import mido
from collections import Counter

MIDI_FILE = "output/test_basic_pitch.mid"

NOTE_NAMES = [
    "C", "C#", "D", "D#", "E", "F",
    "F#", "G", "G#", "A", "A#", "B"
]

# Chords available in C major
CHORDS = {
    "C":  [0, 4, 7],
    "Dm": [2, 5, 9],
    "Em": [4, 7, 11],
    "F":  [5, 9, 0],
    "G":  [7, 11, 2],
    "Am": [9, 0, 4],
    "Bdim": [11, 2, 5]
}

# MIDI note numbers belonging to C major
C_MAJOR = {0, 2, 4, 5, 7, 9, 11}


def get_melody_notes():
    mid = mido.MidiFile(MIDI_FILE)

    notes = []

    for track in mid.tracks:
        for message in track:

            if message.type == "note_on" and message.velocity > 0:
                notes.append(message.note % 12)

    return notes


def chord_score(notes, chord_notes):
    score = 0

    for note in notes:
        if note in chord_notes:
            score += 1

    return score


melody = get_melody_notes()

print("=" * 60)
print("              AI MUSICIAN")
print("            CHORD GENERATOR")
print("=" * 60)

print("\nDetected key: C major")

print("\nTesting chords...")
print("-" * 60)

scores = {}

for chord_name, chord_notes in CHORDS.items():

    score = chord_score(melody, chord_notes)

    scores[chord_name] = score

    print(f"{chord_name:5s} → {score} matching melody notes")


best_chord = max(scores, key=scores.get)

print("\n" + "=" * 60)

print(f"🎹 Best matching chord: {best_chord}")

print("=" * 60)

print("\nChord ranking:")

for chord, score in sorted(
    scores.items(),
    key=lambda item: item[1],
    reverse=True
):

    print(f"{chord:5s} : {score}")