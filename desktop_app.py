"""Native Windows vocal-analysis and accompaniment mixer."""

from __future__ import annotations

import io
import queue
import re
import threading
import wave
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

import numpy as np
import pygame
import soundfile as sf

from music_engine import (
    build_chords,
    create_midi,
    create_piano_wav,
    create_vocal_notes_wav,
    infer_key,
    suggest_tempo,
)
from vocal_analyzer import detect_notes, note_solfege, note_spelling


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
MAX_AUDIO_SECONDS = 180.0
MAX_AUDIO_BYTES = 50 * 1024 * 1024
BG = "#111318"
PANEL = "#1a1e25"
PANEL_INNER = "#20252e"
LINE = "#303744"
TEXT = "#eef0f4"
MUTED = "#9ca6b5"
ACCENT = "#c7a6ff"
MINT = "#86e4cc"


def _wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Encode floating-point audio as a standard PCM WAV for the mixer."""
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 1:
        channels = 1
    elif samples.ndim == 2:
        if samples.shape[1] > 2:
            samples = samples[:, :2]
        channels = samples.shape[1]
    else:
        raise ValueError("The audio must have one or two channels.")

    pcm = (np.clip(np.nan_to_num(samples), -1.0, 1.0) * 32767).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return output.getvalue()


class VocalMixerApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("AI Musician — Vocal Mixer")
        self.root.geometry("1100x790")
        self.root.minsize(860, 680)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        self.events: queue.Queue = queue.Queue()
        self.audio_path: Path | None = None
        self.audio_data: np.ndarray | None = None
        self.sample_rate = 0
        self.duration = 0.0
        self.notes: list[dict] = []
        self.key = ""
        self.mode = ""
        self.chords: list[dict] = []
        self.vocal_sound: pygame.mixer.Sound | None = None
        self.piano_sound: pygame.mixer.Sound | None = None
        self.melody_sound: pygame.mixer.Sound | None = None
        self.vocal_channel = None
        self.piano_channel = None
        self.melody_channel = None
        self.busy = False

        self.status = tk.StringVar(value="Choose a vocal recording to get started.")
        self.selected_file = tk.StringVar(value="No vocal selected")
        self.key_value = tk.StringVar(value="—")
        self.tempo_value = tk.StringVar(value="100")
        self.note_count_value = tk.StringVar(value="—")
        self.vocal_volume = tk.DoubleVar(value=80)
        self.piano_volume = tk.DoubleVar(value=65)

        self._configure_theme()
        self._build_interface()
        self._initialize_audio()
        self.root.after(100, self._poll_events)

    def _configure_theme(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background=PANEL_INNER,
            fieldbackground=PANEL_INNER,
            foreground=TEXT,
            rowheight=27,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background=PANEL,
            foreground=MUTED,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Treeview",
            background=[("selected", "#39304a")],
            foreground=[("selected", TEXT)],
        )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=PANEL_INNER,
            background=ACCENT,
            bordercolor=PANEL_INNER,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )

    def _panel(self, parent: tk.Widget, **kwargs: object) -> tk.Frame:
        return tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1, **kwargs)

    def _build_interface(self) -> None:
        shell = tk.Frame(self.root, bg=BG, padx=24, pady=18)
        shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(3, weight=1)

        header = tk.Frame(shell, bg=BG)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        tk.Label(header, text="AI MUSICIAN", bg=BG, fg=TEXT, font=("Segoe UI", 19, "bold")).pack(side="left")
        tk.Label(
            header,
            text="VOCAL MIXER  ·  PRIVATE DESKTOP APP",
            bg=BG,
            fg=MINT,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="right", pady=(7, 0))

        upload = self._panel(shell)
        upload.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        upload.grid_columnconfigure(1, weight=1)
        self.choose_button = self._button(upload, "Choose vocal", self._choose_audio)
        self.choose_button.grid(row=0, column=0, padx=14, pady=12)
        tk.Label(
            upload,
            textvariable=self.selected_file,
            bg=PANEL,
            fg=MUTED,
            anchor="w",
            font=("Segoe UI", 10),
        ).grid(row=0, column=1, sticky="ew", padx=(0, 12))
        self.analyze_button = self._button(upload, "Analyze vocal", self._analyze, primary=True)
        self.analyze_button.grid(row=0, column=2, padx=(0, 14), pady=12)
        self.progress = ttk.Progressbar(upload, mode="determinate", maximum=100, style="Horizontal.TProgressbar")
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 10))
        self.progress.grid_remove()
        self.analyze_button.configure(state="disabled")

        stats = tk.Frame(shell, bg=BG)
        stats.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        for column, (label, variable) in enumerate(
            (("ESTIMATED KEY", self.key_value), ("TEMPO ESTIMATE · EDITABLE", self.tempo_value), ("DETECTED NOTES", self.note_count_value))
        ):
            stats.grid_columnconfigure(column, weight=1)
            card = self._panel(stats)
            card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 6 if column < 2 else 0))
            tk.Label(card, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(9, 0))
            if column == 1:
                tk.Spinbox(
                    card,
                    from_=40,
                    to=220,
                    increment=1,
                    textvariable=variable,
                    width=7,
                    bg=PANEL_INNER,
                    fg=TEXT,
                    insertbackground=TEXT,
                    buttonbackground=PANEL_INNER,
                    relief="flat",
                    font=("Segoe UI", 14, "bold"),
                ).pack(anchor="w", padx=12, pady=(3, 8))
            else:
                tk.Label(card, textvariable=variable, bg=PANEL, fg=TEXT, font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=12, pady=(2, 9))

        lower = tk.Frame(shell, bg=BG)
        lower.grid(row=3, column=0, sticky="nsew")
        lower.grid_rowconfigure(0, weight=1)
        lower.grid_columnconfigure(0, weight=3)
        lower.grid_columnconfigure(1, weight=2)

        notes_panel = self._panel(lower)
        notes_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        notes_panel.grid_rowconfigure(1, weight=1)
        notes_panel.grid_columnconfigure(0, weight=1)
        self._section_heading(notes_panel, "Detected vocal notes", "Movable Do · sharp/flat names · frequency in Hz")
        table_frame = tk.Frame(notes_panel, bg=PANEL, padx=12)
        table_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        columns = ("number", "time", "syllable", "pitch", "frequency", "change")
        self.note_table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        for column, title, width in (
            ("number", "#", 42),
            ("time", "TIME", 82),
            ("syllable", "NOTE", 90),
            ("pitch", "PITCH", 125),
            ("frequency", "FREQUENCY", 100),
            ("change", "MOVEMENT", 112),
        ):
            self.note_table.heading(column, text=title)
            self.note_table.column(column, width=width, minwidth=40, anchor="center", stretch=column == "pitch")
        note_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.note_table.yview)
        self.note_table.configure(yscrollcommand=note_scroll.set)
        self.note_table.grid(row=0, column=0, sticky="nsew")
        note_scroll.grid(row=0, column=1, sticky="ns")

        mixer = self._panel(lower)
        mixer.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        mixer.grid_columnconfigure(0, weight=1)
        self._section_heading(mixer, "Studio mixer", "Independent track levels")
        strips = tk.Frame(mixer, bg=PANEL, padx=12)
        strips.grid(row=1, column=0, sticky="ew")
        strips.grid_columnconfigure(0, weight=1)
        strips.grid_columnconfigure(1, weight=1)
        self._make_fader(strips, 0, "ORIGINAL VOCAL", self.vocal_volume, self._set_vocal_volume)
        self._make_fader(strips, 1, "AI PIANO", self.piano_volume, self._set_piano_volume)

        controls = tk.Frame(mixer, bg=PANEL, padx=12, pady=12)
        controls.grid(row=2, column=0, sticky="ew")
        self.play_mix_button = self._button(controls, "Play vocal + piano", self._play_mix, primary=True)
        self.play_mix_button.pack(fill="x", pady=(0, 8))
        self.play_notes_button = self._button(controls, "Play vocal-note melody", self._play_notes)
        self.play_notes_button.pack(fill="x", pady=(0, 8))
        self.stop_button = self._button(controls, "Stop", self._stop_audio)
        self.stop_button.pack(fill="x", pady=(0, 9))
        self.generate_button = self._button(controls, "Generate / update piano", self._generate)
        self.generate_button.pack(fill="x")
        self._set_playback_buttons(False)
        self.generate_button.configure(state="disabled")

        tk.Label(
            mixer,
            text="Piano note playback follows the singer's detected timing. Mix playback starts the original vocal and piano together.",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=310,
            font=("Segoe UI", 9),
        ).grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 12))

        footer = tk.Frame(shell, bg=BG)
        footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        tk.Label(footer, textvariable=self.status, bg=BG, fg=MUTED, anchor="w", font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True)
        tk.Label(footer, text="Files saved in output\\", bg=BG, fg="#7e8795", font=("Segoe UI", 9)).pack(side="right")

    def _section_heading(self, parent: tk.Widget, title: str, subtitle: str) -> None:
        heading = tk.Frame(parent, bg=PANEL, padx=13, pady=12)
        heading.grid(row=0, column=0, sticky="ew")
        tk.Label(heading, text=title, bg=PANEL, fg=TEXT, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(heading, text=subtitle, bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 0))

    def _button(
        self,
        parent: tk.Widget,
        title: str,
        command: object,
        *,
        primary: bool = False,
    ) -> tk.Button:
        background = ACCENT if primary else PANEL_INNER
        foreground = "#17131d" if primary else TEXT
        return tk.Button(
            parent,
            text=title,
            command=command,
            bg=background,
            fg=foreground,
            activebackground="#d9c5ff" if primary else "#333a47",
            activeforeground=foreground,
            disabledforeground="#737b87",
            relief="flat",
            padx=12,
            pady=9,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )

    def _make_fader(
        self,
        parent: tk.Widget,
        column: int,
        title: str,
        variable: tk.DoubleVar,
        command: object,
    ) -> None:
        frame = tk.Frame(parent, bg=PANEL_INNER, padx=10, pady=12)
        frame.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 4, 4 if column == 0 else 0))
        tk.Label(frame, text=title, bg=PANEL_INNER, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        volume_label = tk.Label(frame, text=f"{round(variable.get())}%", bg=PANEL_INNER, fg=TEXT, font=("Segoe UI", 12, "bold"))
        volume_label.pack(anchor="w", pady=(7, 0))
        scale = tk.Scale(
            frame,
            from_=100,
            to=0,
            orient="vertical",
            variable=variable,
            command=lambda value: (volume_label.configure(text=f"{round(float(value))}%"), command(value)),
            bg=PANEL_INNER,
            fg=TEXT,
            troughcolor="#343b47",
            activebackground=ACCENT,
            highlightthickness=0,
            showvalue=False,
            length=178,
            width=18,
            sliderlength=24,
            bd=0,
        )
        scale.pack(fill="x", pady=(5, 0))

    def _initialize_audio(self) -> None:
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(8)
            self.vocal_channel = pygame.mixer.Channel(0)
            self.piano_channel = pygame.mixer.Channel(1)
            self.melody_channel = pygame.mixer.Channel(2)
        except pygame.error as error:
            self.status.set(f"Audio output is unavailable: {error}")

    def _choose_audio(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a vocal recording",
            filetypes=(
                ("Supported audio", "*.mp3 *.wav *.flac *.ogg *.aiff *.aif"),
                ("All files", "*.*"),
            ),
        )
        if not path:
            return
        candidate = Path(path)
        if candidate.stat().st_size > MAX_AUDIO_BYTES:
            messagebox.showerror("File too large", "Choose an audio file smaller than 50 MB.")
            return
        self._stop_audio()
        self.audio_path = candidate
        self.selected_file.set(candidate.name)
        self.analyze_button.configure(state="normal")
        self.audio_data = None
        self.notes = []
        self.chords = []
        self.key_value.set("—")
        self.note_count_value.set("—")
        self._clear_notes()
        self._set_playback_buttons(False)
        self.status.set("Audio selected. Select Analyze vocal.")
        self.generate_button.configure(state="disabled")

    def _analyze(self) -> None:
        if self.busy:
            return
        if not self.audio_path:
            messagebox.showinfo("Choose audio", "Choose a vocal recording first.")
            return
        self.busy = True
        self._set_busy(True, "Loading and analyzing the vocal…")
        path = self.audio_path
        threading.Thread(target=self._analyze_worker, args=(path,), daemon=True).start()

    def _analyze_worker(self, path: Path) -> None:
        try:
            audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
            duration = len(audio) / sample_rate
            if not 0 < duration <= MAX_AUDIO_SECONDS:
                raise ValueError("Audio must be longer than zero and no more than 3 minutes.")

            def progress(value: int) -> None:
                self.events.put(("progress", value))

            notes = detect_notes(audio, sample_rate, progress_callback=progress)
            if not notes:
                raise ValueError("No clear sung notes were found. Try a louder, cleaner vocal.")
            key, mode, _ = infer_key(notes)
            bpm = suggest_tempo(notes)
            chords = build_chords(notes, duration, bpm)
            self.events.put(
                ("analysis", {"audio": audio, "sample_rate": sample_rate, "duration": duration,
                              "notes": notes, "key": key, "mode": mode, "bpm": bpm, "chords": chords})
            )
        except Exception as error:
            self.events.put(("error", str(error)))

    def _generate(self) -> None:
        if self.busy:
            return
        if self.audio_data is None or not self.notes:
            messagebox.showinfo("Analyze vocal", "Analyze a vocal recording before generating the piano.")
            return
        try:
            bpm = int(self.tempo_value.get())
        except ValueError:
            messagebox.showerror("Invalid tempo", "Enter a whole-number tempo between 40 and 220 BPM.")
            return
        if not 40 <= bpm <= 220:
            messagebox.showerror("Invalid tempo", "Tempo must be between 40 and 220 BPM.")
            return

        self.busy = True
        self._set_busy(True, "Rendering piano chords, note melody, and MIDI…")
        request = {
            "audio": self.audio_data,
            "sample_rate": self.sample_rate,
            "duration": self.duration,
            "notes": self.notes,
            "bpm": bpm,
            "source_stem": re.sub(r"[^A-Za-z0-9_-]+", "_", self.audio_path.stem).strip("_")
            if self.audio_path
            else "vocal",
        }
        threading.Thread(target=self._render_worker, args=(request,), daemon=True).start()

    def _render_worker(self, request: dict) -> None:
        try:
            bpm = request["bpm"]
            chords = build_chords(request["notes"], request["duration"], bpm)
            vocal_wav = _wav_bytes(request["audio"], request["sample_rate"])
            piano_wav = create_piano_wav(chords, bpm)
            melody_wav = create_vocal_notes_wav(request["notes"])
            midi_data = create_midi(request["notes"], chords, bpm)
            OUTPUT_DIR.mkdir(exist_ok=True)
            source_stem = request["source_stem"] or "vocal"
            outputs = {
                OUTPUT_DIR / f"{source_stem}_vocal.wav": vocal_wav,
                OUTPUT_DIR / f"{source_stem}_ai_piano_{bpm}bpm.wav": piano_wav,
                OUTPUT_DIR / f"{source_stem}_vocal_note_melody.wav": melody_wav,
                OUTPUT_DIR / f"{source_stem}_ai_accompaniment_{bpm}bpm.mid": midi_data,
            }
            for path, data in outputs.items():
                path.write_bytes(data)
            self.events.put(
                ("rendered", {"vocal": vocal_wav, "piano": piano_wav, "melody": melody_wav,
                              "chords": chords, "bpm": bpm, "outputs": list(outputs)})
            )
        except Exception as error:
            self.events.put(("error", str(error)))

    def _poll_events(self) -> None:
        try:
            while True:
                event, data = self.events.get_nowait()
                if event == "progress":
                    self.progress.configure(value=data)
                elif event == "analysis":
                    self.audio_data = data["audio"]
                    self.sample_rate = data["sample_rate"]
                    self.duration = data["duration"]
                    self.notes = data["notes"]
                    self.key = data["key"]
                    self.mode = data["mode"]
                    self.chords = data["chords"]
                    self.key_value.set(data["key"])
                    self.tempo_value.set(str(data["bpm"]))
                    self.note_count_value.set(str(len(data["notes"])))
                    self._show_notes()
                    self.generate_button.configure(state="normal")
                    self.status.set(f"Detected {len(data['notes'])} notes in {self.audio_path.name if self.audio_path else 'the vocal'}. Review the tempo, then generate the piano.")
                    self._set_playback_buttons(False)
                    self.busy = False
                    self._set_busy(False)
                elif event == "rendered":
                    self.chords = data["chords"]
                    self.tempo_value.set(str(data["bpm"]))
                    self._load_sounds(data)
                    self._set_playback_buttons(self.vocal_sound is not None)
                    self.status.set("Ready. Play the note melody or mix the original vocal and AI piano.")
                    self.busy = False
                    self._set_busy(False)
                    messagebox.showinfo(
                        "Piano ready",
                        "Piano accompaniment, note-by-note melody, original vocal WAV, and MIDI saved in the output folder.",
                    )
                elif event == "error":
                    self.busy = False
                    self._set_busy(False)
                    self.status.set(f"Could not complete the task: {data}")
                    messagebox.showerror("AI Musician", data)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _load_sounds(self, data: dict) -> None:
        if not pygame.mixer.get_init():
            self.status.set("Audio output is unavailable. Check your Windows playback device and restart the app.")
            return
        try:
            self._stop_audio()
            self.vocal_sound = pygame.mixer.Sound(file=io.BytesIO(data["vocal"]))
            self.piano_sound = pygame.mixer.Sound(file=io.BytesIO(data["piano"]))
            self.melody_sound = pygame.mixer.Sound(file=io.BytesIO(data["melody"]))
            self.vocal_sound.set_volume(self.vocal_volume.get() / 100)
            self.piano_sound.set_volume(self.piano_volume.get() / 100)
            self.melody_sound.set_volume(self.piano_volume.get() / 100)
        except pygame.error as error:
            self.vocal_sound = self.piano_sound = self.melody_sound = None
            self.status.set(f"Could not load generated audio: {error}")
            messagebox.showerror("Audio playback", str(error))

    def _show_notes(self) -> None:
        self._clear_notes()
        for index, note in enumerate(self.notes, start=1):
            change = note["frequencyChangeCents"]
            movement = "rising" if change > 25 else "falling" if change < -25 else "steady"
            cents = round(note["cents"])
            cents_text = f"{cents:+d}¢"
            change_text = f"{movement} {round(change):+d}¢"
            self.note_table.insert(
                "",
                "end",
                values=(
                    index,
                    f"{note['start']:.2f} s",
                    note_solfege(note["midi"], self.key, self.mode),
                    note_spelling(note["midi"]),
                    f"{note['frequency']:.1f} Hz {cents_text}",
                    change_text,
                ),
            )

    def _clear_notes(self) -> None:
        for row in self.note_table.get_children():
            self.note_table.delete(row)

    def _set_vocal_volume(self, value: str) -> None:
        volume = max(0.0, min(1.0, float(value) / 100))
        if self.vocal_sound:
            self.vocal_sound.set_volume(volume)
        if self.vocal_channel:
            self.vocal_channel.set_volume(volume)

    def _set_piano_volume(self, value: str) -> None:
        volume = max(0.0, min(1.0, float(value) / 100))
        for sound in (self.piano_sound, self.melody_sound):
            if sound:
                sound.set_volume(volume)
        if self.piano_channel:
            self.piano_channel.set_volume(volume)
        if self.melody_channel:
            self.melody_channel.set_volume(volume)

    def _play_mix(self) -> None:
        if not self.vocal_sound or not self.piano_sound:
            messagebox.showinfo("Generate piano", "Analyze the vocal and generate the piano accompaniment first.")
            return
        self._stop_audio()
        self._set_vocal_volume(str(self.vocal_volume.get()))
        self._set_piano_volume(str(self.piano_volume.get()))
        self.vocal_channel.play(self.vocal_sound)
        self.piano_channel.play(self.piano_sound)
        self.status.set("Playing original vocal and piano together. Adjust either fader while listening.")

    def _play_notes(self) -> None:
        if not self.melody_sound:
            messagebox.showinfo("Generate melody", "Generate the piano first to prepare the note-by-note melody.")
            return
        self._stop_audio()
        self._set_piano_volume(str(self.piano_volume.get()))
        self.melody_channel.play(self.melody_sound)
        self.status.set("Playing the detected melody one note at a time on piano.")

    def _stop_audio(self) -> None:
        for channel in (self.vocal_channel, self.piano_channel, self.melody_channel):
            if channel:
                channel.stop()

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.choose_button.configure(state="disabled" if busy else "normal")
        self.analyze_button.configure(
            state="disabled" if busy or self.audio_path is None else "normal",
        )
        self.generate_button.configure(
            state="disabled" if busy or self.audio_data is None else "normal",
        )
        if message:
            self.status.set(message)
            self.progress.configure(value=0)
            self.progress.grid()
        elif not busy:
            self.progress.grid_remove()

    def _set_playback_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.play_mix_button.configure(state=state)
        self.play_notes_button.configure(state=state)
        self.stop_button.configure(state=state)

    def _close(self) -> None:
        self._stop_audio()
        if pygame.mixer.get_init():
            pygame.mixer.quit()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = VocalMixerApp()
    app.run()


if __name__ == "__main__":
    main()
