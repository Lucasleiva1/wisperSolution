"""
ScribeFloat - Motor de Transcripción Multilingüe
Utiliza Faster-Whisper con optimización para GPUs con 4GB VRAM (GTX 1050 Ti).
"""

import torch
from faster_whisper import WhisperModel


class ScribeEngine:
    """
    Motor de transcripción basado en Faster-Whisper.
    Optimizado para bajo consumo de VRAM con modelo 'small' multilingüe.
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

    def __init__(self, language: str = "es", model_size: str = "small"):
        self.model_size = model_size  # Modelo multilingüe
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.compute_type = "int8" if self.device == "cuda" else "int8"  # Máx optimización VRAM
        self.current_language = language
        self._model = None
        
        print(f"[ScribeEngine] Device: {self.device} | Modelo: {self.model_size} | Idioma: {self.current_language}")

    def _load_model(self):
        """Carga el modelo de forma diferida (lazy loading)."""
        if self._model is None:
            print(f"[ScribeEngine] Cargando modelo '{self.model_size}' en {self.device}...")
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                download_root="models"
            )
            print("[ScribeEngine] Modelo cargado exitosamente.")
        return self._model

    @property
    def model(self):
        return self._load_model()

    def set_language(self, lang_code: str):
        """
        Cambia el idioma de transcripción.
        No requiere recargar el modelo.
        """
        if lang_code in self.SUPPORTED_LANGUAGES:
            self.current_language = lang_code
            print(f"[ScribeEngine] Idioma cambiado a: {self.SUPPORTED_LANGUAGES[lang_code]} ({lang_code})")
        else:
            print(f"[ScribeEngine] Idioma '{lang_code}' no soportado. Disponibles: {list(self.SUPPORTED_LANGUAGES.keys())}")

    def transcribe(self, audio_path: str) -> str:
        """
        Transcribe un archivo de audio al idioma configurado.
        Usa VAD filter para mayor precisión.
        """
        try:
            segments, info = self.model.transcribe(
                audio_path,
                beam_size=5,
                language=self.current_language,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=800,  # Más tiempo para frases completas
                    speech_pad_ms=400
                )
            )

            full_text = " ".join([segment.text for segment in segments])
            return full_text.strip()

        except Exception as e:
            print(f"[ScribeEngine] Error en transcripción: {e}")
            return f"[Error: {str(e)}]"

    def transcribe_with_info(self, audio_path: str) -> dict:
        """
        Transcribe y retorna información detallada (idioma detectado, probabilidad, etc.).
        """
        try:
            segments, info = self.model.transcribe(
                audio_path,
                beam_size=5,
                language=self.current_language,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=800)
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

            return {
                "text": " ".join(full_text_parts).strip(),
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": info.duration,
                "segments": segments_list
            }

        except Exception as e:
            print(f"[ScribeEngine] Error: {e}")
            return {"text": f"[Error: {str(e)}]", "language": "unknown", "segments": []}
