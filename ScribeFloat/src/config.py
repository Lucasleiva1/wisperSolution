"""ScribeFloat - Configuración persistente."""
import json
import os

appdata_dir = os.path.join(os.getenv("LOCALAPPDATA", os.path.expanduser("~")), "ScribeFloat")
CONFIG_FILE = os.path.join(appdata_dir, "config.json")

DEFAULT_CONFIG = {
    "hotkey": "ctrl+space",
    "language": "es",
    "model_size": "small",
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
