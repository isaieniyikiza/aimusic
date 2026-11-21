"""Local monophonic vocal pitch tracking for the desktop mixer."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np


_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_FLAT_NAMES = {1: "D♭", 3: "E♭", 6: "G♭", 8: "A♭", 10: "B♭"}
_MAJOR_SOLFEGGE = ("do", "di / ra", "re", "ri / me", "mi", "fa", "fi / se", "sol", "si / le", "la", "li / te", "ti")
_MINOR_SOLFEGGE = ("do", "di / ra", "re", "ri / me", "mi", "fa", "fi / se", "sol", "si / le", "la", "li / te", "ti")
_TARGET_SAMPLE_RATE = 11025
_FRAME_SIZE = 2048
_HOP_SECONDS = 0.085


def note_spelling(midi_note: int) -> str:
    pitch_class = midi_note % 12
    octave = midi_note // 12 - 1
    sharp = _NOTE_NAMES[pitch_class].replace("#", "♯")
    flat = _FLAT_NAMES.get(pitch_class)
    if flat:
        return f"{sharp}{octave} / {flat}{octave}"
    return f"{sharp}{octave}"


def note_solfege(midi_note: int, key: str, mode: str) -> str:
    root_name = key.split()[0].replace("♯", "#")
    try:
        root = _NOTE_NAMES.index(root_name)
    except ValueError:
        return "note"
    syllables = _MINOR_SOLFEGGE if mode == "minor" else _MAJOR_SOLFEGGE
    return syllables[(midi_note - root) % 12]


def _detect_pitch(
    frame: np.ndarray,
    sample_rate: int,
    min_lag: int,
    max_lag: int,
    window: np.ndarray,
) -> dict | None:
    windowed = frame * window
    if not np.any(windowed):
        return None

    fft_size = 1 << (2 * _FRAME_SIZE - 1).bit_length()
    spectrum = np.fft.rfft(windowed, n=fft_size)
    autocorrelation = np.fft.irfft(spectrum.conjugate() * spectrum, n=fft_size)[:max_lag + 1]
    squared = windowed * windowed
    prefix_energy = np.concatenate(([0.0], np.cumsum(squared)))
    lags = np.arange(min_lag, max_lag + 1)
    differences = (
        prefix_energy[_FRAME_SIZE - lags]
        + prefix_energy[_FRAME_SIZE]
        - prefix_energy[lags]
        - 2 * autocorrelation[lags]
    )
    differences = np.maximum(differences, 0)
    cumulative = np.cumsum(differences)
    normalized = np.divide(
        differences * np.arange(1, len(lags) + 1),
        cumulative,
        out=np.ones_like(differences),
        where=cumulative > 0,
    )

    valleys = np.flatnonzero(
        (normalized < 0.16)
        & np.r_[normalized[:-1] <= normalized[1:], True]
    )
    best_index = int(valleys[0]) if len(valleys) else int(np.argmin(normalized))
    best_score = float(normalized[best_index])
    if best_score > 0.30:
        return None

    adjustment = 0.0
    if 0 < best_index < len(normalized) - 1:
        left, center, right = normalized[best_index - 1:best_index + 2]
        denominator = 2 * (2 * center - right - left)
        if denominator:
            adjustment = float((right - left) / denominator)

    frequency = sample_rate / (lags[best_index] + adjustment)
    if not 65 <= frequency <= 1000:
        return None
    midi = round(69 + 12 * math.log2(frequency / 440))
    return {
        "midi": midi,
        "frequency": float(frequency),
        "confidence": max(0.0, min(1.0, 1.0 - best_score)),
    }


def _group_frames(frames: list[dict], hop_seconds: float) -> list[dict]:
    notes: list[dict] = []
    active: dict | None = None

    def finish() -> None:
        nonlocal active
        if active and active["end"] - active["start"] >= 0.085:
            frequencies = active["frequencies"]
            edge_count = min(3, len(frequencies))
            start_frequency = sum(frequencies[:edge_count]) / edge_count
            end_frequency = sum(frequencies[-edge_count:]) / edge_count
            midi = max(24, min(108, round(active["weighted_midi"] / active["weight"])))
            frequency = active["weighted_frequency"] / active["weight"]
            cents = 1200 * math.log2(frequency / (440 * 2 ** ((midi - 69) / 12)))
            frequency_change = 1200 * math.log2(end_frequency / start_frequency)
            notes.append(
                {
                    "midi": midi,
                    "start": round(active["start"], 3),
                    "duration": round(active["end"] - active["start"], 3),
                    "confidence": round(min(1.0, active["confidence"] / active["frames"]), 3),
                    "frequency": round(frequency, 2),
                    "cents": round(cents, 1),
                    "frequencyChangeCents": round(frequency_change, 1),
                }
            )
        active = None

    for frame in frames:
        pitch = frame["pitch"]
        if pitch is None or pitch["confidence"] < 0.69:
            if active and frame["time"] - active["end"] > 0.14:
                finish()
            continue

        midi = pitch["midi"]
        if active and frame["time"] - active["end"] <= 0.14 and abs(midi - active["average_midi"]) <= 1:
            weight = max(0.1, pitch["confidence"])
            active["weighted_midi"] += midi * weight
            active["weighted_frequency"] += pitch["frequency"] * weight
            active["weight"] += weight
            active["average_midi"] = active["weighted_midi"] / active["weight"]
            active["confidence"] += pitch["confidence"]
            active["frames"] += 1
            active["frequencies"].append(pitch["frequency"])
            active["end"] = frame["time"] + hop_seconds
        else:
            finish()
            weight = pitch["confidence"]
            active = {
                "start": frame["time"],
                "end": frame["time"] + hop_seconds,
                "weighted_midi": midi * weight,
                "weighted_frequency": pitch["frequency"] * weight,
                "weight": weight,
                "average_midi": midi,
                "confidence": pitch["confidence"],
                "frames": 1,
                "frequencies": [pitch["frequency"]],
            }

    finish()
    return notes


def detect_notes(
    audio: np.ndarray,
    sample_rate: int,
    progress_callback: Callable[[int], None] | None = None,
) -> list[dict]:
    """Estimate note pitches and timing in mono or multichannel floating audio."""
    if sample_rate <= 0 or audio.size == 0:
        raise ValueError("The audio recording is empty or has an invalid sample rate.")
    if not np.isfinite(audio).all():
        raise ValueError("The audio contains invalid sample values.")

    if audio.ndim == 2:
        mono = audio.mean(axis=1)
    elif audio.ndim == 1:
        mono = audio
    else:
        raise ValueError("The audio must have one or two channels.")

    decimation = max(1, round(sample_rate / _TARGET_SAMPLE_RATE))
    mono = mono[::decimation].astype(np.float64, copy=False)
    effective_rate = max(1, round(sample_rate / decimation))
    if len(mono) < _FRAME_SIZE:
        mono = np.pad(mono, (0, _FRAME_SIZE - len(mono)))
    peak = float(np.max(np.abs(mono)))
    if peak < 0.0005:
        raise ValueError("The recording is silent or too quiet to analyze.")

    hop = max(1, round(effective_rate * _HOP_SECONDS))
    min_lag = max(2, int(effective_rate / 1000))
    max_lag = min(int(effective_rate / 65), _FRAME_SIZE // 2)
    silence_threshold = max(0.0015, peak * 0.018)
    window = np.hanning(_FRAME_SIZE)
    frame_count = max(1, (len(mono) - _FRAME_SIZE) // hop + 1)
    frames = []

    for index, offset in enumerate(range(0, len(mono) - _FRAME_SIZE + 1, hop), start=1):
        frame = mono[offset:offset + _FRAME_SIZE]
        rms = float(np.sqrt(np.mean(frame * frame)))
        pitch = (
            _detect_pitch(frame, effective_rate, min_lag, max_lag, window)
            if rms >= silence_threshold
            else None
        )
        frames.append({"time": offset / effective_rate, "pitch": pitch})
        if progress_callback and (index == frame_count or index % 20 == 0):
            progress_callback(round(index * 100 / frame_count))

    return _group_frames(frames, hop / effective_rate)
