import mido
from mido import MidiFile, MidiTrack, Message, MetaMessage

OUTPUT_FILE = "output/ai_accompaniment.mid"

# Chord notes as MIDI numbers
CHORDS = {
    "C":  [60, 64, 67],   # C4 E4 G4
    "G":  [55, 59, 62],   # G3 B3 D4
    "Am": [57, 60, 64],   # A3 C4 E4
    "F":  [53, 57, 60],   # F3 A3 C4
}

# Chord progression
PROGRESSION = ["C", "G", "Am", "F"]

# MIDI settings
TICKS_PER_BEAT = 480
BEATS_PER_CHORD = 4

mid = MidiFile(ticks_per_beat=TICKS_PER_BEAT)

track = MidiTrack()
mid.tracks.append(track)

# Track name
track.append(
    MetaMessage(
        "track_name",
        name="AI Musician Piano",
        time=0
    )
)

print("=" * 60)
print("              AI MUSICIAN")
print("          PIANO ACCOMPANIMENT")
print("=" * 60)

print("\nGenerating chord progression:")
print(" → ".join(PROGRESSION))

print()

for chord_name in PROGRESSION:

    notes = CHORDS[chord_name]

    print(f"Playing chord: {chord_name}")

    # Start all chord notes
    for note in notes:
        track.append(
            Message(
                "note_on",
                note=note,
                velocity=70,
                time=0
            )
        )

    # Hold chord for 4 beats
    track.append(
        Message(
            "note_off",
            note=notes[0],
            velocity=0,
            time=TICKS_PER_BEAT * BEATS_PER_CHORD
        )
    )

    # Other notes stop at the same time
    for note in notes[1:]:
        track.append(
            Message(
                "note_off",
                note=note,
                velocity=0,
                time=0
            )
        )

mid.save(OUTPUT_FILE)

print("\n" + "=" * 60)
print(f"🎹 Saved accompaniment to:")
print(OUTPUT_FILE)
print("=" * 60)