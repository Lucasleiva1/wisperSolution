"""
ScribeFloat - UI Principal
Ventana flotante + Mini mode (icono con ondas) + System Tray + Hotkey global.
"""
import customtkinter as ctk
import threading, math, sys, os, time, keyboard
import pygame

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import clean_text, save_transcription
from ollama_client import OllamaClient
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


class ScribeFloatApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.title("")
        self.geometry("380x340+80+80")
        self.overrideredirect(True)
        self.attributes("-alpha", 0.95)
        self.wm_attributes("-topmost", True)
        self.configure(fg_color=C["bg0"])
        # Prevent ScribeFloat from stealing focus from other apps
        self.focusmodel("passive")

        # State
        self.is_recording = False
        self.current_language = self.cfg.get("language", "es")
        self.full_transcript = ""
        self.audio_capture = None
        self.scribe_engine = None
        self.ollama_client = None
        self._anim_id = None
        self._bar_phase = 0
        self._ox = 0
        self._oy = 0
        self._mini = False
        self._audio_level = 0.0
        self._saved_clipboard = None  # To restore clipboard after paste

        # Inicializar el motor de audio para mp3
        try:
            pygame.mixer.init()
        except Exception as e:
            print(f"[Audio] Error inicializando pygame: {e}")

        self._build_full_ui()
        self._init_backends()
        self._register_hotkey()

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
        self.ollama_label = ctk.CTkLabel(sf, text="", font=("Segoe UI", 10), text_color=C["pur"])
        self.ollama_label.pack(side="right", padx=5)

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
        self.ai_btn = ctk.CTkButton(af, text="✨ AI", width=60, height=30, corner_radius=15,
            fg_color="#1a1133", hover_color="#2a1a44", text_color=C["pur"],
            font=("Segoe UI", 11, "bold"), command=self._improve_ai)
        self.ai_btn.pack(side="left", padx=4)
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
        self.geometry("64x64")
        
        # Transparent corners hack for Windows
        self.configure(fg_color="#000001")
        self.wm_attributes("-transparentcolor", "#000001")
        self.attributes("-alpha", 1.0) # Solid UI

        # Anti-aliased circle with transparent center
        self.mini_frame = ctk.CTkFrame(self, width=60, height=60, corner_radius=30, 
                                       fg_color="#000001", border_width=2, border_color="#ffffff")
        self.mini_frame.pack(padx=2, pady=2)
        self.mini_frame.pack_propagate(False)

        # Inner canvas for the bars (transparent)
        self.mini_canvas = ctk.CTkCanvas(self.mini_frame, width=40, height=40, bg="#000001", highlightthickness=0)
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
        if hasattr(self, "mini_frame"):
            self.mini_frame.destroy()
        self.geometry("380x340")
        self.wm_attributes("-transparentcolor", "") # Remove transparency hack
        self.configure(fg_color=C["bg0"])
        self.attributes("-alpha", 0.95)
        self.main_panel.pack(fill="both", expand=True, padx=4, pady=4)

    def _animate_mini(self):
        if not self._mini:
            return
            
        if not self.is_recording:
            # Revert to idle state (White bars)
            for i, bar in enumerate(self.mini_bars):
                x = 8 + i * 12
                self.mini_canvas.coords(bar, x, 16, x, 24)
                self.mini_canvas.itemconfig(bar, fill="#ffffff")
            return

        self._bar_phase += 0.2
        
        # Reduced multiplier and lower cap so waves stay elegant and don't hit the top
        target_height = 8 + int(self._audio_level * 50) 
        target_height = min(20, target_height)
        
        # Color yellow if speaking loudly enough
        color = "#ffcc00" if self._audio_level > 0.03 else "#ffffff"

        for i, bar in enumerate(self.mini_bars):
            variation = math.sin(self._bar_phase + i) * 1.5
            h = max(6, target_height + variation)
            x = 8 + i * 12
            self.mini_canvas.coords(bar, x, 20-h/2, x, 20+h/2)
            self.mini_canvas.itemconfig(bar, fill=color)
            
        self.after(50, self._animate_mini)

    # ── HOTKEY ────────────────────────────────────
    def _register_hotkey(self):
        hk = self.cfg.get("hotkey", "ctrl+space")
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        try:
            keyboard.add_hotkey(hk, self._hotkey_triggered, suppress=True)
            print(f"[Hotkey] Registrado: {hk}")
        except Exception as e:
            print(f"[Hotkey] Error: {e}")

    def _hotkey_triggered(self):
        self.after(0, self._toggle_rec)

    # ── BACKENDS ──────────────────────────────────
    def _init_backends(self):
        def _w():
            try:
                self.ollama_client = OllamaClient(model=self.cfg.get("ollama_model", "qwen3.5:2b"))
                if self.ollama_client.is_available:
                    self.after(0, lambda: self.ollama_label.configure(text="🟢 qwen3.5:2b"))
                else:
                    self.after(0, lambda: self.ollama_label.configure(text="🔴 Ollama", text_color=C["dim"]))
            except Exception:
                self.after(0, lambda: self.ollama_label.configure(text="🔴 Ollama", text_color=C["dim"]))
            try:
                from transcriber import ScribeEngine
                self.scribe_engine = ScribeEngine(language=self.current_language)
                self.after(0, lambda: self._set_status("Modelo listo"))
            except Exception as e:
                print(f"[Init] ScribeEngine error: {e}")
                self.after(0, lambda: self._set_status(f"Error: {e}"))
        threading.Thread(target=_w, daemon=True).start()

    # ── RECORDING ─────────────────────────────────
    def _toggle_rec(self):
        if self.is_recording:
            self._stop_rec()
        else:
            self._start_rec()

    def _start_rec(self):
        try:
            # Reproducir Audio 1 del escritorio
            try:
                pygame.mixer.music.load(r"C:\Users\jaell\Desktop\1.mp3")
                pygame.mixer.music.play()
            except Exception as e:
                print(f"[Audio] Error con 1.mp3: {e}")

            from audio_stream import AudioCapture
            self.is_recording = True
            self.rec_btn.configure(text="■ STOP", fg_color="#441111", text_color="#ff6666")
            self._set_status("🔴 Grabando...")
            self._animate_bars_start()

            self.audio_capture = AudioCapture(
                on_segment_ready=self._on_segment,
                on_level_update=self._on_level
            )
            self.audio_capture.start()

            # Animate mini if in mini mode
            if self._mini:
                self._animate_mini()
        except Exception as e:
            self._set_status(f"Error mic: {e}")
            self.is_recording = False

    def _stop_rec(self):
        # Reproducir Audio 2 del escritorio
        try:
            pygame.mixer.music.load(r"C:\Users\jaell\Desktop\2.mp3")
            pygame.mixer.music.play()
        except Exception as e:
            print(f"[Audio] Error con 2.mp3: {e}")
        
        self.is_recording = False
        self.rec_btn.configure(text="● REC", fg_color="#331111", text_color=C["red"])
        self._set_status("Detenido")
        self._animate_bars_stop()
        if self.audio_capture:
            self.audio_capture.stop()
            self.audio_capture = None
        # Call animate_mini one last time to reset it to idle state
        if self._mini:
            self._animate_mini()

    def _on_segment(self, audio_path):
        if not self.scribe_engine:
            return
        def _t():
            self.after(0, lambda: self._set_status("Transcribiendo..."))
            text = self.scribe_engine.transcribe(audio_path)
            if text and text.strip():
                cleaned = clean_text(text)
                self.full_transcript += (" " + cleaned) if self.full_transcript else cleaned
                self.after(0, lambda: self._show_text(cleaned))
                # Type into the active window (Notepad, Word, etc.)
                self.after(100, lambda: self._type_to_active_window(cleaned))
                # Auto AI if enabled (improves in display only, doesn't re-paste)
                if self.cfg.get("auto_ai", True) and self.ollama_client and self.ollama_client.is_available:
                    self.after(600, self._auto_improve)
                else:
                    self.after(0, lambda: self._set_status("🔴 Grabando..." if self.is_recording else "Listo"))
        threading.Thread(target=_t, daemon=True).start()

    def _on_level(self, level, has_speech):
        """Callback from audio stream with current level."""
        self._audio_level = level

    def _type_to_active_window(self, text):
        """
        Pastes text into whatever app currently has focus.
        Uses keyboard.write() which types directly without stealing focus.
        """
        try:
            # Small delay to ensure ScribeFloat doesn't have focus
            time.sleep(0.05)
            # keyboard.write types character by character into the focused app
            keyboard.write(text + " ", delay=0.01)
        except Exception as e:
            print(f"[TypeOut] Error: {e}")

    def _show_text(self, text):
        self.text_display.configure(state="normal")
        cur = self.text_display.get("0.0", "end").strip()
        if cur == "Hable ahora...":
            self.text_display.delete("0.0", "end")
        prefix = " " if self.text_display.get("0.0", "end").strip() else ""
        self.text_display.insert("end", prefix + text)
        self.text_display.see("end")
        self.text_display.configure(state="disabled")

    # ── AI ────────────────────────────────────────
    def _improve_ai(self):
        if not self.ollama_client or not self.ollama_client.is_available:
            self._set_status("Ollama no disponible"); return
        txt = self.text_display.get("0.0", "end").strip()
        if not txt or txt == "Hable ahora...":
            self._set_status("Sin texto"); return
        self._set_status("✨ Procesando AI...")
        self.ai_btn.configure(state="disabled", text="⏳")
        self.ollama_client.improve_text_async(txt, lambda r: self.after(0, lambda: self._show_ai(r)),
                                               language=self.current_language)

    def _auto_improve(self):
        if not self.ollama_client or not self.ollama_client.is_available:
            return
        txt = self.text_display.get("0.0", "end").strip()
        if not txt or txt == "Hable ahora...":
            return
        self._set_status("✨ Auto-AI...")
        self.ollama_client.improve_text_async(txt, lambda r: self.after(0, lambda: self._show_ai(r)),
                                               language=self.current_language)

    def _show_ai(self, text):
        self.text_display.configure(state="normal")
        self.text_display.delete("0.0", "end")
        self.text_display.insert("0.0", text)
        self.text_display.configure(state="disabled")
        self.full_transcript = text
        self.ai_btn.configure(state="normal", text="✨ AI")
        self._set_status("🔴 Grabando..." if self.is_recording else "✨ Mejorado")

    # ── ACTIONS ───────────────────────────────────
    def _save(self):
        txt = self.text_display.get("0.0", "end").strip()
        if not txt or txt == "Hable ahora...": return
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exports")
        save_transcription(txt, export_dir=d)
        self._set_status("💾 Guardado")

    def _clear(self):
        self.text_display.configure(state="normal")
        self.text_display.delete("0.0", "end")
        self.text_display.insert("0.0", "Hable ahora...")
        self.text_display.configure(state="disabled")
        self.full_transcript = ""

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
        # Update ollama model if changed
        if self.ollama_client and self.cfg.get("ollama_model") != self.ollama_client.model:
            self.ollama_client = OllamaClient(model=self.cfg["ollama_model"])

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
        self.destroy()


if __name__ == "__main__":
    app = ScribeFloatApp()
    app.mainloop()
