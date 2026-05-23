"""
ScribeFloat - Captura de Audio y VAD
Captura audio del micrófono en tiempo real con detección de actividad de voz.
"""

import os
import wave
from collections import deque
import numpy as np
import sounddevice as sd

# Configuración de audio
SAMPLE_RATE = 16000       # Whisper necesita 16kHz
CHANNELS = 1              # Mono
BLOCK_DURATION_MS = 30    # Duración de cada bloque de audio (ms)
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION_MS / 1000)  # Muestras por bloque

# Parámetros VAD — umbrales bajos para captar bien la voz
SILENCE_THRESHOLD = 0.00035  # Umbral de energía moderado (ni muy sordo ni muy sensible)
MIN_SPEECH_DURATION = 0.18  # Segundos mínimos de habla para considerar frase
MAX_SILENCE_DURATION = 0.6 # Segundos de silencio antes de cortar la frase
MAX_RECORDING_DURATION = 30.0  # Máximo segundos por segmento
PRE_ROLL_DURATION = 0.25  # Audio previo que evita cortar la primera silaba


class AudioCapture:
    """
    Motor de captura de audio con VAD basado en energía.
    Detecta cuándo el usuario habla y genera segmentos de audio
    que se envían al transcriptor.
    """

    def __init__(self, on_segment_ready=None, on_level_update=None, temp_dir=None, finalize_on_silence=True):
        self.sample_rate = SAMPLE_RATE
        self.channels = CHANNELS
        self.is_recording = False
        self.is_paused = False
        self.finalize_on_silence = finalize_on_silence
        self._stream = None
        
        # Callbacks
        self.on_segment_ready = on_segment_ready   # Cuando hay un segmento listo
        self.on_level_update = on_level_update     # Para actualizar nivel de audio en UI
        
        # Buffer de audio
        self._audio_buffer = []
        self._session_buffer = []
        self._silence_counter = 0
        self._speech_counter = 0
        self._is_speaking = False
        self._segment_counter = 0
        self._emitted_segment = False
        self._session_peak_energy = 0.0
        self._noise_floor = SILENCE_THRESHOLD / 2
        pre_roll_blocks = max(1, int(PRE_ROLL_DURATION * 1000 / BLOCK_DURATION_MS))
        self._pre_roll = deque(maxlen=pre_roll_blocks)
        
        # Directorio temporal para archivos de audio
        if temp_dir is None:
            temp_dir = os.path.join(os.getenv("LOCALAPPDATA", os.path.expanduser("~")), "ScribeFloat", "temp_audio")
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Limpiar archivos temporales viejos al iniciar
        try:
            for f in os.listdir(self.temp_dir):
                if f.endswith(".wav"):
                    os.remove(os.path.join(self.temp_dir, f))
        except Exception as e:
            print(f"[AudioCapture] Error limpiando temporales: {e}")

        # Selección de dispositivo
        self.device_id = None  # None = default

    def _block_energy(self, audio_block: np.ndarray) -> float:
        energy = np.sqrt(np.mean(audio_block ** 2))
        return float(energy)

    def _current_threshold(self) -> float:
        return max(SILENCE_THRESHOLD, self._noise_floor * 2.6)

    def _energy_vad(self, audio_block: np.ndarray) -> bool:
        """
        VAD simple basado en energia RMS con piso de ruido adaptativo.
        Retorna True si se detecta voz en el bloque.
        """
        return self._block_energy(audio_block) > self._current_threshold()

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
        energy = self._block_energy(audio_block)
        self._session_buffer.append(audio_block)
        self._session_peak_energy = max(self._session_peak_energy, energy)
        has_speech = energy > self._current_threshold()

        if not self._is_speaking and not has_speech:
            self._noise_floor = (self._noise_floor * 0.95) + (energy * 0.05)
        
        # Enviar nivel de audio a la UI
        if self.on_level_update:
            level = self._get_level(audio_block)
            self.on_level_update(level, has_speech)

        if has_speech:
            self._speech_counter += BLOCK_DURATION_MS / 1000.0
            self._silence_counter = 0

            if not self._is_speaking:
                self._is_speaking = True
                if not self._audio_buffer:
                    self._audio_buffer.extend(list(self._pre_roll))
                
            self._audio_buffer.append(audio_block)

        else:
            if self._is_speaking:
                self._silence_counter += BLOCK_DURATION_MS / 1000.0
                if self.finalize_on_silence or self._silence_counter <= MAX_SILENCE_DURATION:
                    self._audio_buffer.append(audio_block)  # Mantener silencio corto

                # Si el silencio supera el umbral, finalizar segmento
                if self.finalize_on_silence and self._silence_counter >= MAX_SILENCE_DURATION:
                    self._finalize_segment()
            else:
                self._audio_buffer = []
                self._speech_counter = 0  # Reset si no hay habla sostenida
                self._pre_roll.append(audio_block)

        # Verificar duración máxima
        total_duration = len(self._audio_buffer) * BLOCK_DURATION_MS / 1000.0
        if self.finalize_on_silence and total_duration >= MAX_RECORDING_DURATION and self._is_speaking:
            self._finalize_segment()

    def _finalize_segment(self):
        """Guarda el segmento de audio y notifica al callback."""
        if not self._audio_buffer:
            self._reset_state(clear_pre_roll=True)
            return

        if self._speech_counter < MIN_SPEECH_DURATION:
            self._reset_state(clear_pre_roll=True)
            return

        # Concatenar todo el audio del buffer
        audio_data = np.concatenate(self._audio_buffer)
        
        # Verificar que hay suficiente audio (al menos 0.5s)
        min_samples = int(self.sample_rate * 0.5)
        if len(audio_data) < min_samples:
            self._reset_state(clear_pre_roll=True)
            return
        
        # Guardar como WAV temporal con nombre único por segmento
        self._segment_counter += 1
        temp_path = os.path.join(self.temp_dir, f"_segment_{self._segment_counter}.wav")
        self._save_wav(audio_data, temp_path)
        
        # Notificar al callback
        if self.on_segment_ready:
            self.on_segment_ready(temp_path)
        self._emitted_segment = True
        self._session_buffer = []
        
        # Reset del estado
        self._reset_state(clear_pre_roll=True)

    def _finalize_full_session(self):
        """Guarda toda la sesion si el VAD no genero ningun segmento."""
        if self._emitted_segment or not self._session_buffer:
            return
        audio_data = np.concatenate(self._session_buffer)
        min_samples = int(self.sample_rate * 0.5)
        if len(audio_data) < min_samples:
            return

        self._segment_counter += 1
        temp_path = os.path.join(self.temp_dir, f"_session_{self._segment_counter}.wav")
        self._save_wav(audio_data, temp_path)

        if self.on_segment_ready:
            self.on_segment_ready(temp_path)
        self._emitted_segment = True
        self._session_buffer = []

    def _reset_state(self, clear_pre_roll=False):
        """Resetea los contadores y buffers del VAD."""
        self._audio_buffer = []
        self._silence_counter = 0
        self._speech_counter = 0
        self._is_speaking = False
        if clear_pre_roll:
            self._pre_roll.clear()

    def _save_wav(self, audio_data: np.ndarray, filepath: str):
        """Guarda un array numpy como archivo WAV 16-bit."""
        # Normalizar a int16
        audio_int16 = (np.clip(audio_data, -1.0, 1.0) * 32767).astype(np.int16)
        
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
        self._session_buffer = []
        self._emitted_segment = False
        self._session_peak_energy = 0.0
        self._reset_state(clear_pre_roll=True)
        
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

        # Si no cortamos por pausas, al STOP siempre se envia la sesion completa.
        if not self.finalize_on_silence:
            self._finalize_full_session()
        elif self._audio_buffer:
            self._finalize_segment()
            self._finalize_full_session()

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
        self._reset_state(clear_pre_roll=True)

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
