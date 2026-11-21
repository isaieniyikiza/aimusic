from mido import MidiFile, MidiTrack, Message, MetaMessage, bpm2tempo

# Create MIDI file
mid = MidiFile(ticks_per_beat=480)

track = MidiTrack()
mid.tracks.append(track)

# Tempo: 120 BPM
track.append(
    MetaMessage(
        'set_tempo',
        tempo=bpm2tempo(120)
    )
)

# Acoustic Bass
track.append(
    Message(
        'program_change',
        program=32,
        time=0
    )
)

# C major progression
# C -> G -> Am -> F

progression = [
    ("C", 36, 43),   # C2 -> G2
    ("G", 31, 38),   # G1 -> D2
    ("Am", 33, 40),  # A1 -> E2
    ("F", 29, 36)    # F1 -> C2
]

ticks = 480

for name, root, fifth in progression:

    # Beat 1 - root
    track.append(
        Message(
            'note_on',
            note=root,
            velocity=90,
            time=0
        )
    )

    track.append(
        Message(
            'note_off',
            note=root,
            velocity=70,
            time=ticks
        )
    )

    # Beat 2 - fifth
    track.append(
        Message(
            'note_on',
            note=fifth,
            velocity=75,
            time=0
        )
    )

    track.append(
        Message(
            'note_off',
            note=fifth,
            velocity=65,
            time=ticks
        )
    )

    # Beat 3 - root
    track.append(
        Message(
            'note_on',
            note=root,
            velocity=85,
            time=0
        )
    )

    track.append(
        Message(
            'note_off',
            note=root,
            velocity=70,
            time=ticks
        )
    )

    # Beat 4 - fifth
    track.append(
        Message(
            'note_on',
            note=fifth,
            velocity=75,
            time=0
        )
    )

    track.append(
        Message(
            'note_off',
            note=fifth,
            velocity=65,
            time=ticks
        )

    )

# Save
mid.save("output/ai_bass.mid")

print("🎸 Bass MIDI created!")
print("Saved to: output/ai_bass.mid")