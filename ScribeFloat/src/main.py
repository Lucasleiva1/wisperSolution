"""
ScribeFloat - UI Principal
Ventana flotante + Mini mode (icono con ondas) + System Tray + Hotkey global.
"""
import ctypes, threading, math, sys, os, time, keyboard, queue


def _enable_windows_dpi_awareness():
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_enable_windows_dpi_awareness()

import customtkinter as ctk
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
import pystray
from PIL import Image, ImageDraw, ImageTk

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


TRANSPARENT_COLOR = "#000001"
TRANSPARENT_RGB = (0, 0, 1)
CAPSULE_MATTE_RGB = (5, 9, 17)

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


def _blend_rgb(foreground, background, alpha):
    alpha = max(0.0, min(1.0, alpha))
    inv = 1.0 - alpha
    return tuple(int(round(foreground[i] * alpha + background[i] * inv)) for i in range(3))


def _matte_for_color_key(img, matte=CAPSULE_MATTE_RGB, threshold=4):
    img = img.convert("RGBA")
    out = []
    for r, g, b, a in img.getdata():
        if a <= threshold:
            out.append((*TRANSPARENT_RGB, 255))
            continue
        inv = 255 - a
        out.append((
            (r * a + matte[0] * inv) // 255,
            (g * a + matte[1] * inv) // 255,
            (b * a + matte[2] * inv) // 255,
            255,
        ))
    img.putdata(out)
    return img


class ScribeFloatApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.title("")
        self.geometry("380x340+80+80")
        self.overrideredirect(True)
        self.attributes("-alpha", 0.95)
        self.wm_attributes("-topmost", True)
        self.configure(fg_color=TRANSPARENT_COLOR)
        self.wm_attributes("-transparentcolor", TRANSPARENT_COLOR)
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
        self._capsule_config_preview = False
        self._capsule_preview_phase = 0.0
        self._mini_anim_after = None
        self._capsule_preview_rebuild_after = None
        self.settings_window = None

        self._build_full_ui()
        self._init_sounds()
        self._init_backends()
        self._register_hotkey()

    def _asset_path(self, filename):
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.append(os.path.dirname(sys.executable))
        candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for base_dir in candidates:
            path = os.path.join(base_dir, "assets", filename)
            if os.path.exists(path):
                return path
        return os.path.join(candidates[0], "assets", filename)

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

        self.settings_btn = ctk.CTkButton(
            af,
            text="⚙ Ajustes",
            width=88,
            height=30,
            corner_radius=15,
            fg_color=C["bg2"],
            hover_color=C["hov"],
            text_color=C["dim2"],
            font=("Segoe UI", 11, "bold"),
            command=self._open_settings,
        )
        self.settings_btn.pack(side="right", padx=(2, 0))

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
        self._show_tray()
        self.configure(fg_color=TRANSPARENT_COLOR)
        self.wm_attributes("-transparentcolor", TRANSPARENT_COLOR)
        self._destroy_mini_widgets()

        self._mini_mode_active = self.cfg.get("mini_mode", "capsule")
        if self._mini_mode_active == "circle":
            self._go_mini_circle()
        else:
            self._mini_mode_active = "capsule"
            self._go_mini_capsule()

    def _capsule_int(self, key, default, min_value, max_value):
        try:
            value = int(float(self.cfg.get(key, default)))
        except Exception:
            value = default
        return max(min_value, min(max_value, value))

    def _capsule_render_scale(self, base, max_scale=18):
        try:
            dpi_scale = self.winfo_fpixels("1i") / 96.0
        except Exception:
            dpi_scale = 1.0
        return max(base, min(max_scale, int(math.ceil(base * dpi_scale))))

    def _bind_mini_widget(self, widget):
        widget.bind("<ButtonPress-1>", self._sm)
        widget.bind("<ButtonRelease-1>", self._em)
        widget.bind("<B1-Motion>", self._dm)
        widget.bind("<Double-Button-1>", lambda e: self._restore_full())

    def _cancel_mini_animation(self):
        if self._mini_anim_after is not None:
            try:
                self.after_cancel(self._mini_anim_after)
            except Exception:
                pass
            self._mini_anim_after = None

    def _schedule_mini_animation(self, callback):
        self._mini_anim_after = self.after(50, callback)

    def _destroy_mini_widgets(self):
        self._cancel_mini_animation()
        for attr in ("mini_frame", "mini_canvas", "capsule_frame", "capsule_canvas"):
            widget = getattr(self, attr, None)
            if widget is not None:
                try:
                    widget.destroy()
                except Exception:
                    pass
                setattr(self, attr, None)
        self.mini_bars = []
        self.capsule_bars = []
        self.capsule_bg_image = None
        self.capsule_wave_image = None
        self.capsule_indicator_image = None
        self.capsule_wave_item = None
        self.capsule_indicator_item = None
        self._capsule_indicator_recording_state = None
        self.capsule_layout = {}
        self.capsule_restore_items = []

    def _go_mini_circle(self):
        self.geometry("70x70")
        self.attributes("-alpha", 0.85)
        self.mini_frame = ctk.CTkFrame(self, width=60, height=60, corner_radius=30, 
                                       fg_color=C["bg1"], border_width=2, border_color="#ffffff")
        self.mini_frame.place(relx=0.5, rely=0.5, anchor="center")
        self.mini_frame.pack_propagate(False)

        self.mini_canvas = ctk.CTkCanvas(self.mini_frame, width=40, height=40, bg=C["bg1"], highlightthickness=0)
        self.mini_canvas.place(relx=0.5, rely=0.5, anchor="center")
        
        self.mini_bars = []
        for i in range(3):
            x = 8 + i * 12
            b = self.mini_canvas.create_line(x, 16, x, 24, fill="#ffffff", width=5, capstyle="round")
            self.mini_bars.append(b)

        for w in [self.mini_frame, self.mini_canvas]:
            self._bind_mini_widget(w)

        if self.is_recording:
            self._animate_mini_circle()
        else:
            self._reset_mini_circle_idle()

    def _go_mini_capsule(self):
        body_w = self._capsule_int("capsule_width", 180, 90, 760)
        body_h = self._capsule_int("capsule_height", 30, 18, 160)
        pad_x = max(12, int(body_h * 0.38))
        pad_y = max(16, int(body_h * 0.52))
        win_w = body_w + pad_x * 2
        win_h = body_h + pad_y * 2
        self.geometry(f"{win_w}x{win_h}")
        self.attributes("-alpha", 1.0)

        self.capsule_canvas = ctk.CTkCanvas(
            self,
            width=win_w,
            height=win_h,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
        )
        self.capsule_canvas.place(relx=0.5, rely=0.5, anchor="center")
        self._bind_mini_widget(self.capsule_canvas)

        x0 = pad_x
        y0 = pad_y
        x1 = x0 + body_w
        y1 = y0 + body_h
        cy = win_h / 2
        indicator_scale = self._capsule_int("capsule_indicator_scale", 90, 10, 180) / 100.0
        indicator_cx = x1 - body_h * 0.72
        indicator_r = body_h * 0.33 * indicator_scale
        mic_end = x0 + body_h * 1.32
        indicator_start = indicator_cx - indicator_r * 1.7
        wave_spread = self._capsule_int("capsule_wave_spread", 110, 60, 170) / 100.0
        wave_center = (mic_end + indicator_start) / 2
        wave_half = max(18, (indicator_start - mic_end) * 0.5 * wave_spread)
        wave_left = max(mic_end, wave_center - wave_half)
        wave_right = min(indicator_start, wave_center + wave_half)
        if wave_right <= wave_left + 12:
            wave_left = x0 + body_h * 1.22
            wave_right = x1 - body_h * 1.35
        indicator_dot_r = max(3, body_h * 0.105 * indicator_scale)
        indicator_halo_r = indicator_dot_r * 2.45
        wave_margin = max(4, int(body_h * 0.14))
        wave_box_x = max(0, int(math.floor(wave_left - wave_margin)))
        wave_box_y = max(0, int(math.floor(cy - body_h * 0.43)))
        wave_box_right = min(win_w, int(math.ceil(wave_right + wave_margin)))
        wave_box_bottom = min(win_h, int(math.ceil(cy + body_h * 0.43)))
        indicator_box_x = max(0, int(math.floor(indicator_cx - indicator_halo_r - 2)))
        indicator_box_y = max(0, int(math.floor(cy - indicator_halo_r - 2)))
        indicator_box_right = min(win_w, int(math.ceil(indicator_cx + indicator_halo_r + 2)))
        indicator_box_bottom = min(win_h, int(math.ceil(cy + indicator_halo_r + 2)))

        self.capsule_layout = {
            "win_w": win_w,
            "win_h": win_h,
            "body_w": body_w,
            "body_h": body_h,
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "cy": cy,
            "wave_left": wave_left,
            "wave_right": wave_right,
            "wave_box_x": wave_box_x,
            "wave_box_y": wave_box_y,
            "wave_box_w": max(1, wave_box_right - wave_box_x),
            "wave_box_h": max(1, wave_box_bottom - wave_box_y),
            "indicator_cx": indicator_cx,
            "indicator_cy": cy,
            "indicator_dot_r": indicator_dot_r,
            "indicator_box_x": indicator_box_x,
            "indicator_box_y": indicator_box_y,
            "indicator_box_w": max(1, indicator_box_right - indicator_box_x),
            "indicator_box_h": max(1, indicator_box_bottom - indicator_box_y),
            "max_bar_h": body_h * 0.58,
        }

        self._render_capsule_background()
        self._create_capsule_wave_items()
        self._create_capsule_restore_hint()
        self.capsule_canvas.bind("<Enter>", lambda e: self._show_capsule_restore_hint())
        self.capsule_canvas.bind("<Leave>", lambda e: self._hide_capsule_restore_hint())
        self._reset_mini_capsule_idle()
        if self.is_recording or self._capsule_config_preview:
            self._animate_mini_capsule()

    def _render_capsule_background(self):
        layout = self.capsule_layout
        scale = self._capsule_render_scale(12, 18)
        win_w = layout["win_w"]
        win_h = layout["win_h"]
        x0 = layout["x0"]
        y0 = layout["y0"]
        x1 = layout["x1"]
        y1 = layout["y1"]
        body_h = layout["body_h"]
        cy = layout["cy"]
        glow_amount = self._capsule_int("capsule_border_glow", 115, 40, 200) / 100.0

        img = Image.new("RGBA", (win_w * scale, win_h * scale), (0, 0, 0, 0))
        rect = [int(x0 * scale), int(y0 * scale), int(x1 * scale), int(y1 * scale)]
        radius = int(body_h * scale / 2)
        d = ImageDraw.Draw(img)
        border_alpha = max(135, min(245, int(178 * glow_amount)))
        border_color = _blend_rgb((217, 233, 255), CAPSULE_MATTE_RGB, border_alpha / 255.0)
        inner_color = _blend_rgb((120, 145, 180), CAPSULE_MATTE_RGB, 0.24)
        d.rounded_rectangle(
            rect,
            radius=radius,
            fill=(*CAPSULE_MATTE_RGB, 255),
            outline=(*border_color, 255),
            width=max(1, int(0.9 * scale)),
        )
        inner = [
            int((x0 + body_h * 0.10) * scale),
            int((y0 + body_h * 0.10) * scale),
            int((x1 - body_h * 0.10) * scale),
            int((y1 - body_h * 0.10) * scale),
        ]
        d.rounded_rectangle(
            inner,
            radius=max(1, int(body_h * 0.40 * scale)),
            outline=(*inner_color, 255),
            width=max(1, int(0.45 * scale)),
        )

        self._draw_capsule_mic(d, scale)
        self._draw_capsule_rings(d, scale)
        resample = getattr(Image, "Resampling", Image).LANCZOS
        img = img.resize((win_w, win_h), resample)
        img = _matte_for_color_key(img, threshold=120)
        self.capsule_bg_image = ImageTk.PhotoImage(img)
        self.capsule_canvas.create_image(0, 0, image=self.capsule_bg_image, anchor="nw")

    def _draw_capsule_mic(self, draw, scale):
        layout = self.capsule_layout
        body_h = layout["body_h"]
        raw_mic_scale = self._capsule_int("capsule_mic_scale", 100, 10, 180)
        mic_scale = 0.55 + (raw_mic_scale / 160.0)
        cx = layout["x0"] + body_h * 0.64
        cy = layout["cy"]
        unit = (body_h * 0.68 * mic_scale) / 18.0
        stroke = max(0.9, 1.18 * unit)
        white = (230, 240, 255, 255)

        def sbox(values):
            return [int(round(v * scale)) for v in values]

        def sline(values, width=None):
            draw.line(
                sbox(values),
                fill=white,
                width=max(1, int(round((width or stroke) * scale))),
                joint="curve",
            )

        def point(x, y):
            return cx + (x * unit), cy + (y * unit)

        def bezier(p0, p1, p2, p3, steps=22):
            pts = []
            for idx in range(steps + 1):
                t = idx / steps
                inv = 1.0 - t
                x = (inv ** 3 * p0[0]) + (3 * inv * inv * t * p1[0]) + (3 * inv * t * t * p2[0]) + (t ** 3 * p3[0])
                y = (inv ** 3 * p0[1]) + (3 * inv * inv * t * p1[1]) + (3 * inv * t * t * p2[1]) + (t ** 3 * p3[1])
                pts.append((x, y))
            return pts

        cap_left, cap_top = point(-3.25, -7.5)
        cap_right, cap_bottom = point(3.25, 4.0)
        draw.rounded_rectangle(
            sbox([cap_left, cap_top, cap_right, cap_bottom]),
            radius=max(1, int(3.25 * unit * scale)),
            outline=white,
            width=max(1, int(round(stroke * scale))),
        )

        cradle = bezier(
            point(-6, -2),
            point(-6, 5.5),
            point(6, 5.5),
            point(6, -2),
        )
        draw.line(
            [(int(round(x * scale)), int(round(y * scale))) for x, y in cradle],
            fill=white,
            width=max(1, int(round(stroke * scale))),
            joint="curve",
        )
        sline([*point(0, 5), *point(0, 8)])
        sline([*point(-4.5, 8), *point(4.5, 8)])

    def _draw_capsule_rings(self, draw, scale):
        layout = self.capsule_layout
        cx = layout["indicator_cx"]
        cy = layout["indicator_cy"]
        r = layout["body_h"] * 0.33 * (self._capsule_int("capsule_indicator_scale", 90, 10, 180) / 100.0)
        white = (*_blend_rgb((226, 231, 241), CAPSULE_MATTE_RGB, 0.42), 255)
        soft = (*_blend_rgb((226, 231, 241), CAPSULE_MATTE_RGB, 0.23), 255)

        def oval(radius, color, width=1):
            draw.ellipse(
                [int((cx - radius) * scale), int((cy - radius) * scale),
                 int((cx + radius) * scale), int((cy + radius) * scale)],
                outline=color,
                width=max(1, int(width * scale)),
            )

        oval(r, soft, 0.75)
        oval(r * 0.74, white, 0.8)

    def _create_capsule_wave_items(self):
        layout = self.capsule_layout
        bar_count = self._capsule_int("capsule_wave_bars", 42, 20, 72)
        self.capsule_bars = list(range(bar_count))
        blank = Image.new("RGBA", (layout["wave_box_w"], layout["wave_box_h"]), (0, 0, 0, 0))
        self.capsule_wave_image = ImageTk.PhotoImage(blank)
        self.capsule_wave_item = self.capsule_canvas.create_image(
            layout["wave_box_x"], layout["wave_box_y"], image=self.capsule_wave_image, anchor="nw"
        )

        indicator_blank = Image.new("RGBA", (layout["indicator_box_w"], layout["indicator_box_h"]), (0, 0, 0, 0))
        self.capsule_indicator_image = ImageTk.PhotoImage(indicator_blank)
        self.capsule_indicator_item = self.capsule_canvas.create_image(
            layout["indicator_box_x"], layout["indicator_box_y"], image=self.capsule_indicator_image, anchor="nw"
        )
        self._capsule_indicator_recording_state = None

    def _render_capsule_wave(self, level, active):
        if not self.capsule_canvas or not getattr(self, "capsule_layout", None):
            return
        layout = self.capsule_layout
        scale = self._capsule_render_scale(4, 6)
        img = Image.new("RGBA", (layout["wave_box_w"] * scale, layout["wave_box_h"] * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        center = layout["cy"] - layout["wave_box_y"]
        left = layout["wave_left"] - layout["wave_box_x"]
        right = layout["wave_right"] - layout["wave_box_x"]
        span = max(1, right - left)
        count = max(1, len(self.capsule_bars) - 1)
        amplitude = self._capsule_int("capsule_wave_amplitude", 115, 20, 240) / 100.0
        base_alpha = 225 if active else 155
        body_h = layout["body_h"]

        for i, _ in enumerate(self.capsule_bars):
            distance = abs(i - count / 2)
            falloff = max(0.13, 1.0 - distance / max(10, len(self.capsule_bars) * 0.58))
            wave = (math.sin(self._bar_phase + i * 0.55) + 1.0) * 0.5
            h = body_h * 0.035 + (level * layout["max_bar_h"] * amplitude * falloff) + (wave * body_h * 0.10 * falloff)
            if i % 5 in (0, 4):
                h *= 0.55
            h = max(1.0, min(body_h * 0.72, h))
            w = max(1.15, min(2.8, body_h * 0.035 + h * 0.045))
            x = left + span * (i / count)
            alpha = int(base_alpha * (0.55 + 0.45 * falloff))
            color = (255, 255, 255, alpha) if active else (211, 217, 228, alpha)
            rect = [
                int((x - w / 2) * scale),
                int((center - h / 2) * scale),
                int((x + w / 2) * scale),
                int((center + h / 2) * scale),
            ]
            draw.rounded_rectangle(rect, radius=max(1, int(w * scale / 2)), fill=color)

        resample = getattr(Image, "Resampling", Image).LANCZOS
        img = img.resize((layout["wave_box_w"], layout["wave_box_h"]), resample)
        self.capsule_wave_image = ImageTk.PhotoImage(img)
        self.capsule_canvas.itemconfig(self.capsule_wave_item, image=self.capsule_wave_image)

    def _create_capsule_restore_hint(self):
        layout = self.capsule_layout
        body_h = layout["body_h"]
        cx = layout["win_w"] / 2
        cy = min(layout["win_h"] - 7, layout["y1"] + (layout["win_h"] - layout["y1"]) / 2)
        self.capsule_restore_items = [
            self.capsule_canvas.create_text(
                cx,
                cy,
                text="Abrir",
                fill="#c7d4e8",
                font=("Segoe UI", max(8, int(body_h * 0.22)), "bold"),
                state="hidden",
                tags=("capsule_restore",),
            ),
        ]
        self.capsule_canvas.tag_bind("capsule_restore", "<Button-1>", lambda e: self._restore_full())
        self.capsule_canvas.tag_bind("capsule_restore", "<Enter>", lambda e: self._show_capsule_restore_hint())

    def _show_capsule_restore_hint(self):
        if not getattr(self, "capsule_restore_items", None) or not self.capsule_canvas:
            return
        for item in self.capsule_restore_items:
            self.capsule_canvas.itemconfig(item, state="normal")
        self.capsule_canvas.tag_raise("capsule_restore")

    def _hide_capsule_restore_hint(self):
        if not getattr(self, "capsule_restore_items", None) or not self.capsule_canvas:
            return
        for item in self.capsule_restore_items:
            self.capsule_canvas.itemconfig(item, state="hidden")

    def _restore_full(self):
        self._mini = False
        self._hide_tray()
        self._destroy_mini_widgets()
        self.geometry("380x340")
        self.configure(fg_color=TRANSPARENT_COLOR)
        self.wm_attributes("-transparentcolor", TRANSPARENT_COLOR)
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
        if getattr(self, "_mini_mode_active", "capsule") == "circle":
            self._animate_mini_circle()
        else:
            self._animate_mini_capsule()

    def _reset_mini_circle_idle(self):
        if not getattr(self, "mini_bars", None) or not self.mini_canvas:
            return
        for i, bar in enumerate(self.mini_bars):
            x = 8 + i * 12
            self.mini_canvas.coords(bar, x, 16, x, 24)
            self.mini_canvas.itemconfig(bar, fill="#ffffff")
        self.mini_frame.configure(width=60, height=60, corner_radius=30, border_color="#ffffff")

    def _animate_mini_circle(self):
        self._mini_anim_after = None
        if not self._mini:
            return
            
        if not self.is_recording:
            self._reset_mini_circle_idle()
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
            
        self._schedule_mini_animation(self._animate_mini_circle)

    def _reset_mini_capsule_idle(self):
        if not getattr(self, "capsule_bars", None) or not self.capsule_canvas:
            return
        self._render_capsule_wave(0.0, False)
        self._set_capsule_indicator_recording(False)

    def _set_capsule_indicator_recording(self, recording, force=False):
        if not self.capsule_canvas or not getattr(self, "capsule_layout", None):
            return
        if not getattr(self, "capsule_indicator_item", None):
            return
        recording = bool(recording)
        if not force and getattr(self, "_capsule_indicator_recording_state", None) == recording:
            return
        layout = self.capsule_layout
        scale = self._capsule_render_scale(4, 6)
        img = Image.new("RGBA", (layout["indicator_box_w"] * scale, layout["indicator_box_h"] * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cx = (layout["indicator_cx"] - layout["indicator_box_x"]) * scale
        cy = (layout["indicator_cy"] - layout["indicator_box_y"]) * scale
        r = layout["indicator_dot_r"] * scale
        active = recording
        dot = (68, 255, 136, 242) if active else (255, 68, 68, 238)
        halo = (104, 255, 168, 90) if active else (255, 104, 104, 86)
        core_glow = (255, 255, 255, 78) if active else (255, 210, 210, 56)
        halo_radius = r * (2.35 if active else 1.95)
        draw.ellipse(
            [cx - halo_radius, cy - halo_radius, cx + halo_radius, cy + halo_radius],
            fill=halo,
        )
        draw.ellipse(
            [cx - r * 1.45, cy - r * 1.45, cx + r * 1.45, cy + r * 1.45],
            fill=core_glow,
        )
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=dot)
        shine_r = max(1.0, r * 0.34)
        draw.ellipse(
            [cx - r * 0.38 - shine_r, cy - r * 0.42 - shine_r, cx - r * 0.38 + shine_r, cy - r * 0.42 + shine_r],
            fill=(255, 255, 255, 120),
        )
        resample = getattr(Image, "Resampling", Image).LANCZOS
        img = img.resize((layout["indicator_box_w"], layout["indicator_box_h"]), resample)
        self.capsule_indicator_image = ImageTk.PhotoImage(img)
        self.capsule_canvas.itemconfig(self.capsule_indicator_item, image=self.capsule_indicator_image)
        self._capsule_indicator_recording_state = recording

    def _animate_mini_capsule(self):
        self._mini_anim_after = None
        if not self._mini:
            return
        if not self.capsule_canvas or not getattr(self, "capsule_layout", None):
            return

        previewing = self._capsule_config_preview and getattr(self, "_mini_mode_active", "capsule") == "capsule"
        if not self.is_recording and not previewing:
            self._reset_mini_capsule_idle()
            return

        self._bar_phase += 0.22
        if previewing and not self.is_recording:
            self._capsule_preview_phase += 0.11

        if not hasattr(self, "_smoothed_level"):
            self._smoothed_level = 0.0
        smoothing = self._capsule_int("capsule_wave_smoothing", 28, 10, 80) / 100.0
        if previewing and not self.is_recording:
            preview_level = 0.28 + 0.22 * abs(math.sin(self._capsule_preview_phase)) + 0.10 * abs(math.sin(self._capsule_preview_phase * 0.43))
            source_level = min(0.72, preview_level)
        else:
            source_level = self._audio_level
        self._smoothed_level += (source_level - self._smoothed_level) * smoothing

        layout = self.capsule_layout
        sensitivity = self._capsule_int("capsule_wave_sensitivity", 130, 40, 240) / 100.0
        level = min(1.0, self._smoothed_level * sensitivity)
        active = level > 0.018
        self._render_capsule_wave(level, active)

        self._set_capsule_indicator_recording(self.is_recording)

        self._schedule_mini_animation(self._animate_mini_capsule)

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
            if self._mini and getattr(self, "_mini_mode_active", "capsule") == "capsule":
                self._set_capsule_indicator_recording(True)
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
            if getattr(self, "_mini_mode_active", "capsule") == "capsule":
                self._reset_mini_capsule_idle()
            else:
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
        if self.settings_window is not None:
            try:
                if self.settings_window.winfo_exists():
                    window = self.settings_window
                    self._end_settings_preview()
                    window.destroy()
                    self.settings_window = None
                    return
            except Exception:
                self.settings_window = None

        self._capsule_config_preview = True
        self._capsule_preview_phase = 0.0
        if not self._mini:
            self._go_mini()
        if self._mini and getattr(self, "_mini_mode_active", "capsule") == "capsule" and not self.is_recording:
            self._animate_mini_capsule()
        self.settings_window = SettingsPanel(
            self,
            self.cfg,
            on_save=self._apply_settings,
            on_preview=self._preview_settings,
            on_close=self._end_settings_preview,
        )

    def _preview_settings(self, new_cfg):
        old_cfg = self.cfg
        self.cfg = new_cfg
        if not self._mini:
            return
        layout_keys = {
            "mini_mode",
            "capsule_width",
            "capsule_height",
            "capsule_border_glow",
            "capsule_mic_scale",
            "capsule_indicator_scale",
            "capsule_wave_bars",
            "capsule_wave_spread",
        }
        needs_rebuild = any(old_cfg.get(key) != new_cfg.get(key) for key in layout_keys)
        if needs_rebuild:
            self._schedule_capsule_preview_rebuild()
        elif getattr(self, "_mini_mode_active", "capsule") == "capsule" and self._mini_anim_after is None:
            self._animate_mini_capsule()

    def _schedule_capsule_preview_rebuild(self):
        if self._capsule_preview_rebuild_after is not None:
            try:
                self.after_cancel(self._capsule_preview_rebuild_after)
            except Exception:
                pass
        self._capsule_preview_rebuild_after = self.after(120, self._apply_capsule_preview_rebuild)

    def _apply_capsule_preview_rebuild(self):
        self._capsule_preview_rebuild_after = None
        if self._mini:
            self._go_mini()

    def _end_settings_preview(self):
        if self._capsule_preview_rebuild_after is not None:
            try:
                self.after_cancel(self._capsule_preview_rebuild_after)
            except Exception:
                pass
            self._capsule_preview_rebuild_after = None
        self._capsule_config_preview = False
        self.settings_window = None
        if self._mini and getattr(self, "_mini_mode_active", "capsule") == "capsule" and not self.is_recording:
            self._reset_mini_capsule_idle()

    def _apply_settings(self, new_cfg):
        if self._capsule_preview_rebuild_after is not None:
            try:
                self.after_cancel(self._capsule_preview_rebuild_after)
            except Exception:
                pass
            self._capsule_preview_rebuild_after = None
        self._capsule_config_preview = False
        self.settings_window = None
        self.cfg = new_cfg
        save_config(self.cfg)
        self._register_hotkey()
        hk = self.cfg.get("hotkey", "ctrl+space")
        self.hk_label.configure(text=f"Atajo: {hk}")
        if self._mini:
            self._go_mini()


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
