"""
ScribeFloat - Cliente Ollama
Conexión con modelos locales de Ollama (qwen3.5:2b) para
post-procesado inteligente del texto transcrito.
"""

import json
import requests
import threading


OLLAMA_BASE_URL = "http://localhost:11434"


class OllamaClient:
    """
    Cliente para comunicarse con Ollama vía API REST local.
    Usado para mejorar, resumir o reformatear el texto transcrito.
    """

    def __init__(self, model: str = "qwen3.5:2b", base_url: str = OLLAMA_BASE_URL):
        self.model = model
        self.base_url = base_url
        self.is_available = False
        self._check_connection()

    def _check_connection(self):
        """Verifica si Ollama está corriendo."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                self.is_available = any(self.model in name for name in model_names)
                if self.is_available:
                    print(f"[OllamaClient] Conectado. Modelo '{self.model}' disponible.")
                else:
                    print(f"[OllamaClient] Conectado, pero '{self.model}' no encontrado. Modelos: {model_names}")
            else:
                print(f"[OllamaClient] Ollama respondió con status {resp.status_code}")
        except requests.ConnectionError:
            print("[OllamaClient] Ollama no está corriendo. Las funciones de IA estarán deshabilitadas.")
        except Exception as e:
            print(f"[OllamaClient] Error de conexión: {e}")

    def generate(self, prompt: str, system: str = None, temperature: float = 0.3) -> str:
        """
        Genera una respuesta del modelo Ollama de forma síncrona.
        """
        if not self.is_available:
            return "[Ollama no disponible]"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 256,
            }
        }

        if system:
            payload["system"] = system

        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=180
            )
            if resp.status_code == 200:
                return resp.json().get("response", "").strip()
            else:
                return f"[Error Ollama: {resp.status_code}]"
        except Exception as e:
            return f"[Error: {e}]"

    def generate_async(self, prompt: str, callback, system: str = None, temperature: float = 0.3):
        """
        Genera una respuesta en un hilo separado y llama al callback con el resultado.
        """
        def _worker():
            result = self.generate(prompt, system=system, temperature=temperature)
            if callback:
                callback(result)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def improve_text(self, raw_text: str, language: str = "es") -> str:
        """
        Usa el modelo para mejorar el texto transcrito:
        - Corrige gramática
        - Agrega puntuación
        - Mejora la coherencia
        """
        lang_names = {"es": "español", "en": "inglés", "pt": "portugués"}
        lang_name = lang_names.get(language, "español")

        system_prompt = (
            f"Eres un asistente de corrección de texto en {lang_name}. "
            "Tu única tarea es corregir la gramática, ortografía y puntuación del texto dado. "
            "NO cambies el significado. NO agregues contenido nuevo. "
            "Devuelve SOLO el texto corregido, sin explicaciones."
        )

        return self.generate(raw_text, system=system_prompt, temperature=0.1)

    def summarize_text(self, text: str, language: str = "es") -> str:
        """Resume el texto transcrito."""
        lang_names = {"es": "español", "en": "inglés", "pt": "portugués"}
        lang_name = lang_names.get(language, "español")

        system_prompt = (
            f"Eres un asistente de resumen en {lang_name}. "
            "Resume el siguiente texto en 2-3 oraciones concisas. "
            "Mantén los puntos clave. Devuelve SOLO el resumen."
        )

        return self.generate(text, system=system_prompt, temperature=0.2)

    def improve_text_async(self, raw_text: str, callback, language: str = "es"):
        """Versión asíncrona de improve_text."""
        def _worker():
            result = self.improve_text(raw_text, language)
            if callback:
                callback(result)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def summarize_text_async(self, text: str, callback, language: str = "es"):
        """Versión asíncrona de summarize_text."""
        def _worker():
            result = self.summarize_text(text, language)
            if callback:
                callback(result)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
