"""Standard-library music analysis helpers and piano accompaniment renderers."""

from __future__ import annotations

import array
import io
import math
import struct
import wave
from collections.abc import Sequence


NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)
MAJOR_QUALITIES = ("major", "minor", "minor", "major", "major", "minor", "diminished")
MINOR_QUALITIES = ("minor", "diminished", "major", "minor", "minor", "major", "major")
TICKS_PER_BEAT = 480
SAMPLE_RATE = 22050


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_norm = sum((value - left_mean) ** 2 for value in left)
    right_norm = sum((value - right_mean) ** 2 for value in right)
    divisor = math.sqrt(left_norm * right_norm)
    return numerator / divisor if divisor else 0.0


def infer_key(notes: Sequence[dict]) -> tuple[str, str, list[float]]:
    """Estimate a major or minor key from pitch-class duration and confidence."""
    histogram = [0.0] * 12
    for note in notes:
        weight = note["duration"] * note.get("confidence", 1.0)
        histogram[note["midi"] % 12] += max(weight, 0.01)

    if not any(histogram):
        raise ValueError("No sung notes were detected. Try a clear, solo vocal recording.")

    best: tuple[float, int, str] | None = None
    for root in range(12):
        for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            rotated = profile[-root:] + profile[:-root] if root else profile
            candidate = (_correlation(histogram, rotated), root, mode)
            if best is None or candidate[0] > best[0]:
                best = candidate

    assert best is not None
    return f"{NOTE_NAMES[best[1]]} {best[2]}", best[2], histogram


def suggest_tempo(notes: Sequence[dict]) -> int:
    """Suggest a plausible BPM from successive vocal note onsets."""
    intervals = [
        right["start"] - left["start"]
        for left, right in zip(notes, notes[1:])
        if 0.18 <= right["start"] - left["start"] <= 1.5
    ]
    if not intervals:
        return 100

    intervals.sort()
    median = intervals[len(intervals) // 2]
    candidates = []
    for multiplier in (0.5, 1.0, 2.0, 4.0):
        bpm = round(60.0 / (median * multiplier))
        if 55 <= bpm <= 180:
            candidates.append(bpm)
    return min(candidates, key=lambda bpm: abs(bpm - 100)) if candidates else 100


def build_chords(notes: Sequence[dict], duration: float, bpm: int) -> list[dict]:
    """Choose one diatonic triad per bar, weighted by the melody in that bar."""
    key_name, mode, _ = infer_key(notes)
    root = NOTE_NAMES.index(key_name.split()[0])
    scale_intervals = (0, 2, 4, 5, 7, 9, 11) if mode == "major" else (0, 2, 3, 5, 7, 8, 10)
    qualities = MAJOR_QUALITIES if mode == "major" else MINOR_QUALITIES
    bar_seconds = 240.0 / bpm
    bar_count = max(1, math.ceil(duration / bar_seconds))
    chord_notes = {
        "major": (0, 4, 7),
        "minor": (0, 3, 7),
        "diminished": (0, 3, 6),
    }
    empty_bar_degrees = (0, 4, 5, 3) if mode == "major" else (0, 5, 2, 6)
    chords = []

    for bar in range(bar_count):
        bar_start = bar * bar_seconds
        bar_end = bar_start + bar_seconds
        weights = [0.0] * 12
        for note in notes:
            overlap = max(
                0.0,
                min(note["start"] + note["duration"], bar_end)
                - max(note["start"], bar_start),
            )
            if overlap:
                weights[note["midi"] % 12] += overlap * note.get("confidence", 1.0)

        candidates = []
        if not any(weights):
            degrees = (empty_bar_degrees[bar % len(empty_bar_degrees)],)
        else:
            degrees = range(7)
        for degree in degrees:
            chord_root = (root + scale_intervals[degree]) % 12
            quality = qualities[degree]
            intervals = chord_notes[quality]
            chord_pcs = {(chord_root + interval) % 12 for interval in intervals}
            score = sum(
                weight * (2.0 if pitch in chord_pcs else 0.15 if pitch in {
                    (root + interval) % 12 for interval in scale_intervals
                } else -0.3)
                for pitch, weight in enumerate(weights)
            )
            score += weights[chord_root] * 0.2
            candidates.append((score, degree, chord_root, quality, intervals))

        _, _, chord_root, quality, intervals = max(candidates, key=lambda candidate: candidate[0])
        suffix = {"major": "", "minor": "m", "diminished": "dim"}[quality]
        label = f"{NOTE_NAMES[chord_root]}{suffix}"
        chords.append(
            {
                "bar": bar + 1,
                "start": round(bar_start, 3),
                "duration": round(min(bar_seconds, max(0.0, duration - bar_start)), 3),
                "name": label,
                "root": chord_root,
                "quality": quality,
                "notes": [chord_root, (chord_root + intervals[1]) % 12, (chord_root + intervals[2]) % 12],
            }
        )

    return chords


def _variable_length(value: int) -> bytes:
    value = max(0, value)
    encoded = [value & 0x7F]
    value >>= 7
    while value:
        encoded.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(encoded)


def _midi_track(name: str, events: list[tuple[int, int, bytes]]) -> bytes:
    name_bytes = name.encode("ascii")
    events.extend(
        [
            (0, -2, b"\xff\x03" + _variable_length(len(name_bytes)) + name_bytes),
            (0, -1, b"\xc0\x00"),
        ]
    )
    events.sort(key=lambda event: (event[0], event[1]))
    track = bytearray()
    previous_tick = 0
    for tick, _, message in events:
        track.extend(_variable_length(tick - previous_tick))
        track.extend(message)
        previous_tick = tick
    track.extend(b"\x00\xff\x2f\x00")
    return b"MTrk" + struct.pack(">I", len(track)) + track


def create_midi(notes: Sequence[dict], chords: Sequence[dict], bpm: int) -> bytes:
    """Write a standard MIDI file containing a piano accompaniment and vocal line."""
    tempo = round(60_000_000 / bpm)
    tempo_track = bytearray(b"\x00\xff\x03\x05Tempo")
    tempo_track.extend(b"\x00\xff\x51\x03" + tempo.to_bytes(3, "big"))
    tempo_track.extend(b"\x00\xff\x58\x04\x04\x02\x18\x08")
    tempo_track.extend(b"\x00\xff\x2f\x00")
    tracks = [b"MTrk" + struct.pack(">I", len(tempo_track)) + tempo_track]

    piano_events: list[tuple[int, int, bytes]] = []
    melody_events: list[tuple[int, int, bytes]] = []
    for chord in chords:
        start_tick = round(chord["start"] * bpm / 60 * TICKS_PER_BEAT)
        end_tick = start_tick + round(4 * TICKS_PER_BEAT)
        root = chord["root"]
        third, fifth = chord["notes"][1:]
        pitches = (48 + root, 60 + root, 60 + third, 60 + fifth)
        for pitch in pitches:
            piano_events.append((start_tick, 1, bytes((0x90, pitch, 72))))
            piano_events.append((end_tick, 0, bytes((0x80, pitch, 0))))

    for note in notes:
        start_tick = max(0, round(note["start"] * bpm / 60 * TICKS_PER_BEAT))
        end_tick = start_tick + max(1, round(note["duration"] * bpm / 60 * TICKS_PER_BEAT))
        pitch = note["midi"]
        melody_events.append((start_tick, 1, bytes((0x90, pitch, 90))))
        melody_events.append((end_tick, 0, bytes((0x80, pitch, 0))))

    tracks.append(_midi_track("Piano accompaniment", piano_events))
    tracks.append(_midi_track("Detected vocal melody", melody_events))
    return b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), TICKS_PER_BEAT) + b"".join(tracks)


