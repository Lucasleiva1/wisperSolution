"""ScribeFloat - Panel de Settings."""
import customtkinter as ctk
import keyboard

C = {
    "bg": "#121212", "bg2": "#1a1a1a", "border": "#2a2a2a",
    "text": "#f0f0f0", "dim": "#555555", "accent": "#4488ff",
    "purple": "#aa66ff", "green": "#44ff88", "red": "#ff4444",
}

class SettingsPanel(ctk.CTkToplevel):
    def __init__(self, parent, config, on_save=None):
        super().__init__(parent)
        self.title("⚙ Configuración")
        self.geometry("320x280")
        self.resizable(False, False)
        self.wm_attributes("-topmost", True)
        self.configure(fg_color=C["bg"])
        self.config_data = dict(config)
        self.on_save = on_save
        self._capturing_hotkey = False

        frame = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        frame.pack(fill="both", expand=True, padx=16, pady=16)

        # --- Hotkey ---
        ctk.CTkLabel(frame, text="Atajo de teclado (REC/STOP):", font=("Segoe UI", 11),
                      text_color=C["dim"]).pack(anchor="w", pady=(0, 4))

        hk_frame = ctk.CTkFrame(frame, fg_color="transparent")
        hk_frame.pack(fill="x", pady=(0, 12))

        self.hotkey_var = ctk.StringVar(value=self.config_data.get("hotkey", "ctrl+space"))
        self.hotkey_entry = ctk.CTkEntry(hk_frame, textvariable=self.hotkey_var, width=160, height=30,
                                          fg_color=C["bg2"], border_color=C["border"], font=("Consolas", 12),
                                          state="disabled", text_color=C["text"])
        self.hotkey_entry.pack(side="left")

        self.capture_btn = ctk.CTkButton(hk_frame, text="Capturar", width=80, height=30, corner_radius=8,
                                          fg_color=C["bg2"], hover_color="#222", text_color=C["accent"],
                                          font=("Segoe UI", 10), command=self._start_capture)
        self.capture_btn.pack(side="left", padx=(8, 0))

        # --- Auto AI ---
        ctk.CTkLabel(frame, text="Post-procesado automático con IA:", font=("Segoe UI", 11),
                      text_color=C["dim"]).pack(anchor="w", pady=(0, 4))

        self.auto_ai_var = ctk.BooleanVar(value=self.config_data.get("auto_ai", True))
        ctk.CTkSwitch(frame, text="Activar IA automática", variable=self.auto_ai_var,
                       font=("Segoe UI", 11), text_color=C["text"],
                       fg_color=C["border"], progress_color=C["purple"]).pack(anchor="w", pady=(0, 12))

        # --- Modelo Ollama ---
        ctk.CTkLabel(frame, text="Modelo Ollama:", font=("Segoe UI", 11),
                      text_color=C["dim"]).pack(anchor="w", pady=(0, 4))

        self.model_var = ctk.StringVar(value=self.config_data.get("ollama_model", "qwen3.5:2b"))
        ctk.CTkEntry(frame, textvariable=self.model_var, width=200, height=30,
                      fg_color=C["bg2"], border_color=C["border"], font=("Consolas", 11),
                      text_color=C["text"]).pack(anchor="w", pady=(0, 16))

        # --- Guardar ---
        ctk.CTkButton(frame, text="Guardar", width=120, height=34, corner_radius=10,
                       fg_color=C["purple"], hover_color="#8844cc", text_color="#fff",
                       font=("Segoe UI", 12, "bold"), command=self._save).pack(anchor="e")

    def _start_capture(self):
        self._capturing_hotkey = True
        self.capture_btn.configure(text="Presiona...")
        self.hotkey_var.set("esperando...")
        self.after(100, self._listen_hotkey)

    def _listen_hotkey(self):
        if not self._capturing_hotkey:
            return
        try:
            event = keyboard.read_hotkey(suppress=False)
            self.hotkey_var.set(event)
            self._capturing_hotkey = False
            self.capture_btn.configure(text="Capturar")
        except Exception:
            self.after(100, self._listen_hotkey)

    def _save(self):
        self.config_data["hotkey"] = self.hotkey_var.get()
        self.config_data["auto_ai"] = self.auto_ai_var.get()
        self.config_data["ollama_model"] = self.model_var.get()
        if self.on_save:
            self.on_save(self.config_data)
        self.destroy()
