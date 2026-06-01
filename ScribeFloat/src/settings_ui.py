"""ScribeFloat - Panel de Settings."""
import threading
import customtkinter as ctk
import keyboard

C = {
    "bg": "#101114", "panel": "#15171c", "row": "#1b1e25",
    "border": "#2c313a", "text": "#f0f3f8", "dim": "#8b93a1",
    "value": "#c9d2e3", "accent": "#7aa2ff", "purple": "#aa66ff",
}

MINI_MODE_LABELS = {
    "Capsula": "capsule",
    "Circulo": "circle",
}
MINI_MODE_VALUES = {value: label for label, value in MINI_MODE_LABELS.items()}

CAPSULE_GROUPS = [
    ("Capsula", [
        ("Ancho", "capsule_width", 90, 760, 10, "px"),
        ("Alto", "capsule_height", 18, 160, 2, "px"),
        ("Borde", "capsule_border_glow", 40, 200, 5, "%"),
    ]),
    ("Elementos", [
        ("Microfono", "capsule_mic_scale", 10, 180, 5, "%"),
        ("Punto", "capsule_indicator_scale", 10, 180, 5, "%"),
    ]),
    ("Ondas", [
        ("Cantidad", "capsule_wave_bars", 20, 72, 1, ""),
        ("Sensibilidad", "capsule_wave_sensitivity", 20, 260, 5, "%"),
        ("Suavizado", "capsule_wave_smoothing", 10, 80, 5, "%"),
        ("Reaccion", "capsule_wave_amplitude", 20, 240, 5, "%"),
        ("Ancho onda", "capsule_wave_spread", 50, 180, 5, "%"),
    ]),
]

CAPSULE_SLIDERS = [item for _, items in CAPSULE_GROUPS for item in items]