def create_piano_wav(
    chords: Sequence[dict],
    bpm: int,
    melody: Sequence[dict] = (),
) -> bytes:
    """Render piano-style chords and optional timed melody notes to a WAV."""
    bar_seconds = 240.0 / bpm
    last_melody_note = max(
        (note["start"] + note["duration"] for note in melody),
        default=0.0,
    )
    empty_duration = bar_seconds if not chords and not melody else 0.0
    duration = max(empty_duration, len(chords) * bar_seconds, last_melody_note) + 0.35
    total_samples = round(duration * SAMPLE_RATE)
    mix = array.array("f", [0.0]) * total_samples
    waveform_cache: dict[tuple[int, int], array.array] = {}

    def add_voice(pitch: int, start_sample: int, length: int, gain: float) -> None:
        cache_key = (pitch, length)
        samples = waveform_cache.get(cache_key)
        if samples is None:
            frequency = 440.0 * 2 ** ((pitch - 69) / 12)
            attack_samples = max(1, round(0.012 * SAMPLE_RATE))
            release_samples = max(1, round(0.16 * SAMPLE_RATE))
            samples = array.array("f")
            for index in range(length):
                attack = min(1.0, index / attack_samples)
                release = min(1.0, (length - index) / release_samples)
                decay = 0.24 + 0.76 * math.exp(-index / (SAMPLE_RATE * 0.58))
                envelope = attack * decay * release
                phase = 2 * math.pi * frequency * index / SAMPLE_RATE
                tone = (
                    0.55 * math.sin(phase)
                    + 0.23 * math.sin(2 * phase)
                    + 0.12 * math.sin(3 * phase)
                    + 0.065 * math.sin(4 * phase)
                    + 0.035 * math.sin(5 * phase)
                )
                hammer = 0.012 * math.exp(-index / (SAMPLE_RATE * 0.004)) * math.sin(phase * 7)
                samples.append((tone + hammer) * envelope)
            waveform_cache[cache_key] = samples

        available = min(len(samples), total_samples - start_sample)
        for index in range(available):
            mix[start_sample + index] += samples[index] * gain

    for chord in chords:
        start_sample = round(chord["start"] * SAMPLE_RATE)
        length = min(
            round(bar_seconds * SAMPLE_RATE),
            max(1, total_samples - start_sample),
        )
        root = chord["root"]
        pitches = (48 + root, 60 + root, 60 + chord["notes"][1], 60 + chord["notes"][2])
        for voice, pitch in enumerate(pitches):
            add_voice(pitch, start_sample, length, 0.22 if voice == 0 else 0.16)

    for note in melody:
        start_sample = round(note["start"] * SAMPLE_RATE)
        length = min(
            max(1, round(note["duration"] * SAMPLE_RATE)),
            max(1, total_samples - start_sample),
        )
        add_voice(note["midi"], start_sample, length, 0.34)

    pcm = array.array(
        "h",
        (round(max(-0.96, min(0.96, sample)) * 32767) for sample in mix),
    )
    if pcm.itemsize != 2:
        pcm.byteswap()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())
    return output.getvalue()


def create_vocal_notes_wav(notes: Sequence[dict]) -> bytes:
    """Render each detected vocal note at its original time as a piano note."""
    return create_piano_wav((), 120, melody=notes)
