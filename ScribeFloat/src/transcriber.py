"""
ScribeFloat - Motor de Transcripción Multilingüe
Utiliza Faster-Whisper con optimización para GPUs con 4GB VRAM (GTX 1050 Ti).
"""

import os
import site
import sys
import threading
import ctypes


_DLL_DIRECTORY_HANDLES = []


def _add_cuda_dll_directories():
    """Allow CTranslate2 to find CUDA DLLs installed in this virtualenv."""
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return

    candidate_roots = []
    for path in site.getsitepackages() + sys.path:
        if path and path.endswith("site-packages") and path not in candidate_roots:
            candidate_roots.append(path)

    for root in candidate_roots:
        for relative_path in (
            os.path.join("nvidia", "cuda_runtime", "bin"),
            os.path.join("nvidia", "cuda_nvrtc", "bin"),
            os.path.join("nvidia", "cublas", "bin"),
            os.path.join("nvidia", "cudnn", "bin"),
            "ctranslate2",
        ):
            dll_dir = os.path.join(root, relative_path)
            if os.path.isdir(dll_dir):
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(dll_dir))


_add_cuda_dll_directories()

import ctranslate2
from faster_whisper import WhisperModel


class ScribeEngine:
    """
    Motor de transcripción basado en Faster-Whisper.
    Soporta modelos base, small y medium con cambio en caliente.
    """

    SUPPORTED_LANGUAGES = {
        "es": "Español",
        "en": "Inglés",
        "pt": "Portugués",
        "fr": "Francés",
        "de": "Alemán",
        "it": "Italiano",
        "ja": "Japonés",
        "zh": "Chino",
    }

    AVAILABLE_MODELS = {
        "base": "Base (rápido, buena precisión)",
        "small": "Small (equilibrado)",
        "medium": "Medium (lento, máxima precisión)",
    }

    def __init__(self, language: str = "es", model_size: str = "small"):
        self.model_size = model_size
        self.device = self._detect_device()
        self.compute_type = "int8_float32" if self.device == "cuda" else "int8"
        self.current_language = language
        self._model = None
        self._previous_text = ""  # Contexto para mejorar precisión
        self._lock = threading.Lock()
        
        print(f"[ScribeEngine] Device: {self.device} | Modelo: {self.model_size} | Idioma: {self.current_language}")

    def _detect_device(self) -> str:
        """Detecta si CTranslate2 puede usar CUDA sin depender de Torch."""
        try:
            if ctranslate2.get_cuda_device_count() > 0:
                try:
                    ctypes.WinDLL("cublas64_12.dll")
                except Exception as e:
                    print(f"[ScribeEngine] CUDA detectado, pero falta cublas64_12.dll. Usando CPU: {e}")
                    return "cpu"
                return "cuda"
        except Exception as e:
            print(f"[ScribeEngine] CUDA no disponible para CTranslate2: {e}")
        return "cpu"

    def _load_model(self):
        """Carga el modelo de forma diferida (lazy loading)."""
        if self._model is None:
            print(f"[ScribeEngine] Cargando modelo '{self.model_size}' en {self.device}...")
            models_dir = os.path.join(os.getenv("LOCALAPPDATA", os.path.expanduser("~")), "ScribeFloat", "models")
            os.makedirs(models_dir, exist_ok=True)
            try:
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=models_dir
                )
            except Exception as e:
                if self.device != "cuda":
                    raise
                print(f"[ScribeEngine] CUDA fallo ({e}). Reintentando en CPU/int8...")
                self.device = "cpu"
                self.compute_type = "int8"
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=models_dir
                )
            print("[ScribeEngine] Modelo cargado exitosamente.")
        return self._model

    @property
    def model(self):
        return self._load_model()

    def warm_up(self):
        """Carga el modelo antes de la primera frase para evitar latencia inicial."""
        with self._lock:
            self._load_model()

    def set_language(self, lang_code: str):
        """
        Cambia el idioma de transcripción.
        No requiere recargar el modelo.
        """
        if lang_code in self.SUPPORTED_LANGUAGES:
            with self._lock:
                self.current_language = lang_code
            print(f"[ScribeEngine] Idioma cambiado a: {self.SUPPORTED_LANGUAGES[lang_code]} ({lang_code})")
        else:
            print(f"[ScribeEngine] Idioma '{lang_code}' no soportado. Disponibles: {list(self.SUPPORTED_LANGUAGES.keys())}")

    def change_model(self, new_model_size: str):
        """Cambia el modelo de Whisper. Requiere recargar."""
        if new_model_size not in self.AVAILABLE_MODELS:
            print(f"[ScribeEngine] Modelo '{new_model_size}' no válido.")
            return
        if new_model_size == self.model_size and self._model is not None:
            return  # Ya está cargado
        print(f"[ScribeEngine] Cambiando modelo de '{self.model_size}' a '{new_model_size}'...")
        with self._lock:
            self.model_size = new_model_size
            self._model = None  # Forzar recarga en siguiente uso
            self._previous_text = ""

    def transcribe(self, audio_path: str) -> str:
        """
        Transcribe un archivo de audio al idioma configurado.
        Usa contexto de frases anteriores para mayor precisión.
        """
        with self._lock:
            try:
                return self._transcribe_locked(audio_path)
            except Exception as e:
                if self.device == "cuda":
                    print(f"[ScribeEngine] CUDA fallo transcribiendo ({e}). Reintentando en CPU/int8...")
                    self.device = "cpu"
                    self.compute_type = "int8"
                    self._model = None
                    try:
                        return self._transcribe_locked(audio_path)
                    except Exception as cpu_error:
                        print(f"[ScribeEngine] Error en transcripción CPU: {cpu_error}")
                        return f"[Error: {str(cpu_error)}]"
                print(f"[ScribeEngine] Error en transcripción: {e}")
                return f"[Error: {str(e)}]"

    def _transcribe_locked(self, audio_path: str) -> str:
        # Usar las ultimas 200 letras como contexto para Whisper
        prompt = self._previous_text[-200:] if self._previous_text else None

        segments, info = self.model.transcribe(
            audio_path,
            beam_size=1,
            language=self.current_language,
            vad_filter=False,  # VAD ya se maneja en audio_stream.py
            initial_prompt=prompt,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
        )

        full_text = " ".join([segment.text for segment in segments])
        result = full_text.strip()

        # Actualizar contexto para la proxima transcripcion
        if result:
            self._previous_text = (self._previous_text + " " + result)[-1000:]

        return result

    def clear_context(self):
        """Limpia el contexto acumulado (al presionar limpiar texto)."""
        with self._lock:
            self._previous_text = ""

    def transcribe_with_info(self, audio_path: str) -> dict:
        """
        Transcribe y retorna información detallada (idioma detectado, probabilidad, etc.).
        """
        try:
            with self._lock:
                prompt = self._previous_text[-200:] if self._previous_text else None

                segments, info = self.model.transcribe(
                    audio_path,
                    beam_size=1,
                    language=self.current_language,
                    vad_filter=False,
                    initial_prompt=prompt,
                    condition_on_previous_text=False,
                    no_speech_threshold=0.6,
                )

                segments_list = []
                full_text_parts = []
                for segment in segments:
                    segments_list.append({
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text,
                    })
                    full_text_parts.append(segment.text)

                result = " ".join(full_text_parts).strip()
                if result:
                    self._previous_text = (self._previous_text + " " + result)[-1000:]

            return {
                "text": result,
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": info.duration,
                "segments": segments_list
            }

        except Exception as e:
            print(f"[ScribeEngine] Error: {e}")
            return {"text": f"[Error: {str(e)}]", "language": "unknown", "segments": []}
