"""
AURA TTS Engine — JARVIS-like voice output.
Primary: pyttsx3 (local SAPI, instant — no network latency)
Uses a persistent pyttsx3 engine on a dedicated thread (COM-safe).
"""

import queue
import re
import threading


# ── text sanitisation ────────────────────────────────────────────────────────

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_EMPH_RE = re.compile(r"(\*\*|__|\*|_|~~)")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s*", re.MULTILINE)
_LIST_BULLET_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "]+",
    flags=re.UNICODE,
)
_MULTI_WS_RE = re.compile(r"\s+")


def _sanitize(text: str) -> str:
    """Strip markdown and symbols that SAPI would pronounce literally."""
    text = _CODE_FENCE_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _URL_RE.sub(" ", text)
    text = _HEADING_RE.sub("", text)
    text = _LIST_BULLET_RE.sub("", text)
    text = _MD_EMPH_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    return _MULTI_WS_RE.sub(" ", text).strip()


# ── sentence splitter that tolerates abbreviations and decimals ──────────────

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt",
    "vs", "etc", "e.g", "i.e", "eg", "ie", "fig", "no",
    "inc", "ltd", "co", "corp", "vol", "pg",
}

# A sentence boundary is [.!?]+ followed by whitespace and an uppercase letter
# or end of buffer. We reject the boundary if the word ending at the dot looks
# like an abbreviation, or if it sits between two digits (e.g. 3.14).
_BOUNDARY_RE = re.compile(
    r"""
    (?P<word>[A-Za-z0-9.]*?)      # preceding word-ish token
    (?P<end>[.!?]+)               # terminator
    (?P<tail>["')\]]*)            # optional closers
    (?P<ws>\s+)                   # whitespace gap
    (?=[A-Z0-9"'(\[])             # next sentence starts with capital/digit/quote
    """,
    re.VERBOSE,
)


def _find_sentence_end(buffer: str) -> int:
    """Return index just past the first real sentence terminator, or -1."""
    for m in _BOUNDARY_RE.finditer(buffer):
        word = m.group("word").lower().rstrip(".")
        end = m.group("end")
        start = m.start("end")

        # Skip decimals: digit.digit
        if (end == "."
                and start > 0 and buffer[start - 1].isdigit()
                and m.end("end") < len(buffer)
                and buffer[m.end("end")].isdigit()):
            continue

        # Skip known abbreviations
        if end == "." and word in _ABBREVIATIONS:
            continue

        # Skip single-letter initials (e.g. "J. K. Rowling")
        if end == "." and len(word) == 1 and word.isalpha():
            continue

        return m.end("end") + len(m.group("tail"))
    return -1


# ── engine ───────────────────────────────────────────────────────────────────

class TTSEngine:
    """Sentence-buffered text-to-speech with background playback."""

    def __init__(self, voice: str = "en-US-GuyNeural", rate: str = "+25%"):
        self.voice = voice
        self.rate = rate
        self.enabled = True
        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._ready = threading.Event()

        self._worker = threading.Thread(target=self._playback_loop, daemon=True)
        self._worker.start()
        self._ready.wait(timeout=5)

    def speak(self, text: str):
        """Queue a text string for TTS playback."""
        if not self.enabled:
            return
        cleaned = _sanitize(text)
        if not cleaned:
            return
        self._queue.put(cleaned)

    def speak_streamed(self, token_iter):
        """Accept a token iterator, buffer by sentence, and queue each sentence."""
        buffer = ""
        for token in token_iter:
            buffer += token
            while True:
                idx = _find_sentence_end(buffer)
                if idx == -1:
                    # Safety: flush on hard newlines even without capital follow-up
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
        """Stop current playback and clear the queue."""
        self._stop_event.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._stop_event.clear()

    def toggle(self) -> bool:
        """Toggle TTS on/off. Returns new state."""
        self.enabled = not self.enabled
        if not self.enabled:
            self.stop()
        return self.enabled

    def _playback_loop(self):
        """Background worker — owns the pyttsx3 engine (COM stays on this thread)."""
        # CRITICAL: SAPI is COM-based. Every thread that talks to it MUST
        # initialise COM, or engine.say() silently produces no audio.
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception as e:
            print(f"[TTS] CoInitialize failed: {e}")

        import pyttsx3
        import time

        def _build_engine():
            e = pyttsx3.init()
            e.setProperty("rate", 175)
            e.setProperty("volume", 1.0)
            for v in e.getProperty("voices"):
                if "david" in v.name.lower() or "male" in v.name.lower():
                    e.setProperty("voice", v.id)
                    break
            return e

        try:
            engine = _build_engine()
        except Exception as e:
            print(f"[TTS] pyttsx3.init failed: {e}")
            self._ready.set()
            return

        self._ready.set()

        # pyttsx3's SAPI driver has a known bug: after the first runAndWait()
        # completes, subsequent say()+runAndWait() calls occasionally no-op
        # because the internal event-loop state is left stale. The reliable
        # pattern is non-blocking startLoop + manual iterate() per utterance,
        # with a fresh engine rebuild if iterate() ever throws.
        while True:
            text = self._queue.get()
            if self._stop_event.is_set():
                continue
            try:
                engine.say(text)
                engine.startLoop(False)
                # Pump the driver until this utterance finishes or is stopped.
                while engine.isBusy():
                    if self._stop_event.is_set():
                        break
                    engine.iterate()
                    time.sleep(0.01)
                engine.endLoop()
            except Exception as e:
                print(f"[TTS] playback error: {e} — rebuilding engine")
                try:
                    engine = _build_engine()
                except Exception as e2:
                    print(f"[TTS] rebuild failed: {e2}")