"""
ScribeFloat - Captura de Audio y VAD
Captura audio del micrófono en tiempo real con detección de actividad de voz.
"""

import os
import wave
import threading
import numpy as np
import sounddevice as sd

# Configuración de audio
SAMPLE_RATE = 16000       # Whisper necesita 16kHz
CHANNELS = 1              # Mono
BLOCK_DURATION_MS = 30    # Duración de cada bloque de audio (ms)
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION_MS / 1000)  # Muestras por bloque

# Parámetros VAD — umbrales bajos para captar bien la voz
SILENCE_THRESHOLD = 0.0015  # Umbral de energía moderado (ni muy sordo ni muy sensible)
MIN_SPEECH_DURATION = 0.3  # Segundos mínimos de habla para considerar frase
MAX_SILENCE_DURATION = 0.8 # Segundos de silencio antes de cortar la frase
MAX_RECORDING_DURATION = 30.0  # Máximo segundos por segmento


class AudioCapture:
    """
    Motor de captura de audio con VAD basado en energía.
    Detecta cuándo el usuario habla y genera segmentos de audio
    que se envían al transcriptor.
    """

    def __init__(self, on_segment_ready=None, on_level_update=None, temp_dir="exports"):
        self.sample_rate = SAMPLE_RATE
        self.channels = CHANNELS
        self.is_recording = False
        self.is_paused = False
        self._stream = None
        
        # Callbacks
        self.on_segment_ready = on_segment_ready   # Cuando hay un segmento listo
        self.on_level_update = on_level_update     # Para actualizar nivel de audio en UI
        
        # Buffer de audio
        self._audio_buffer = []
        self._silence_counter = 0
        self._speech_counter = 0
        self._is_speaking = False
        
        # Directorio temporal para archivos de audio
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Selección de dispositivo
        self.device_id = None  # None = default

    def _energy_vad(self, audio_block: np.ndarray) -> bool:
        """
        VAD simple basado en energía RMS.
        Retorna True si se detecta voz en el bloque.
        """
        energy = np.sqrt(np.mean(audio_block ** 2))
        return energy > SILENCE_THRESHOLD

    def _get_level(self, audio_block: np.ndarray) -> float:
        """Retorna el nivel de audio normalizado 0.0-1.0."""
        rms = np.sqrt(np.mean(audio_block ** 2))
        # Normalizar (clamp a 0-1)
        level = min(1.0, rms / 0.01)
        return level

    def _audio_callback(self, indata, frames, time_info, status):
        """Callback llamado por sounddevice en cada bloque de audio."""
        if status:
            print(f"[AudioCapture] Status: {status}")
        
        if self.is_paused:
            return
            
        audio_block = indata[:, 0].copy()  # Mono
        has_speech = self._energy_vad(audio_block)
        
        # Enviar nivel de audio a la UI
        if self.on_level_update:
            level = self._get_level(audio_block)
            self.on_level_update(level, has_speech)

        if has_speech:
            self._speech_counter += BLOCK_DURATION_MS / 1000.0
            self._silence_counter = 0
            
            if not self._is_speaking and self._speech_counter >= MIN_SPEECH_DURATION:
                self._is_speaking = True
                
            self._audio_buffer.append(audio_block)

        else:
            if self._is_speaking:
                self._silence_counter += BLOCK_DURATION_MS / 1000.0
                self._audio_buffer.append(audio_block)  # Mantener silencio corto

                # Si el silencio supera el umbral, finalizar segmento
                if self._silence_counter >= MAX_SILENCE_DURATION:
                    self._finalize_segment()
            else:
                self._speech_counter = 0  # Reset si no hay habla sostenida

        # Verificar duración máxima
        total_duration = len(self._audio_buffer) * BLOCK_DURATION_MS / 1000.0
        if total_duration >= MAX_RECORDING_DURATION and self._is_speaking:
            self._finalize_segment()

    def _finalize_segment(self):
        """Guarda el segmento de audio y notifica al callback."""
        if not self._audio_buffer:
            self._reset_state()
            return

        # Concatenar todo el audio del buffer
        audio_data = np.concatenate(self._audio_buffer)
        
        # Verificar que hay suficiente audio (al menos 0.5s)
        min_samples = int(self.sample_rate * 0.5)
        if len(audio_data) < min_samples:
            self._reset_state()
            return
        
        # Guardar como WAV temporal
        temp_path = os.path.join(self.temp_dir, f"_segment_temp.wav")
        self._save_wav(audio_data, temp_path)
        
        # Notificar al callback
        if self.on_segment_ready:
            self.on_segment_ready(temp_path)
        
        # Reset del estado
        self._reset_state()

    def _reset_state(self):
        """Resetea los contadores y buffers del VAD."""
        self._audio_buffer = []
        self._silence_counter = 0
        self._speech_counter = 0
        self._is_speaking = False

    def _save_wav(self, audio_data: np.ndarray, filepath: str):
        """Guarda un array numpy como archivo WAV 16-bit."""
        # Normalizar a int16
        audio_int16 = (audio_data * 32767).astype(np.int16)
        
        with wave.open(filepath, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_int16.tobytes())

    def start(self):
        """Inicia la captura de audio del micrófono."""
        if self.is_recording:
            print("[AudioCapture] Ya está grabando.")
            return

        self.is_recording = True
        self.is_paused = False
        self._reset_state()
        
        try:
            self._stream = sd.InputStream(
                device=self.device_id,
                samplerate=self.sample_rate,
                channels=self.channels,
                blocksize=BLOCK_SIZE,
                dtype='float32',
                callback=self._audio_callback
            )
            self._stream.start()
            print("[AudioCapture] Captura iniciada.")
        except Exception as e:
            self.is_recording = False
            print(f"[AudioCapture] Error al iniciar: {e}")
            raise

    def stop(self):
        """Detiene la captura de audio."""
        if not self.is_recording:
            return

        # Finalizar cualquier segmento pendiente
        if self._is_speaking and self._audio_buffer:
            self._finalize_segment()

        self.is_recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        
        print("[AudioCapture] Captura detenida.")

    def pause(self):
        """Pausa la captura sin detener el stream."""
        self.is_paused = True

    def resume(self):
        """Reanuda la captura."""
        self.is_paused = False
        self._reset_state()

    @staticmethod
    def list_devices():
        """Lista los dispositivos de entrada de audio disponibles."""
        devices = sd.query_devices()
        input_devices = []
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                input_devices.append({
                    "id": i,
                    "name": dev['name'],
                    "channels": dev['max_input_channels'],
                    "sample_rate": dev['default_samplerate']
                })
        return input_devices
