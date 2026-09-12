"""
AURA — Persistent JARVIS-style server.
Run once, keeps model in memory. GUI connects to this.

Usage:  python server.py
"""

import os
import threading
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, JSONResponse
from reasoning_engine import ReasoningEngine
from short_term import ShortTermMemory
from long_term_vector import LongTermMemory, is_storable_fact
from os_commander import OSCommander
from tts_engine import TTSEngine
from stt_engine import STTEngine
from sound_effects import SoundEffects

app = FastAPI(title="AURA API")

# ── Load core models ─────────────────────────────────────────────────────────
print("[AURA Server] Starting up — loading models...")
brain = ReasoningEngine()

stm = ShortTermMemory()
commander = OSCommander()
stt = STTEngine()
sfx = SoundEffects()

# ── TTS engine selector ──────────────────────────────────────────────────────
# AURA_TTS=sapi   → pyttsx3 (instant, robotic, local SAPI)
# AURA_TTS=kokoro → neural Kokoro-82M on GPU (higher quality, ~0.5–1s latency)
TTS_BACKEND = os.environ.get("AURA_TTS", "kokoro").lower()


def _build_tts(backend: str):
    if backend == "kokoro":
        from kokoro_tts import KokoroTTS
        engine = KokoroTTS()
        engine._ready.wait(timeout=30)
        return engine
    return TTSEngine()


tts = _build_tts(TTS_BACKEND)
print(f"[AURA Server] TTS backend: {TTS_BACKEND}")

# Load LTM in background
ltm = None

def _load_ltm():
    global ltm
    ltm = LongTermMemory()
    print("[AURA Server] Long-term memory ready.")

threading.Thread(target=_load_ltm, daemon=True).start()


# Warm up the Vosk model in the background so the first /stt/start doesn't
# block on a 2.6 GB model load (the GUI's HTTP timeout is 5 s).
def _warmup_stt():
    try:
        stt._ensure_model()
        print("[AURA Server] STT model warmed up.")
    except Exception as e:
        print(f"[AURA Server] STT warmup failed: {e}")

threading.Thread(target=_warmup_stt, daemon=True).start()

print("[AURA Server] Ready — listening for requests.")


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Think (with OS command interception) ─────────────────────────────────────

@app.get("/think")
def think(q: str):
    stm.add(q)

    # Check for OS command first
    action, params = commander.detect_intent(q)
    if action:
        result = commander.execute(action, params)
        if tts.enabled:
            # Strip markdown for TTS
            tts.speak(_strip_md(result))
        return {"answer": result, "type": "command"}

    # Normal LLM path
    if ltm and is_storable_fact(q):
        ltm.store(q)
    ltm_ctx = ltm.retrieve(q) if ltm else []

    answer = brain.think(q, stm.get_context(), ltm_ctx, stm.get_facts())
    if tts.enabled:
        tts.speak(_strip_md(answer))
    return {"answer": answer, "type": "llm"}


@app.get("/think/stream")
def think_stream(q: str):
    stm.add(q)

    # Check for OS command first
    action, params = commander.detect_intent(q)
    if action:
        result = commander.execute(action, params)
        if tts.enabled:
            tts.speak(_strip_md(result))
        def gen_cmd():
            yield result
        return StreamingResponse(gen_cmd(), media_type="text/plain")

    # Normal LLM streaming path
    if ltm and is_storable_fact(q):
        ltm.store(q)
    ltm_ctx = ltm.retrieve(q) if ltm else []

    def generate():
        token_iter = brain.think_stream(q, stm.get_context(), ltm_ctx, stm.get_facts())
        if tts.enabled:
            for token in tts.speak_streamed(token_iter):
                yield token
        else:
            for token in token_iter:
                yield token
        # Assistant replies are NEVER written back to LTM — they are model
        # output, not ground truth, and storing them compounds hallucinations.

    return StreamingResponse(generate(), media_type="text/plain")


# ── Memory ───────────────────────────────────────────────────────────────────

@app.get("/memory")
def memory_info():
    facts = stm.get_facts()
    return {
        "stm_count": len(stm.memory),
        "ltm_count": len(ltm.memory) if ltm else 0,
        "user_name": facts.get("name") or "",
        "user_age": facts.get("age") or "",
    }


# ── TTS controls ─────────────────────────────────────────────────────────────

@app.post("/tts/toggle")
def tts_toggle():
    new_state = tts.toggle()
    return {"enabled": new_state}

