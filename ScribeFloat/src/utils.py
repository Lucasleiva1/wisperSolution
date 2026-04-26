"""
ScribeFloat - Utilidades
Funciones de limpieza de texto, guardado y post-procesado.
"""

import os
import re
from datetime import datetime


def clean_text(text: str) -> str:
    """
    Limpia y normaliza el texto transcrito.
    - Elimina espacios múltiples
    - Agrega puntuación final si falta
    - Capitaliza la primera letra
    """
    if not text or not text.strip():
        return ""
    
    # Eliminar espacios múltiples
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Capitalizar primera letra
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    
    # Agregar punto final si el último carácter es una letra o número
    if text and text[-1].isalnum():
        text += "."
    
    return text


def save_transcription(text: str, export_dir: str = "exports", filename: str = None) -> str:
    """
    Guarda la transcripción en un archivo .txt con marca de tiempo.
    Retorna la ruta del archivo guardado.
    """
    os.makedirs(export_dir, exist_ok=True)
    
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"transcripcion_{timestamp}.txt"
    
    filepath = os.path.join(export_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"--- ScribeFloat Transcripción ---\n")
        f.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'=' * 40}\n\n")
        f.write(text)
        f.write(f"\n\n{'=' * 40}\n")
        f.write(f"--- Fin de transcripción ---\n")
    
    return filepath


def format_duration(seconds: float) -> str:
    """Formatea segundos a MM:SS."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"
