"""ScribeFloat - Configuración persistente."""
import json
import os

appdata_dir = os.path.join(os.getenv("LOCALAPPDATA", os.path.expanduser("~")), "ScribeFloat")
CONFIG_FILE = os.path.join(appdata_dir, "config.json")

DEFAULT_CONFIG = {
    "hotkey": "ctrl+space",
    "language": "es",
    "model_size": "small",
    "mini_mode": "capsule",
    "capsule_width": 180,
    "capsule_height": 30,
    "capsule_border_glow": 115,
    "capsule_mic_scale": 115,
    "capsule_indicator_scale": 90,
    "capsule_wave_bars": 42,
    "capsule_wave_sensitivity": 130,
    "capsule_wave_smoothing": 28,
    "capsule_wave_amplitude": 115,
    "capsule_wave_spread": 110,
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    os.makedirs(appdata_dir, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
