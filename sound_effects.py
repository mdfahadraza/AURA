"""
AURA Sound Effects — short synthesized UI cues, fully offline.
Tones are generated in-memory with numpy, played via pygame.mixer.
"""

import numpy as np


DEFAULT_SAMPLE_RATE = 22050


class SoundEffects:
    """Lazy-init pygame.mixer; pre-bake a few short cues."""

    def __init__(self):
        self.enabled = True
        self._sounds = {}
        self._ready = False
        self._sample_rate = DEFAULT_SAMPLE_RATE
        self._channels = 1

    def _ensure_ready(self):
        if self._ready:
            return
        try:
            import pygame
            pygame.mixer.pre_init(frequency=DEFAULT_SAMPLE_RATE, size=-16, channels=1, buffer=512)
            pygame.mixer.init()
            # pre_init hints can be overridden — read what we actually got.
            freq, _size, channels = pygame.mixer.get_init()
            self._sample_rate = freq
            self._channels = channels
            self._sounds = {
                "listen_start": _make_sound(880, 0.10, freq, channels, fade=0.02),
                "listen_stop":  _make_sound(440, 0.08, freq, channels, fade=0.02),
                "interrupt":    _make_sound(220, 0.05, freq, channels, fade=0.01),
                "ack":          _make_chord([523, 659], 0.12, freq, channels, fade=0.02),
            }
            self._ready = True
        except Exception as e:
            print(f"[SFX] init failed: {e}")
            self.enabled = False

    def play(self, name: str):
        if not self.enabled:
            return
        self._ensure_ready()
        snd = self._sounds.get(name)
        if snd is not None:
            try:
                snd.play()
            except Exception as e:
                print(f"[SFX] play '{name}' failed: {e}")


def _tone(freq: float, duration: float, sample_rate: int, fade: float = 0.0) -> np.ndarray:
    n = int(sample_rate * duration)
    t = np.linspace(0, duration, n, endpoint=False, dtype=np.float32)
    wave = np.sin(2 * np.pi * freq * t, dtype=np.float32)
    if fade > 0:
        f = int(sample_rate * fade)
        if f > 0 and 2 * f < n:
            ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)
            wave[:f] *= ramp
            wave[-f:] *= ramp[::-1]
    return wave


def _to_sound(wave: np.ndarray, channels: int):
    import pygame
    pcm = np.clip(wave * 0.4, -1.0, 1.0)
    pcm16 = (pcm * 32767).astype(np.int16)
    if channels > 1:
        # Duplicate the mono signal across all channels.
        pcm16 = np.repeat(pcm16[:, None], channels, axis=1)
        pcm16 = np.ascontiguousarray(pcm16)
    return pygame.sndarray.make_sound(pcm16)


def _make_sound(freq: float, duration: float, sample_rate: int, channels: int, fade: float = 0.0):
    return _to_sound(_tone(freq, duration, sample_rate, fade), channels)


def _make_chord(freqs, duration: float, sample_rate: int, channels: int, fade: float = 0.0):
    mix = sum(_tone(f, duration, sample_rate, fade) for f in freqs) / len(freqs)
    return _to_sound(mix, channels)
