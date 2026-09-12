"""
AURA STT Engine — Voice input via Vosk (offline).
Captures microphone audio, transcribes with Vosk, returns text.
Uses large model + energy gate + per-word confidence filtering to
suppress noise-driven hallucinations.
"""

import json
import os
import queue
import struct
import math
import threading

# Prefer the large model when present; fall back to small if not.
_LARGE = "D:/AURA/models/vosk-model-en-us-0.22"
_SMALL = "D:/AURA/models/vosk-model-small-en-us-0.15"
VOSK_MODEL_PATH = _LARGE if os.path.exists(_LARGE) else _SMALL

# Audio gating thresholds
ENERGY_THRESHOLD = 600       # RMS below this is silence (was 300 — too lax)
MIN_AVG_WORD_CONF = 0.85     # Vosk per-word confidence; below this is discarded
MIN_RESULT_CHARS = 3         # Single-letter "transcripts" are always noise


class STTEngine:
    """Offline speech-to-text using Vosk + sounddevice."""

    def __init__(self):
        self._model = None
        self._listening = False
        self._result = None
        self._audio_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._model_loaded = False

    def _ensure_model(self):
        if self._model_loaded:
            return
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        if not os.path.exists(VOSK_MODEL_PATH):
            raise FileNotFoundError(
                f"Vosk model not found at {VOSK_MODEL_PATH}. "
                "Download vosk-model-small-en-us-0.15 and extract there."
            )
        self._model = Model(VOSK_MODEL_PATH)
        self._model_loaded = True

    @property
    def is_listening(self) -> bool:
        return self._listening

    def start_listening(self):
        """Begin capturing and transcribing in a background thread."""
        if self._listening:
            return
        self._ensure_model()
        self._stop_event.clear()
        self._result = None
        self._listening = True
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def stop_listening(self) -> str:
        """Stop capturing and return the transcribed text."""
        self._stop_event.set()
        for _ in range(60):
            if not self._listening:
                break
            import time
            time.sleep(0.05)
        return self._result or ""

    def get_result(self) -> dict:
        """Poll for the transcription result."""
        return {
            "listening": self._listening,
            "text": self._result or "",
        }

    @staticmethod
    def _rms(data: bytes) -> float:
        """Compute RMS energy of 16-bit PCM audio."""
        count = len(data) // 2
        if count == 0:
            return 0.0
        samples = struct.unpack(f"<{count}h", data)
        sum_sq = sum(s * s for s in samples)
        return math.sqrt(sum_sq / count)

    @staticmethod
    def _filter_result(raw: dict) -> str:
        """Keep transcript only if word confidences clear the bar."""
        text = (raw.get("text") or "").strip()
        if not text or len(text) < MIN_RESULT_CHARS:
            return ""
        words = raw.get("result") or []
        if not words:
            # No per-word confidences (partial result style) — accept as-is.
            return text
        confs = [w.get("conf", 0.0) for w in words]
        if not confs:
            return ""
        avg = sum(confs) / len(confs)
        if avg < MIN_AVG_WORD_CONF:
            return ""
        return text

    def _listen_loop(self):
        """Capture audio from mic and transcribe with Vosk."""
        import sounddevice as sd
        from vosk import KaldiRecognizer

        samplerate = 16000
        recognizer = KaldiRecognizer(self._model, samplerate)
        recognizer.SetWords(True)  # emit per-word confidence in Result()

        audio_buffer = queue.Queue()

        def audio_callback(indata, frames, time_info, status):
            audio_buffer.put(bytes(indata))

        try:
            with sd.RawInputStream(
                samplerate=samplerate,
                blocksize=1600,
                dtype="int16",
                channels=1,
                callback=audio_callback,
            ):
                silence_frames = 0
                max_silence = 30  # ~3s at 100ms chunks

                while not self._stop_event.is_set():
                    try:
                        data = audio_buffer.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    # Energy gate — skip quiet/noise frames
                    if self._rms(data) < ENERGY_THRESHOLD:
                        silence_frames += 1
                        if self._result and silence_frames > max_silence:
                            break
                        continue

                    # Audio is loud enough — feed to recognizer
                    silence_frames = 0
                    if recognizer.AcceptWaveform(data):
                        text = self._filter_result(json.loads(recognizer.Result()))
                        if text:
                            self._result = (self._result + " " + text) if self._result else text

                # Get final result
                final_text = self._filter_result(json.loads(recognizer.FinalResult()))
                if final_text:
                    self._result = (self._result + " " + final_text) if self._result else final_text

        except Exception as e:
            self._result = f"[STT Error: {e}]"
        finally:
            self._listening = False
