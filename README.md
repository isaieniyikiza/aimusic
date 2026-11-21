# AI Musician Vocal Mixer

A native Windows desktop app that analyzes a vocal recording, shows the detected notes, plays the note melody on piano, and mixes the original vocal with piano accompaniment using separate track faders. The app opens a desktop window; it does not start a web server or use a browser.

## Windows setup

1. Install Python 3.11 or newer from [python.org/downloads](https://www.python.org/downloads/). The standard Tk interface must be included.
2. Open PowerShell in this project folder.
3. Create and install the audio environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

4. Run the desktop mixer:

   ```powershell
   .\.venv\Scripts\python.exe ai_music_generator.py
   ```

   If `py` is unavailable, create the environment with `python -m venv .venv`. Keep the old `venv` folder out of this setup; it may reference a Python installation from another computer.

## Use

1. Choose an MP3, WAV, FLAC, OGG, or AIFF vocal (up to 50 MB and 3 minutes).
2. Click **Analyze vocal**. The app estimates the key, tempo, note names, singing syllables, frequencies, and pitch movement.
3. Adjust the **Tempo (BPM)** value if needed.
4. Click **Generate / update piano**.
5. Use **Play vocal-note melody** to hear the detected notes one by one at their estimated timings.
6. Use **Play vocal + piano** to start the original recording and piano accompaniment together. Adjust the vocal and piano faders independently; **Stop** halts playback.

Piano accompaniment, the detected-note piano melody, a WAV copy of the input vocal, and a MIDI with separate melody and chord tracks are saved under `output\`.

Pitch and tempo are estimates; a clear solo vocal generally works better than a full mixed song. Audio is analyzed and played locally.

The piano preview is a locally synthesized instrument. The recording in `trainig sound` is not extracted or converted into instrument samples; use only soundfonts and samples you have permission to reuse.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```
"# aimusic" 
