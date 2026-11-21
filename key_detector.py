import mido
from collections import Counter

MIDI_FILE = "output/test_basic_pitch.mid"

NOTE_NAMES = [
    "C", "C#", "D", "D#", "E", "F",
    "F#", "G", "G#", "A", "A#", "B"
]

# Major scale intervals
MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]

# Minor scale intervals
MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]


def get_notes():
    mid = mido.MidiFile(MIDI_FILE)
    notes = []

    for track in mid.tracks:
        for message in track:
            if message.type == "note_on" and message.velocity > 0:
                notes.append(message.note % 12)

    return notes


def calculate_score(notes, root, scale):
    scale_notes = {(root + interval) % 12 for interval in scale}
    return sum(1 for note in notes if note in scale_notes)


notes = get_notes()

print("=" * 60)
print("              AI MUSICIAN")
print("             KEY DETECTOR")
print("=" * 60)

print(f"\nNotes analyzed: {len(notes)}")

counts = Counter(notes)

print("\nPitch usage:")
print("-" * 60)

for note_number, count in counts.most_common():
    print(f"{NOTE_NAMES[note_number]:3s} : {count}")

best_key = None
best_score = -1

for root in range(12):

    major_score = calculate_score(notes, root, MAJOR_SCALE)

    if major_score > best_score:
        best_score = major_score
        best_key = f"{NOTE_NAMES[root]} major"

    minor_score = calculate_score(notes, root, MINOR_SCALE)

    if minor_score > best_score:
        best_score = minor_score
        best_key = f"{NOTE_NAMES[root]} minor"


print("\n" + "=" * 60)
print(f"🎵 Estimated key: {best_key}")
print(f"🎯 Matching notes: {best_score}/{len(notes)}")
print("=" * 60)