@app.post("/tts/stop")
def tts_stop():
    tts.stop()
    sfx.play("interrupt")
    return {"status": "stopped"}

@app.post("/sfx/play")
def sfx_play(body: dict):
    """Play a named cue: listen_start, listen_stop, interrupt, ack."""
    name = body.get("name", "")
    sfx.play(name)
    return {"status": "ok", "name": name}

@app.get("/tts/status")
def tts_status():
    return {"enabled": tts.enabled, "backend": TTS_BACKEND, "voice": getattr(tts, "voice", "")}

@app.post("/tts/engine")
def tts_engine_switch(body: dict):
    """Hot-swap TTS engine. body: {"backend": "sapi"|"kokoro"}."""
    global tts, TTS_BACKEND
    backend = body.get("backend", "").lower()
    if backend not in ("sapi", "kokoro"):
        return JSONResponse({"error": "backend must be 'sapi' or 'kokoro'"}, status_code=400)
    if backend == TTS_BACKEND:
        return {"backend": TTS_BACKEND, "status": "unchanged"}
    try:
        old = tts
        new = _build_tts(backend)
        tts = new
        TTS_BACKEND = backend
        try:
            old.stop()
        except Exception:
            pass
        return {"backend": TTS_BACKEND, "status": "switched"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── STT controls ─────────────────────────────────────────────────────────────

@app.post("/stt/start")
def stt_start():
    if tts.enabled:
        tts.stop()  # Stop TTS to avoid echo
    sfx.play("listen_start")
    stt.start_listening()
    return {"status": "listening"}

@app.post("/stt/stop")
def stt_stop():
    text = stt.stop_listening()
    sfx.play("listen_stop")
    return {"text": text}

@app.get("/stt/result")
def stt_result():
    return stt.get_result()


# ── Knowledge Base (ingest / query) ──────────────────────────────────────────

@app.post("/kb/ingest/text")
def kb_ingest_text(body: dict):
    """Ingest raw text into the knowledge base."""
    if not ltm:
        return JSONResponse({"error": "LTM not ready yet"}, status_code=503)
    text = body.get("text", "")
    if not text.strip():
        return {"error": "No text provided", "count": 0}
    count = ltm.ingest_text(text)
    return {"status": "ok", "chunks_added": count, "total": ltm.count()}

@app.post("/kb/ingest/file")
def kb_ingest_file(body: dict):
    """Ingest a file from disk into the knowledge base."""
    if not ltm:
        return JSONResponse({"error": "LTM not ready yet"}, status_code=503)
    filepath = body.get("path", "")
    if not filepath:
        return {"error": "No path provided"}
    try:
        count = ltm.ingest_file(filepath)
        return {"status": "ok", "chunks_added": count, "total": ltm.count()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post("/kb/ingest/folder")
def kb_ingest_folder(body: dict):
    """Ingest all supported files from a folder recursively."""
    if not ltm:
        return JSONResponse({"error": "LTM not ready yet"}, status_code=503)
    folder = body.get("path", "")
    if not folder:
        return {"error": "No path provided"}
    try:
        count = ltm.ingest_folder(folder)
        return {"status": "ok", "chunks_added": count, "total": ltm.count()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post("/kb/query")
def kb_query(body: dict):
    """Search the knowledge base."""
    if not ltm:
        return JSONResponse({"error": "LTM not ready yet"}, status_code=503)
    query = body.get("query", "")
    top_k = body.get("top_k", 5)
    results = ltm.retrieve(query, top_k=top_k)
    return {"results": results, "total_entries": ltm.count()}

@app.get("/kb/stats")
def kb_stats():
    """Get knowledge base statistics."""
    if not ltm:
        return {"status": "loading", "count": 0}
    return {"status": "ready", "count": ltm.count(), "path": "E:/AURA_DATA"}

@app.post("/kb/clear")
def kb_clear():
    """Clear all stored knowledge."""
    if not ltm:
        return JSONResponse({"error": "LTM not ready yet"}, status_code=503)
    ltm.clear()
    return {"status": "cleared", "count": 0}


# ── Settings ─────────────────────────────────────────────────────────────────

@app.get("/settings")
def get_settings():
    return {
        "tts_enabled": tts.enabled,
        "stt_listening": stt.is_listening,
        "tts_voice": tts.voice,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _strip_md(text: str) -> str:
    """Strip markdown formatting for cleaner TTS."""
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"```[\s\S]*?```", "", text)
    return text.strip()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8340)
