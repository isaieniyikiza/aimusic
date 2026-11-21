import struct
import unittest

import numpy as np

from music_engine import (
    SAMPLE_RATE,
    build_chords,
    create_midi,
    create_piano_wav,
    create_vocal_notes_wav,
    infer_key,
    suggest_tempo,
)
from vocal_analyzer import detect_notes


class MusicEngineTests(unittest.TestCase):
    def setUp(self):
        self.notes = [
            {"midi": pitch, "start": index * 0.5, "duration": 0.35, "confidence": 0.95}
            for index, pitch in enumerate((60, 64, 67, 60, 67, 64, 60, 65))
        ]

    def test_estimates_key_and_quarter_note_tempo(self):
        key, mode, histogram = infer_key(self.notes)
        self.assertEqual((key, mode), ("C major", "major"))
        self.assertGreater(histogram[0], 0)
        self.assertEqual(suggest_tempo(self.notes), 120)

    def test_suggests_one_diatonic_chord_per_bar(self):
        chords = build_chords(self.notes, duration=4, bpm=120)
        self.assertEqual(len(chords), 2)
        self.assertEqual(chords[0]["name"], "C")
        self.assertEqual(chords[0]["notes"], [0, 4, 7])
        self.assertEqual(chords[1]["bar"], 2)

    def test_midi_contains_three_timed_tracks(self):
        chords = build_chords(self.notes, duration=4, bpm=120)
        midi = create_midi(self.notes, chords, bpm=120)
        self.assertEqual(midi[:4], b"MThd")
        header_length, midi_format, tracks, ticks = struct.unpack(">IHHH", midi[4:14])
        self.assertEqual((header_length, midi_format, tracks, ticks), (6, 1, 3, 480))
        self.assertIn(b"\x07\xa1\x20", midi)
        offset = 14
        track_names = []
        for _ in range(tracks):
            self.assertEqual(midi[offset:offset + 4], b"MTrk")
            length = struct.unpack(">I", midi[offset + 4:offset + 8])[0]
            track = midi[offset + 8:offset + 8 + length]
            self.assertEqual(track[-3:], b"\xff\x2f\x00")
            if b"\xff\x03" in track:
                track_names.append(track)
            offset += 8 + length
        self.assertEqual(offset, len(midi))
        self.assertEqual(len(track_names), 3)

    def test_wav_is_audible_pcm(self):
        chords = build_chords(self.notes, duration=4, bpm=120)
        wav = create_piano_wav(chords, bpm=120)
        self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(wav[8:12], b"WAVE")
        self.assertEqual(wav[22:24], b"\x01\x00")
        self.assertGreater(max(wav[44:]), 0)

    def test_vocal_note_wav_preserves_note_timing(self):
        notes = [
            {"midi": 60, "start": 0.5, "duration": 0.4},
            {"midi": 64, "start": 1.0, "duration": 0.3},
        ]
        wav = create_vocal_notes_wav(notes)
        frame_width = 2
        silence_end = round(0.45 * SAMPLE_RATE) * frame_width
        note_start = round(0.55 * SAMPLE_RATE) * frame_width
        note_end = round(0.85 * SAMPLE_RATE) * frame_width
        self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(wav[44:silence_end], bytes(silence_end - 44))
        self.assertTrue(any(wav[note_start:note_end]))
        duration = struct.unpack("<I", wav[40:44])[0] / (SAMPLE_RATE * frame_width)
        self.assertAlmostEqual(duration, 1.65, places=2)

    def test_pitch_tracker_follows_consecutive_sung_notes(self):
        sample_rate = 11025
        first_times = np.arange(round(0.65 * sample_rate)) / sample_rate
        second_times = np.arange(round(0.65 * sample_rate)) / sample_rate
        samples = np.concatenate(
            (
                0.6 * np.sin(2 * np.pi * 440.0 * first_times),
                np.zeros(round(0.18 * sample_rate)),
                0.6 * np.sin(2 * np.pi * 493.88 * second_times),
            )
        )

        notes = detect_notes(samples, sample_rate)

        self.assertEqual([note["midi"] for note in notes], [69, 71])
        self.assertAlmostEqual(notes[0]["frequency"], 440.0, delta=5.0)
        self.assertAlmostEqual(notes[1]["frequency"], 493.88, delta=5.0)
        self.assertLess(notes[0]["start"], notes[1]["start"])


if __name__ == "__main__":
    unittest.main()