class SettingsPanel(ctk.CTkToplevel):
    def __init__(self, parent, config, on_save=None, on_preview=None, on_close=None):
        super().__init__(parent)
        self.title("Configuracion")
        self.geometry("410x660")
        self.resizable(False, False)
        self.wm_attributes("-topmost", True)
        self.configure(fg_color=C["bg"])
        self.config_data = dict(config)
        self.on_save = on_save
        self.on_preview = on_preview
        self.on_close = on_close
        self._capturing_hotkey = False
        self._slider_vars = {}
        self.protocol("WM_DELETE_WINDOW", self._close)

        frame = ctk.CTkScrollableFrame(self, fg_color=C["bg"], corner_radius=0)
        frame.pack(fill="both", expand=True, padx=14, pady=14)

        self._add_title(frame)
        self._add_general_controls(frame)
        for group_name, sliders in CAPSULE_GROUPS:
            self._add_group(frame, group_name, sliders)
        self._add_save_button(frame)

    def _add_title(self, parent):
        ctk.CTkLabel(parent, text="Controles de capsula", font=("Segoe UI", 15, "bold"),
                      text_color=C["text"]).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(parent, text="Ajusta fino y guarda cuando quede listo.", font=("Segoe UI", 10),
                      text_color=C["dim"]).pack(anchor="w", pady=(0, 12))

    def _add_general_controls(self, parent):
        box = self._section(parent, "General")

        ctk.CTkLabel(box, text="Atajo REC/STOP", font=("Segoe UI", 10),
                      text_color=C["dim"]).pack(anchor="w", padx=10, pady=(10, 4))
        hk_frame = ctk.CTkFrame(box, fg_color="transparent")
        hk_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.hotkey_var = ctk.StringVar(value=self.config_data.get("hotkey", "ctrl+space"))
        self.hotkey_entry = ctk.CTkEntry(hk_frame, textvariable=self.hotkey_var, width=178, height=30,
                                          fg_color=C["row"], border_color=C["border"],
                                          font=("Consolas", 12), state="disabled", text_color=C["text"])
        self.hotkey_entry.pack(side="left")

        self.capture_btn = ctk.CTkButton(hk_frame, text="Capturar", width=86, height=30, corner_radius=8,
                                          fg_color=C["row"], hover_color="#242936", text_color=C["accent"],
                                          font=("Segoe UI", 10), command=self._start_capture)
        self.capture_btn.pack(side="left", padx=(8, 0))

        ctk.CTkLabel(box, text="Modo minimizado", font=("Segoe UI", 10),
                      text_color=C["dim"]).pack(anchor="w", padx=10, pady=(0, 4))
        current_mode = self.config_data.get("mini_mode", "capsule")
        self.mini_mode_var = ctk.StringVar(value=MINI_MODE_VALUES.get(current_mode, "Capsula"))
        self.mini_mode_sel = ctk.CTkComboBox(
            box,
            values=list(MINI_MODE_LABELS.keys()),
            variable=self.mini_mode_var,
            width=180,
            height=30,
            font=("Segoe UI", 10),
            dropdown_font=("Segoe UI", 10),
            border_color=C["border"],
            button_color=C["border"],
            fg_color=C["row"],
            dropdown_fg_color=C["row"],
            corner_radius=8,
            state="readonly",
            command=lambda _: self._preview_now(),
        )
        self.mini_mode_sel.pack(anchor="w", padx=10, pady=(0, 12))

    def _section(self, parent, title):
        ctk.CTkLabel(parent, text=title.upper(), font=("Segoe UI", 10, "bold"),
                      text_color=C["value"]).pack(anchor="w", pady=(12, 5))
        box = ctk.CTkFrame(parent, fg_color=C["panel"], corner_radius=8,
                           border_width=1, border_color=C["border"])
        box.pack(fill="x")
        return box

    def _add_group(self, parent, title, sliders):
        box = self._section(parent, title)
        for index, (label, key, min_value, max_value, step, suffix) in enumerate(sliders):
            self._add_slider(box, label, key, min_value, max_value, step, suffix, index == len(sliders) - 1)

    def _add_slider(self, parent, label, key, min_value, max_value, step, suffix, is_last=False):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(9, 11 if is_last else 0))

        header = ctk.CTkFrame(row, fg_color="transparent")
        header.pack(fill="x")

        ctk.CTkLabel(header, text=label, font=("Segoe UI", 10),
                      text_color=C["dim"]).pack(side="left")
        value = self._coerce_int(self.config_data.get(key, min_value), min_value, max_value)
        value_var = ctk.StringVar(value=self._format_value(value, suffix))
        self._slider_vars[key] = (value_var, suffix)
        ctk.CTkLabel(header, textvariable=value_var, font=("Consolas", 10),
                      text_color=C["value"]).pack(side="right")

        slider = ctk.CTkSlider(
            row,
            from_=min_value,
            to=max_value,
            number_of_steps=max(1, int((max_value - min_value) / step)),
            width=346,
            button_color=C["accent"],
            button_hover_color="#9bb8ff",
            progress_color="#3b5fbd",
            fg_color="#252a33",
            command=lambda raw, k=key, mn=min_value, mx=max_value, st=step: self._slider_changed(k, raw, mn, mx, st),
        )
        slider.set(value)
        slider.pack(fill="x", pady=(5, 0))

    def _add_save_button(self, parent):
        buttons = ctk.CTkFrame(parent, fg_color="transparent")
        buttons.pack(fill="x", pady=(14, 0))
        ctk.CTkButton(buttons, text="Guardar", width=124, height=36, corner_radius=9,
                       fg_color=C["purple"], hover_color="#8844cc", text_color="#fff",
                       font=("Segoe UI", 12, "bold"), command=self._save).pack(side="right")

    def _slider_changed(self, key, raw_value, min_value, max_value, step):
        value = round(float(raw_value) / step) * step
        value = self._coerce_int(value, min_value, max_value)
        self.config_data[key] = value
        label_var, suffix = self._slider_vars[key]
        label_var.set(self._format_value(value, suffix))
        self._preview_now()

    def _preview_now(self):
        self.config_data["mini_mode"] = MINI_MODE_LABELS.get(self.mini_mode_var.get(), "capsule")
        if self.on_preview:
            self.on_preview(dict(self.config_data))

    def _format_value(self, value, suffix):
        return f"{value}{suffix}" if suffix else str(value)

    def _coerce_int(self, value, min_value, max_value):
        try:
            value = int(float(value))
        except Exception:
            value = int(min_value)
        return max(int(min_value), min(int(max_value), value))

    def _start_capture(self):
        if self._capturing_hotkey:
            return
        self._capturing_hotkey = True
        self.capture_btn.configure(text="Presiona...")
        self.hotkey_var.set("esperando...")
        threading.Thread(target=self._listen_hotkey, daemon=True).start()

    def _listen_hotkey(self):
        if not self._capturing_hotkey:
            return
        try:
            event = keyboard.read_hotkey(suppress=False)
            try:
                self.after(0, lambda: self._finish_hotkey_capture(event))
            except Exception:
                pass
        except Exception:
            try:
                self.after(0, lambda: self._finish_hotkey_capture(None))
            except Exception:
                pass

    def _finish_hotkey_capture(self, event):
        if not self._capturing_hotkey:
            return
        self._capturing_hotkey = False
        if event:
            self.hotkey_var.set(event)
        else:
            self.hotkey_var.set(self.config_data.get("hotkey", "ctrl+space"))
        self.capture_btn.configure(text="Capturar")

    def _save(self):
        self.config_data["hotkey"] = self.hotkey_var.get()
        self.config_data["mini_mode"] = MINI_MODE_LABELS.get(self.mini_mode_var.get(), "capsule")
        for _, key, min_value, max_value, _, _ in CAPSULE_SLIDERS:
            self.config_data[key] = self._coerce_int(self.config_data.get(key, min_value), min_value, max_value)
        if self.on_save:
            self.on_save(dict(self.config_data))
        self.destroy()

    def _close(self):
        self._capturing_hotkey = False
        if self.on_close:
            self.on_close()
        self.destroy()
