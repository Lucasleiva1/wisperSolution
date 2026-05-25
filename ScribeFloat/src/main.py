"""
ScribeFloat - UI Principal
Ventana flotante + Mini mode (icono con ondas) + System Tray + Hotkey global.
"""
import customtkinter as ctk
import ctypes, threading, math, sys, os, time, keyboard, queue
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
import pystray
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import clean_text, save_transcription

from config import load_config, save_config
from settings_ui import SettingsPanel

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Colores
C = {
    "bg0": "#0d0d0d", "bg1": "#121212", "bg2": "#1a1a1a",
    "brd": "#2a2a2a", "brd2": "#3a3a3a",
    "txt": "#f0f0f0", "dim": "#555555", "dim2": "#888888",
    "red": "#ff4444", "grn": "#44ff88", "blu": "#4488ff",
    "pur": "#aa66ff", "org": "#ffaa33", "idle": "#444444",
    "hov": "#1e1e1e",
}
LANGS = {"Español (es)":"es","Inglés (en)":"en","Portugués (pt)":"pt",
         "Francés (fr)":"fr","Alemán (de)":"de","Italiano (it)":"it"}


START_SOUND_DELAY_MS = 350
_SINGLE_INSTANCE_MUTEX = None


def _acquire_single_instance():
    """Prevent duplicate ScribeFloat windows, hotkeys, and tray icons."""
    global _SINGLE_INSTANCE_MUTEX
    if os.name != "nt":
        return True

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool

    handle = kernel32.CreateMutexW(None, True, "Local\\ScribeFloatSingleInstance")
    if not handle:
        return True

    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False

    _SINGLE_INSTANCE_MUTEX = handle
    return True


def _release_single_instance():
    global _SINGLE_INSTANCE_MUTEX
    if os.name != "nt" or not _SINGLE_INSTANCE_MUTEX:
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
    kernel32.ReleaseMutex.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool

    kernel32.ReleaseMutex(_SINGLE_INSTANCE_MUTEX)
    kernel32.CloseHandle(_SINGLE_INSTANCE_MUTEX)
    _SINGLE_INSTANCE_MUTEX = None


class ScribeFloatApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.title("")
        self.geometry("380x340+80+80")
        self.overrideredirect(True)
        self.attributes("-alpha", 0.95)
        self.wm_attributes("-topmost", True)
        self.configure(fg_color="#000001")
        self.wm_attributes("-transparentcolor", "#000001")
        # Prevent ScribeFloat from stealing focus from other apps
        self.focusmodel("passive")

        # State
        self.is_recording = False
        self.current_language = self.cfg.get("language", "es")
        self.full_transcript = ""
        self._transcript_before_session = ""
        self._session_transcript = ""
        self._session_parts = {}
        self._completed_segments = set()
        self._last_pasted_session_text = ""
        self._segment_seq = 0
        self._pending_segments = 0
        self._paste_after_stop = False
        self._session_pasted = False
        self._segment_lock = threading.Lock()
        self._active_session_id = 0
        self._segment_queue = queue.Queue()
        self._segment_worker_thread = threading.Thread(target=self._segment_worker, daemon=True)
        self._segment_worker_thread.start()
        self._last_hotkey_time = 0.0
        self._hotkey_enabled_after = time.monotonic() + 1.0
        self.audio_capture = None
        self.scribe_engine = None

        self._anim_id = None
        self._bar_phase = 0
        self._ox = 0
        self._oy = 0
        self._mini = False
        self._audio_level = 0.0

        self._build_full_ui()
        self._init_sounds()
        self._init_backends()
        self._register_hotkey()

    def _asset_path(self, filename):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "assets", filename)

    def _init_sounds(self):
        self._sounds_enabled = False
        self._sound_paths = {
            "start": self._asset_path("start.mp3"),
            "stop": self._asset_path("stop.mp3"),
        }
        try:
            pygame.mixer.init()
            self._sounds_enabled = True
        except Exception as e:
            print(f"[Audio] Error inicializando sonidos: {e}")

    def _play_sound(self, name):
        if not self._sounds_enabled:
            return
        path = self._sound_paths.get(name)
        if not path or not os.path.exists(path):
            print(f"[Audio] No existe sonido: {path}")
            return
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
        except Exception as e:
            print(f"[Audio] Error reproduciendo {name}: {e}")

    # ── BUILD FULL UI ──────────────────────────────
    def _build_full_ui(self):
        self.main_panel = ctk.CTkFrame(self, corner_radius=16, fg_color=C["bg1"],
                                        border_width=1, border_color=C["brd"])
        self.main_panel.pack(fill="both", expand=True, padx=4, pady=4)

        # Header
        hdr = ctk.CTkFrame(self.main_panel, fg_color="transparent", height=32)
        hdr.pack(fill="x", padx=10, pady=(8, 0)); hdr.pack_propagate(False)
        tl = ctk.CTkLabel(hdr, text="⚡ ScribeFloat", font=("Segoe UI", 13, "bold"), text_color=C["dim2"])
        tl.pack(side="left")
        for w in [hdr, tl]:
            w.bind("<ButtonPress-1>", self._sm); w.bind("<ButtonRelease-1>", self._em); w.bind("<B1-Motion>", self._dm)
        ctk.CTkButton(hdr, text="✕", width=26, height=26, corner_radius=13, fg_color="transparent",
                       hover_color="#331111", text_color=C["dim"], font=("Segoe UI", 14),
                       command=self._on_close).pack(side="right")
        # Mini button (collapse to icon)
        ctk.CTkButton(hdr, text="●", width=26, height=26, corner_radius=13, fg_color="transparent",
                       hover_color=C["hov"], text_color=C["dim"], font=("Segoe UI", 10),
                       command=self._toggle_mini).pack(side="right", padx=2)
        # Settings
        ctk.CTkButton(hdr, text="⚙", width=26, height=26, corner_radius=13, fg_color="transparent",
                       hover_color=C["hov"], text_color=C["dim"], font=("Segoe UI", 14),
                       command=self._open_settings).pack(side="right", padx=2)

        # Status bar
        sf = ctk.CTkFrame(self.main_panel, fg_color="transparent", height=36)
        sf.pack(fill="x", padx=12, pady=(6, 0)); sf.pack_propagate(False)
        self.wave_canvas = ctk.CTkCanvas(sf, width=50, height=28, bg=C["bg1"], highlightthickness=0)
        self.wave_canvas.pack(side="left")
        self.bars = []
        for i, h in enumerate([8, 14, 18, 14, 8]):
            x = 6 + i * 9
            self.bars.append(self.wave_canvas.create_rectangle(x, 14-h//2, x+5, 14+h//2, fill=C["idle"], outline=""))
        self.status_label = ctk.CTkLabel(sf, text="  Listo", font=("Segoe UI", 11), text_color=C["dim"])
        self.status_label.pack(side="left")


        # Lang selector
        lf = ctk.CTkFrame(self.main_panel, fg_color="transparent", height=30)
        lf.pack(fill="x", padx=12, pady=(4, 0)); lf.pack_propagate(False)
        ctk.CTkLabel(lf, text="Idioma:", font=("Segoe UI", 10), text_color=C["dim"]).pack(side="left")
        self.lang_sel = ctk.CTkComboBox(lf, values=list(LANGS.keys()), command=self._chg_lang,
            width=140, height=26, font=("Segoe UI", 10), dropdown_font=("Segoe UI", 10),
            border_color=C["brd"], button_color=C["brd2"], fg_color=C["bg2"],
            dropdown_fg_color=C["bg2"], corner_radius=8)
        # Set initial lang display
        for display, code in LANGS.items():
            if code == self.current_language:
                self.lang_sel.set(display)
                break
        self.lang_sel.pack(side="left", padx=(6, 0))

        # Text area
        self.text_display = ctk.CTkTextbox(self.main_panel, height=130, corner_radius=10,
            fg_color=C["bg2"], border_width=1, border_color=C["brd"],
            font=("Consolas", 12), text_color=C["txt"], wrap="word")
        self.text_display.pack(fill="x", padx=12, pady=(6, 0))
        self.text_display.insert("0.0", "Hable ahora...")
        self.text_display.configure(state="disabled")

        # Action bar
        af = ctk.CTkFrame(self.main_panel, fg_color="transparent", height=42)
        af.pack(fill="x", padx=12, pady=(6, 10)); af.pack_propagate(False)
        self.rec_btn = ctk.CTkButton(af, text="● REC", width=70, height=30, corner_radius=15,
            fg_color="#331111", hover_color="#442222", text_color=C["red"],
            font=("Segoe UI", 11, "bold"), command=self._toggle_rec)
        self.rec_btn.pack(side="left")

        for icon, clr, cmd in [("💾",C["grn"],self._save),("🗑",C["dim"],self._clear),("📋",C["blu"],self._copy)]:
            ctk.CTkButton(af, text=icon, width=36, height=30, corner_radius=15,
                fg_color=C["bg2"], hover_color=C["hov"], text_color=clr,
                font=("Segoe UI", 14), command=cmd).pack(side="left" if icon!="📋" else "right", padx=2)

        # Hotkey hint
        hk = self.cfg.get("hotkey", "ctrl+space")
        self.hk_label = ctk.CTkLabel(self.main_panel, text=f"Atajo: {hk}", font=("Segoe UI", 9),
                                      text_color=C["dim"])
        self.hk_label.pack(side="bottom", pady=(0, 4))

    # ── MINI MODE (circular icon with waves) ──────
    def _toggle_mini(self):
        if self._mini:
            self._restore_full()
        else:
            self._go_mini()

    def _go_mini(self):
        self._mini = True
        self.main_panel.pack_forget()
        self.geometry("70x70")
        self._show_tray()
        # Transparent corners hack for Windows
        self.configure(fg_color="#000001")
        self.wm_attributes("-transparentcolor", "#000001")
        self.attributes("-alpha", 0.85) # Efecto cristal oscuro

        # Anti-aliased circle with solid background that catches clicks
        self.mini_frame = ctk.CTkFrame(self, width=60, height=60, corner_radius=30, 
                                       fg_color=C["bg1"], border_width=2, border_color="#ffffff")
        self.mini_frame.place(relx=0.5, rely=0.5, anchor="center")
        self.mini_frame.pack_propagate(False)

        # Inner canvas for the bars
        self.mini_canvas = ctk.CTkCanvas(self.mini_frame, width=40, height=40, bg=C["bg1"], highlightthickness=0)
        self.mini_canvas.place(relx=0.5, rely=0.5, anchor="center")
        
        self.mini_bars = []
        for i in range(3):
            x = 8 + i * 12
            # Rounded lines instead of sharp rectangles
            b = self.mini_canvas.create_line(x, 16, x, 24, fill="#ffffff", width=5, capstyle="round")
            self.mini_bars.append(b)

        # Bind interactions
        for w in [self.mini_frame, self.mini_canvas]:
            w.bind("<ButtonPress-1>", self._sm)
            w.bind("<ButtonRelease-1>", self._em)
            w.bind("<B1-Motion>", self._dm)
            w.bind("<Double-Button-1>", lambda e: self._restore_full())

        if self.is_recording:
            self._animate_mini()

    def _restore_full(self):
        self._mini = False
        self._hide_tray()
        if hasattr(self, "mini_frame"):
            self.mini_frame.destroy()
        self.geometry("380x340")
        self.configure(fg_color="#000001")
        self.wm_attributes("-transparentcolor", "#000001")
        self.attributes("-alpha", 0.95)
        self.main_panel.pack(fill="both", expand=True, padx=4, pady=4)

    def _show_tray(self):
        if hasattr(self, "_tray_icon") and self._tray_icon is not None:
            return

        img = Image.new('RGB', (64, 64), color=(18, 18, 18))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, 60, 60), outline=(255, 255, 255), width=4)
        d.line((22, 20, 22, 44), fill=(255, 255, 255), width=6)
        d.line((32, 14, 32, 50), fill=(255, 255, 255), width=6)
        d.line((42, 20, 42, 44), fill=(255, 255, 255), width=6)

        menu = pystray.Menu(
            pystray.MenuItem("Restaurar ScribeFloat", lambda icon, item: self.after(0, self._restore_full), default=True),
            pystray.MenuItem("Configuración", lambda icon, item: self.after(0, self._open_settings_from_tray)),
            pystray.MenuItem("Cerrar ScribeFloat", lambda icon, item: self.after(0, self._on_close))
        )

        self._tray_icon = pystray.Icon("ScribeFloat", img, "ScribeFloat", menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _hide_tray(self):
        if hasattr(self, "_tray_icon") and self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None

    def _open_settings_from_tray(self):
        self._restore_full()
        self._open_settings()

    def _animate_mini(self):
        if not self._mini:
            return
            
        if not self.is_recording:
            # Revert to idle state (White bars)
            for i, bar in enumerate(self.mini_bars):
                x = 8 + i * 12
                self.mini_canvas.coords(bar, x, 16, x, 24)
                self.mini_canvas.itemconfig(bar, fill="#ffffff")
            self.mini_frame.configure(width=60, height=60, corner_radius=30, border_color="#ffffff")
            return

        self._bar_phase += 0.2
        
        if not hasattr(self, "_smoothed_level"):
            self._smoothed_level = 0.0
            
        # Filtro de suavizado para que el movimiento sea elegante y no salte
        self._smoothed_level += (self._audio_level - self._smoothed_level) * 0.3
        
        # Reduced multiplier and lower cap so waves stay elegant and don't hit the top
        target_height = 8 + int(self._smoothed_level * 25)
        target_height = min(18, target_height)
        
        # Color yellow if speaking loudly enough
        color = "#ffcc00" if self._smoothed_level > 0.01 else "#ffffff"

        for i, bar in enumerate(self.mini_bars):
            variation = math.sin(self._bar_phase + i) * 0.5
            h = max(6, target_height + variation)
            x = 8 + i * 12
            self.mini_canvas.coords(bar, x, 20-h/2, x, 20+h/2)
            self.mini_canvas.itemconfig(bar, fill=color)
            
        # Subtle pulsing effect for the main circle
        # Aseguramos que el tamaño sea un número par para que no haya temblor de 1 píxel al centrar
        extra_size = (int(self._smoothed_level * 6) // 2) * 2
        circle_size = min(64, 60 + extra_size)
        
        self.mini_frame.configure(
            width=circle_size,
            height=circle_size,
            corner_radius=circle_size // 2,
            border_color=color
        )
            
        self.after(50, self._animate_mini)

    # ── HOTKEY ────────────────────────────────────
    def _register_hotkey(self):
        hk = self.cfg.get("hotkey", "ctrl+space")
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        try:
            keyboard.add_hotkey(hk, self._hotkey_triggered, suppress=True, trigger_on_release=True)
            self._hotkey_enabled_after = time.monotonic() + 1.0
            print(f"[Hotkey] Registrado: {hk}")
        except Exception as e:
            print(f"[Hotkey] Error: {e}")

    def _hotkey_triggered(self):
        now = time.monotonic()
        if now < self._hotkey_enabled_after:
            return
        if now - self._last_hotkey_time < 0.45:
            return
        self._last_hotkey_time = now
        self.after(80, self._toggle_rec)

    # ── BACKENDS ──────────────────────────────────
    def _init_backends(self):
        def _w():
            try:
                from transcriber import ScribeEngine
                model_size = self.cfg.get("model_size", "small")
                self.scribe_engine = ScribeEngine(language=self.current_language, model_size=model_size)
                self.after(0, lambda: self._set_status("Cargando modelo..."))
                self.scribe_engine.warm_up()
                self.after(0, lambda: self._set_status("Modelo listo"))
            except Exception as e:
                print(f"[Init] ScribeEngine error: {e}")
                self.after(0, lambda err=str(e): self._set_status(f"Error: {err}"))
        threading.Thread(target=_w, daemon=True).start()

    # ── RECORDING ─────────────────────────────────
    def _toggle_rec(self):
        if self.is_recording:
            self._stop_rec()
        else:
            with self._segment_lock:
                has_pending_work = self._pending_segments > 0
            if has_pending_work:
                self._set_status("Terminando transcripcion...")
                return
            self._start_rec()

    def _start_rec(self):
        try:
            self._reset_transcription_state(clear_display=True, clear_model_context=True)
            self._begin_recording_session()
            self.is_recording = True
            self.rec_btn.configure(text="■ STOP", fg_color="#441111", text_color="#ff6666")
            self._set_status("🔴 Grabando...")
            self._animate_bars_start()
            self._play_sound("start")
            self.after(START_SOUND_DELAY_MS, self._start_audio_capture)
        except Exception as e:
            self._set_status(f"Error mic: {e}")
            self.is_recording = False

    def _start_audio_capture(self):
        if not self.is_recording:
            return
        try:
            from audio_stream import AudioCapture
            self.audio_capture = AudioCapture(
                on_segment_ready=self._on_segment,
                on_level_update=self._on_level,
                finalize_on_silence=True
            )
            self.audio_capture.start()
            self._set_status("🔴 Grabando...")

            # Animate mini if in mini mode
            if self._mini:
                self._animate_mini()
        except Exception as e:
            self._set_status(f"Error mic: {e}")
            self.is_recording = False

    def _stop_rec(self):
        self.is_recording = False
        self._paste_after_stop = True
        self.rec_btn.configure(text="● REC", fg_color="#331111", text_color=C["red"])
        self._set_status("Finalizando...")
        self._animate_bars_stop()
        if self.audio_capture:
            self.audio_capture.stop()
            self.audio_capture = None
        self._play_sound("stop")
        # Call animate_mini one last time to reset it to idle state
        if self._mini:
            self._animate_mini()
        self._maybe_paste_session()

    def _on_segment(self, audio_path):
        if not self.scribe_engine:
            try:
                os.remove(audio_path)
            except Exception:
                pass
            self.after(0, lambda: self._set_status("Modelo cargando..."))
            return

        with self._segment_lock:
            session_id = self._active_session_id
            self._segment_seq += 1
            segment_id = self._segment_seq
            self._pending_segments += 1

        self._segment_queue.put((session_id, segment_id, audio_path))

    def _segment_worker(self):
        while True:
            item = self._segment_queue.get()
            if item is None:
                self._segment_queue.task_done()
                return

            session_id, segment_id, audio_path = item
            try:
                self.after(0, lambda: self._set_status("Transcribiendo..."))
                text = self.scribe_engine.transcribe(audio_path)

                try:
                    os.remove(audio_path)
                except Exception:
                    pass

                if text.startswith("[Error:"):
                    self.after(0, lambda msg=text, sid=segment_id, sess=session_id: self._finish_segment(sess, sid, "", msg))
                    continue

                cleaned = clean_text(text) if text and text.strip() else ""
                self.after(0, lambda sid=segment_id, value=cleaned, sess=session_id: self._finish_segment(sess, sid, value))
            finally:
                self._segment_queue.task_done()

    def _begin_recording_session(self):
        with self._segment_lock:
            self._active_session_id += 1
            self._transcript_before_session = ""
            self._session_transcript = ""
            self._session_parts = {}
            self._completed_segments = set()
            self._last_pasted_session_text = ""
            self._segment_seq = 0
            self._pending_segments = 0
            self._paste_after_stop = False
            self._session_pasted = False

    def _finish_segment(self, session_id, segment_id, text, error=None):
        with self._segment_lock:
            if session_id != self._active_session_id:
                return
            self._completed_segments.add(segment_id)
            if text:
                self._session_parts[segment_id] = text
                ordered_parts = []
                for segment_key in range(1, self._segment_seq + 1):
                    if segment_key not in self._completed_segments:
                        break
                    part = self._session_parts.get(segment_key, "")
                    if part:
                        ordered_parts.append(part)
                self._session_transcript = " ".join(ordered_parts).strip()
                if self._transcript_before_session and self._session_transcript:
                    self.full_transcript = f"{self._transcript_before_session} {self._session_transcript}"
                else:
                    self.full_transcript = self._session_transcript or self._transcript_before_session

            self._pending_segments = max(0, self._pending_segments - 1)

        if error:
            print(f"[Transcription] {error}")
            self._set_status("Error de transcripcion")
        elif text:
            self._replace_text_display(self.full_transcript)

        self._maybe_paste_session()

    def _maybe_paste_session(self):
        with self._segment_lock:
            should_paste = self._paste_after_stop and not self.is_recording
            text_to_paste = self._get_unpasted_session_delta_locked() if should_paste else ""
            if text_to_paste:
                self._session_pasted = True
                self._last_pasted_session_text = self._session_transcript.strip()

        if text_to_paste:
            self._set_status("Pegando texto...")
            self.after(100, lambda text=text_to_paste: self._type_to_active_window(text))
            if self._pending_segments == 0:
                self.after(250, lambda: self._set_status("Listo"))
            else:
                self.after(250, lambda: self._set_status("Completando texto..."))
        elif self._paste_after_stop and self._pending_segments == 0 and not self.is_recording:
            self._set_status("Listo")

    def _get_unpasted_session_delta_locked(self):
        current_text = self._session_transcript.strip()
        pasted_text = self._last_pasted_session_text.strip()
        if not current_text or current_text == pasted_text:
            return ""
        if not pasted_text:
            return current_text
        if current_text.startswith(pasted_text):
            return current_text[len(pasted_text):].strip()
        return ""

    def _on_level(self, level, has_speech):
        """Callback from audio stream with current level."""
        self._audio_level = level

    def _type_to_active_window(self, text):
        """
        Pega el texto en la app activa usando el portapapeles.
        Es mas rapido y confiable que escribir caracter por caracter.
        """
        try:
            previous_clipboard = None
            try:
                previous_clipboard = self.clipboard_get()
            except Exception:
                pass

            self.clipboard_clear()
            self.clipboard_append(text + " ")
            self.update_idletasks()
            time.sleep(0.05)
            self._release_keyboard_keys()
            keyboard.press_and_release("ctrl+v")
            self._release_keyboard_keys()

            self.after(250, lambda old=previous_clipboard: self._restore_clipboard(old))
        except Exception as e:
            print(f"[TypeOut] Error: {e}")

    def _release_keyboard_keys(self):
        for key in ("ctrl", "left ctrl", "right ctrl", "shift", "alt", "space", "v"):
            try:
                keyboard.release(key)
            except Exception:
                pass

    def _restore_clipboard(self, previous_text):
        try:
            self.clipboard_clear()
            if previous_text:
                self.clipboard_append(previous_text)
            self.update_idletasks()
        except Exception as e:
            print(f"[Clipboard] Error restaurando portapapeles: {e}")

    def _show_text(self, text):
        self.text_display.configure(state="normal")
        cur = self.text_display.get("0.0", "end").strip()
        if cur == "Hable ahora...":
            self.text_display.delete("0.0", "end")
        prefix = " " if self.text_display.get("0.0", "end").strip() else ""
        self.text_display.insert("end", prefix + text)
        self.text_display.see("end")
        self.text_display.configure(state="disabled")

    def _replace_text_display(self, text):
        self.text_display.configure(state="normal")
        self.text_display.delete("0.0", "end")
        self.text_display.insert("0.0", text if text else "Hable ahora...")
        self.text_display.see("end")
        self.text_display.configure(state="disabled")


    def _reset_transcription_state(self, clear_display=False, clear_model_context=False):
        self.full_transcript = ""
        self._transcript_before_session = ""
        self._session_transcript = ""
        self._session_parts = {}
        self._completed_segments = set()
        self._last_pasted_session_text = ""
        self._segment_seq = 0
        self._pending_segments = 0
        self._paste_after_stop = False
        self._session_pasted = False

        if clear_model_context and self.scribe_engine:
            self.scribe_engine.clear_context()

        if clear_display:
            self._replace_text_display("")


    # ── ACTIONS ───────────────────────────────────
    def _save(self):
        txt = self.text_display.get("0.0", "end").strip()
        if not txt or txt == "Hable ahora...": return
        d = os.path.join(os.path.expanduser("~"), "Documents", "ScribeFloat", "exports")
        save_transcription(txt, export_dir=d)
        self._set_status("💾 Guardado")

    def _clear(self):
        self._reset_transcription_state(clear_display=True, clear_model_context=True)

    def _copy(self):
        txt = self.text_display.get("0.0", "end").strip()
        if txt and txt != "Hable ahora...":
            self.clipboard_clear(); self.clipboard_append(txt)
            self._set_status("📋 Copiado")

    def _chg_lang(self, choice):
        self.current_language = LANGS.get(choice, "es")
        self.cfg["language"] = self.current_language
        save_config(self.cfg)
        if self.scribe_engine:
            self.scribe_engine.set_language(self.current_language)
        self._set_status(f"Idioma: {choice}")

    def _open_settings(self):
        SettingsPanel(self, self.cfg, on_save=self._apply_settings)

    def _apply_settings(self, new_cfg):
        self.cfg = new_cfg
        save_config(self.cfg)
        self._register_hotkey()
        hk = self.cfg.get("hotkey", "ctrl+space")
        self.hk_label.configure(text=f"Atajo: {hk}")


    # ── VISUAL ────────────────────────────────────
    def _set_status(self, t):
        self.status_label.configure(text=f"  {t}")

    def _animate_bars_start(self):
        self._bar_phase = 0
        self._do_animate_bars()

    def _do_animate_bars(self):
        if not self.is_recording: return
        self._bar_phase += 0.4
        for i, bar in enumerate(self.bars):
            h = int(6 + 10 * abs(math.sin(self._bar_phase + i * 0.8)))
            x = 6 + i * 9
            self.wave_canvas.coords(bar, x, 14-h//2, x+5, 14+h//2)
            self.wave_canvas.itemconfig(bar, fill=C["red"])
        self._anim_id = self.after(120, self._do_animate_bars)

    def _animate_bars_stop(self):
        if self._anim_id:
            self.after_cancel(self._anim_id); self._anim_id = None
        for i, bar in enumerate(self.bars):
            h = [8, 14, 18, 14, 8][i]; x = 6 + i * 9
            self.wave_canvas.coords(bar, x, 14-h//2, x+5, 14+h//2)
            self.wave_canvas.itemconfig(bar, fill=C["idle"])

    # ── DRAG ──────────────────────────────────────
    def _sm(self, e): self._ox, self._oy = e.x, e.y
    def _em(self, e): self._ox = self._oy = None
    def _dm(self, e):
        if self._ox is not None:
            self.geometry(f"+{self.winfo_x()+(e.x-self._ox)}+{self.winfo_y()+(e.y-self._oy)}")

    def _on_close(self):
        try: keyboard.unhook_all_hotkeys()
        except: pass
        if self.audio_capture: self.audio_capture.stop()
        try:
            self._segment_queue.put(None)
        except Exception:
            pass
        self._hide_tray()
        _release_single_instance()
        self.destroy()


if __name__ == "__main__":
    if _acquire_single_instance():
        app = ScribeFloatApp()
        app.mainloop()
