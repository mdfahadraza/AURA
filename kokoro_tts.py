"""
AURA Kokoro TTS — neural offline TTS using hexgrad/Kokoro-82M.
Runs on CUDA when available. Sentence-buffered, identical public API to
tts_engine.TTSEngine so server.py can swap between them at runtime.
"""

import os
import queue
import threading

# Reuse the proven sanitiser + sentence splitter from the SAPI engine.
from tts_engine import _sanitize, _find_sentence_end


KOKORO_DIR = "D:/AURA/models/kokoro"
SAMPLE_RATE = 24000  # Kokoro outputs 24 kHz mono


class KokoroTTS:
    """Sentence-buffered Kokoro TTS with background synthesis + playback."""

    def __init__(self, voice: str = "am_michael", speed: float = 1.0):
        self.voice = voice
        self.speed = speed
        self.enabled = True

        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._current_stream = None  # active sounddevice OutputStream, if any

        self._worker = threading.Thread(target=self._playback_loop, daemon=True)
        self._worker.start()

    # ── public API (mirrors TTSEngine) ──────────────────────────────────────

    def speak(self, text: str):
        if not self.enabled:
            return
        cleaned = _sanitize(text)
        if cleaned:
            self._queue.put(cleaned)

    def speak_streamed(self, token_iter):
        """Buffer tokens by sentence; queue each sentence as it completes."""
        buffer = ""
        for token in token_iter:
            buffer += token
            while True:
                idx = _find_sentence_end(buffer)
                if idx == -1:
                    nl = buffer.find("\n\n")
                    if nl != -1:
                        sentence = buffer[:nl].strip()
                        buffer = buffer[nl + 2:]
                        if sentence:
                            self.speak(sentence)
                        continue
                    break
                sentence = buffer[:idx].strip()
                buffer = buffer[idx:].lstrip()
                if sentence:
                    self.speak(sentence)
            yield token
        if buffer.strip():
            self.speak(buffer.strip())

    def stop(self):
        """Cancel queued sentences and abort the currently playing audio."""
        self._stop_event.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        # Abort any in-flight sounddevice stream.
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        self._stop_event.clear()

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        if not self.enabled:
            self.stop()
        return self.enabled

    # ── worker ──────────────────────────────────────────────────────────────

    def _playback_loop(self):
        """Owns the model and the audio output stream on a single thread."""
        try:
            import torch
            from kokoro import KModel, KPipeline

            device = "cuda" if torch.cuda.is_available() else "cpu"
            cfg = os.path.join(KOKORO_DIR, "config.json")
            weights = os.path.join(KOKORO_DIR, "kokoro-v1_0.pth")

            self._model = KModel(config=cfg, model=weights).to(device).eval()
            self._pipe = KPipeline(lang_code="a", model=self._model, device=device)
            self._voice_tensor = torch.load(
                os.path.join(KOKORO_DIR, "voices", f"{self.voice}.pt"),
                weights_only=True,
            )
            self._device = device
            print(f"[Kokoro] loaded on {device}, voice={self.voice}")
        except Exception as e:
            print(f"[Kokoro] init failed: {e}")
            self.enabled = False
            self._ready.set()
            return

        self._ready.set()

        import sounddevice as sd
        import numpy as np

        while True:
            text = self._queue.get()
            if self._stop_event.is_set():
                continue
            try:
                # Kokoro's pipeline yields (graphemes, phonemes, audio) per chunk.
                gen = self._pipe(text, voice=self._voice_tensor, speed=self.speed)
                for _, _, audio in gen:
                    if self._stop_event.is_set():
                        break
                    arr = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
                    arr = arr.astype("float32", copy=False)
                    sd.play(arr, samplerate=SAMPLE_RATE, blocking=False)
                    sd.wait()
            except Exception as e:
                print(f"[Kokoro] synth/playback error: {e}")
