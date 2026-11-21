import mido

MIDI_FILE = "output/test_basic_pitch.mid"

NOTE_NAMES = [
    "C", "C#", "D", "D#", "E", "F",
    "F#", "G", "G#", "A", "A#", "B"
]

def midi_to_note(note_number):
    octave = (note_number // 12) - 1
    note_name = NOTE_NAMES[note_number % 12]
    return f"{note_name}{octave}"


print("=" * 60)
print("              AI MUSICIAN")
print("           MELODY ANALYZER")
print("=" * 60)

mid = mido.MidiFile(MIDI_FILE)

print(f"\nMIDI file: {MIDI_FILE}")
print(f"Tracks: {len(mid.tracks)}")
print(f"Ticks per beat: {mid.ticks_per_beat}")

print("\nDetected melody:")
print("-" * 60)

note_count = 0

for track_number, track in enumerate(mid.tracks):

    for message in track:

        if message.type == "note_on" and message.velocity > 0:

            note_count += 1

            note_name = midi_to_note(message.note)

            print(
                f"{note_count:3d}. "
                f"MIDI {message.note:3d}  →  "
                f"{note_name:4s}  "
                f"Velocity: {message.velocity}"
            )

print("-" * 60)
print(f"Total detected notes: {note_count}")

print("\nAnalysis complete!")