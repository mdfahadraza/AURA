"""
AURA Desktop Chat (thin client)
pywebview frontend with voice I/O, OS commands, connected to persistent server.
"""

import json
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
import webview

SERVER = "http://127.0.0.1:8340"


# ── Backend API exposed to JS ───────────────────────────────────────────────

class AuraAPI:
    """Python <-> JS bridge. Every public method is callable from window.pywebview.api.*"""

    def __init__(self):
        self._window = None
        self._streaming = False

    def init_backend(self):
        """Check if server is reachable, then signal ready."""
        def _check():
            for _ in range(60):
                try:
                    urllib.request.urlopen(f"{SERVER}/health", timeout=2)
                    # Fetch TTS status
                    try:
                        with urllib.request.urlopen(f"{SERVER}/tts/status", timeout=2) as r:
                            data = json.loads(r.read())
                            self._push("tts_state", "on" if data.get("enabled") else "off")
                    except Exception:
                        pass
                    self._push("ready", "")
                    return
                except (urllib.error.URLError, OSError):
                    self._push("status", "Waiting for AURA server...")
                    time.sleep(1)
            self._push("error", "Cannot reach AURA server at " + SERVER + ". Run: python server.py")

        threading.Thread(target=_check, daemon=True).start()
        return "loading"

    def send_message(self, text: str):
        """Stream a response from the server."""
        if self._streaming:
            return
        text = text.strip()
        if not text:
            return

        self._streaming = True

        def _generate():
            try:
                self._push("stream_start", "")
                url = f"{SERVER}/think/stream?q={urllib.parse.quote(text)}"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=120) as resp:
                    while True:
                        chunk = resp.read(4)
                        if not chunk:
                            break
                        token = chunk.decode("utf-8", errors="replace")
                        self._push("token", token)
                self._push("stream_end", "")
            except Exception as e:
                self._push("error", str(e))
            finally:
                self._streaming = False

        threading.Thread(target=_generate, daemon=True).start()

    def get_memory_info(self):
        """Fetch memory stats from server."""
        try:
            with urllib.request.urlopen(f"{SERVER}/memory", timeout=5) as resp:
                return resp.read().decode("utf-8")
        except Exception:
            return json.dumps({})

    def toggle_tts(self):
        """Toggle TTS on/off on the server."""
        def _toggle():
            try:
                req = urllib.request.Request(f"{SERVER}/tts/toggle", method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    self._push("tts_state", "on" if data.get("enabled") else "off")
            except Exception:
                pass
        threading.Thread(target=_toggle, daemon=True).start()

    def stop_tts(self):
        """Stop current TTS playback."""
        def _stop():
            try:
                req = urllib.request.Request(f"{SERVER}/tts/stop", method="POST")
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass
        threading.Thread(target=_stop, daemon=True).start()

    def start_listening(self):
        """Start STT on the server."""
        def _listen():
            try:
                req = urllib.request.Request(f"{SERVER}/stt/start", method="POST")
                urllib.request.urlopen(req, timeout=5)
                self._push("stt_state", "listening")

                # Poll for result
                while True:
                    time.sleep(0.5)
                    with urllib.request.urlopen(f"{SERVER}/stt/result", timeout=5) as resp:
                        data = json.loads(resp.read())
                        if not data.get("listening"):
                            text = data.get("text", "")
                            if text:
                                self._push("stt_result", text)
                            self._push("stt_state", "idle")
                            return
            except Exception as e:
                self._push("stt_state", "idle")
                self._push("error", f"STT error: {e}")

        threading.Thread(target=_listen, daemon=True).start()

    def stop_listening(self):
        """Stop STT and get the result."""
        def _stop():
            try:
                req = urllib.request.Request(f"{SERVER}/stt/stop", method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                    text = data.get("text", "")
                    if text:
                        self._push("stt_result", text)
                    self._push("stt_state", "idle")
            except Exception:
                self._push("stt_state", "idle")
        threading.Thread(target=_stop, daemon=True).start()

    def _push(self, event: str, data: str):
        if not self._window:
            return
        try:
            safe = json.dumps(data)
            self._window.evaluate_js(f"window.__aura_event('{event}', {safe})")
        except Exception:
            pass


# ── HTML / CSS / JS ─────────────────────────────────────────────────────────

HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AURA</title>
<style>
/* ═══════════════════════════════════════════════════════════════
   AURA Prestige Design System
   ═══════════════════════════════════════════════════════════════ */

*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }

:root {
  --bg-deep:    #04060c;
  --bg-surface: #0a0e18;
  --bg-card:    #0f1422;
  --bg-hover:   #141a2e;
  --border:     #1a2038;
  --border-l:   #242c48;
  --text:       #e8ecf4;
  --text-dim:   #8892a8;
  --text-muted: #4a5268;
  --accent:     #818cf8;
  --accent-dim: #6366f1;
  --accent-glow:rgba(129,140,248,.12);
  --green:      #34d399;
  --amber:      #fbbf24;
  --red:        #f87171;
  --radius:     14px;
  --radius-sm:  10px;
  --font: 'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', sans-serif;
  --font-mono: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
}

::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-l); border-radius: 2px; }

body {
  font-family: var(--font);
  background: var(--bg-deep);
  color: var(--text);
  height: 100vh;
  overflow: hidden;
  display: flex;
  -webkit-font-smoothing: antialiased;
}

/* ── Ambient background ─────────────────────────────────────── */
.bg-ambient { position:fixed; inset:0; z-index:0; pointer-events:none; overflow:hidden; }
.bg-gradient { position: absolute; border-radius: 50%; filter: blur(140px); opacity: 0; transition: opacity 2s ease; }
.bg-gradient.visible { opacity: 1; }
.bg-g1 { width:600px; height:600px; background:rgba(99,102,241,.06); top:-200px; left:-100px; }
.bg-g2 { width:500px; height:500px; background:rgba(139,92,246,.05); bottom:-150px; right:-80px; }
.bg-g3 { width:350px; height:350px; background:rgba(79,70,229,.04); top:40%; left:50%; }
.bg-grid-pattern {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(129,140,248,.015) 1px, transparent 1px),
    linear-gradient(90deg, rgba(129,140,248,.015) 1px, transparent 1px);
  background-size: 60px 60px;
}

/* ── Layout ──────────────────────────────────────────────────── */
.sidebar {
  width: 272px; flex-shrink: 0;
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  z-index: 2; position: relative;
  opacity: 0; transform: translateX(-20px);
  transition: opacity .7s ease, transform .7s ease;
}
.sidebar.visible { opacity: 1; transform: translateX(0); }
.main { flex: 1; display: flex; flex-direction: column; z-index: 1; position: relative; background: var(--bg-deep); }

/* ── Sidebar ─────────────────────────────────────────────────── */
.sidebar-header { padding: 32px 28px 24px; border-bottom: 1px solid var(--border); }
.sidebar-brand { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.brand-icon {
  width: 36px; height: 36px; border-radius: 10px;
  background: linear-gradient(135deg, var(--accent-dim), #7c3aed);
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 800; color: #fff;
  letter-spacing: 1px;
  box-shadow: 0 4px 16px rgba(99,102,241,.25);
}
.brand-text {
  font-size: 22px; font-weight: 800; letter-spacing: 0.5px;
  background: linear-gradient(135deg, #f1f5f9, var(--accent));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.brand-sub { font-size: 11px; color: var(--text-muted); letter-spacing: 2px; text-transform: uppercase; font-weight: 600; padding-left: 48px; }

.status-panel { padding: 24px 20px; flex: 1; overflow-y: auto; }
.status-label { font-size: 10px; font-weight: 700; letter-spacing: 2.5px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 16px; padding-left: 4px; }
.status-card {
  padding: 14px 16px; background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-sm);
  margin-bottom: 10px; display: flex; align-items: center; gap: 14px; font-size: 13px;
  opacity: 0; transform: translateY(8px); transition: opacity .4s ease, transform .4s ease, background .2s ease, border-color .2s ease;
}
.status-card.visible { opacity: 1; transform: translateY(0); }
.status-card:hover { background: var(--bg-hover); border-color: var(--border-l); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--text-muted); transition: background .4s, box-shadow .4s; }
.status-dot.active { background: var(--green); box-shadow: 0 0 8px rgba(52,211,153,.5); }
.status-dot.recording { background: var(--red); box-shadow: 0 0 8px rgba(248,113,113,.5); animation: dot-pulse 1.5s ease-in-out infinite; }
@keyframes dot-pulse { 0%,100% { box-shadow: 0 0 4px rgba(248,113,113,.3); } 50% { box-shadow: 0 0 12px rgba(248,113,113,.6); } }
.status-info { flex: 1; }
.status-name { color: var(--text); font-weight: 600; font-size: 13px; }
.status-state { color: var(--text-muted); font-size: 11px; margin-top: 2px; transition: color .3s; }
.status-state.on { color: var(--green); }
.status-state.recording { color: var(--red); }

.sidebar-footer { padding: 16px 24px; border-top: 1px solid var(--border); display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-muted); }
.footer-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-muted); transition: background .4s, box-shadow .4s; }
.footer-dot.live { background: var(--green); box-shadow: 0 0 6px rgba(52,211,153,.5); }

/* ── Chat header ─────────────────────────────────────────────── */
.chat-header {
  padding: 18px 36px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 14px;
  background: rgba(4,6,12,.85); backdrop-filter: blur(16px);
  opacity: 0; transform: translateY(-10px); transition: opacity .5s ease, transform .5s ease;
}
.chat-header.visible { opacity: 1; transform: translateY(0); }
.header-avatar {
  width: 34px; height: 34px; border-radius: 10px;
  background: linear-gradient(135deg, var(--accent-dim), #7c3aed);
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 800; color: #fff; letter-spacing: 0.5px;
}
.header-info { flex: 1; }
.header-name { font-size: 14px; font-weight: 700; color: var(--text); }
.header-status { font-size: 11px; color: var(--text-muted); transition: color .3s; }
.header-status.online { color: var(--green); }
.header-actions { display: flex; gap: 8px; }
.header-btn {
  width: 34px; height: 34px; border-radius: 8px;
  background: var(--bg-card); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; transition: background .2s, border-color .2s, color .2s;
  color: var(--text-dim);
}
.header-btn:hover { background: var(--bg-hover); border-color: var(--border-l); }
.header-btn svg { width: 16px; height: 16px; fill: currentColor; }
.header-btn.active { background: var(--accent-dim); border-color: var(--accent); color: #fff; }
.header-btn.active:hover { background: var(--accent); }

/* ── Messages ────────────────────────────────────────────────── */
.messages { flex: 1; overflow-y: auto; padding: 32px 36px; display: flex; flex-direction: column; gap: 6px; }
.msg-group { display: flex; flex-direction: column; gap: 2px; margin-bottom: 12px; }
.msg {
  max-width: 70%; padding: 14px 20px; font-size: 14px; line-height: 1.65; word-wrap: break-word;
  opacity: 0; transform: translateY(12px); transition: opacity .35s ease, transform .35s ease;
}
.msg.visible { opacity: 1; transform: translateY(0); }
.msg.user {
  align-self: flex-end; background: linear-gradient(135deg, #6366f1, #7c3aed);
  color: #fff; border-radius: 20px 20px 8px 20px; box-shadow: 0 2px 12px rgba(99,102,241,.2);
}
.msg.aura {
  align-self: flex-start; background: var(--bg-card); border: 1px solid var(--border);
  color: var(--text); border-radius: 20px 20px 20px 8px;
}
.msg.aura .cursor { display: inline-block; width: 2px; height: 15px; background: var(--accent); margin-left: 2px; vertical-align: text-bottom; animation: blink .7s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }
.msg code { font-family: var(--font-mono); font-size: 12.5px; background: rgba(129,140,248,.08); padding: 2px 6px; border-radius: 4px; color: var(--accent); }
.msg pre { background: var(--bg-deep); border: 1px solid var(--border); border-radius: 8px; padding: 14px 18px; margin: 10px 0 6px; overflow-x: auto; font-family: var(--font-mono); font-size: 12.5px; line-height: 1.6; color: var(--text-dim); }
.msg.system { align-self: center; max-width: 90%; background: transparent; color: var(--text-muted); font-size: 12px; text-align: center; padding: 10px 20px; border-radius: 8px; }

/* Command result styling */
.msg.aura.command { border-color: rgba(52,211,153,.3); background: rgba(52,211,153,.04); }

.msg-time { font-size: 10px; color: var(--text-muted); padding: 0 8px; margin-top: 4px; opacity: 0; transition: opacity .2s; }
.msg-group:hover .msg-time { opacity: 1; }
.msg-group.user-group .msg-time { text-align: right; }

/* ── Typing indicator ────────────────────────────────────────── */
.typing-indicator {
  align-self: flex-start; display: none; padding: 16px 22px;
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 20px 20px 20px 8px;
  gap: 6px; align-items: center; margin-bottom: 12px;
}
.typing-indicator.visible { display: flex; }
.typing-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); opacity: .4; }

/* ── Input bar ───────────────────────────────────────────────── */
.input-bar {
  padding: 16px 36px 24px; background: rgba(4,6,12,.9); backdrop-filter: blur(16px);
  border-top: 1px solid var(--border); display: flex; gap: 12px; align-items: flex-end;
  opacity: 0; transform: translateY(10px); transition: opacity .5s ease, transform .5s ease;
}
.input-bar.visible { opacity: 1; transform: translateY(0); }
.input-wrapper { flex: 1; position: relative; }
.input-wrapper textarea {
  width: 100%; background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 14px 20px; font-size: 14px; font-family: var(--font); color: var(--text); outline: none;
  resize: none; min-height: 48px; max-height: 160px; line-height: 1.5;
  transition: border-color .3s, box-shadow .3s;
}
.input-wrapper textarea::placeholder { color: var(--text-muted); }
.input-wrapper textarea:focus { border-color: var(--accent-dim); box-shadow: 0 0 0 3px var(--accent-glow); }
.input-wrapper textarea:disabled { opacity: .4; }

/* Mic button */
.mic-btn {
  width: 48px; height: 48px; border: none; border-radius: var(--radius);
  background: var(--bg-card); border: 1px solid var(--border);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: transform .15s ease, background .2s, border-color .2s; flex-shrink: 0;
  color: var(--text-dim);
}
.mic-btn:hover { background: var(--bg-hover); border-color: var(--border-l); }
.mic-btn svg { width: 20px; height: 20px; fill: currentColor; }
.mic-btn.recording {
  background: rgba(248,113,113,.15); border-color: var(--red); color: var(--red);
  animation: mic-pulse 1.5s ease-in-out infinite;
}
@keyframes mic-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(248,113,113,.3); } 50% { box-shadow: 0 0 0 10px rgba(248,113,113,0); } }

.send-btn {
  width: 48px; height: 48px;
  background: linear-gradient(135deg, var(--accent-dim), #7c3aed);
  border: none; border-radius: var(--radius); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: transform .15s ease, box-shadow .2s ease, opacity .2s; flex-shrink: 0;
  box-shadow: 0 2px 12px rgba(99,102,241,.25);
}
.send-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 20px rgba(99,102,241,.35); }
.send-btn:active:not(:disabled) { transform: translateY(0) scale(.97); }
.send-btn:disabled { opacity: .3; cursor: default; transform: none; box-shadow: none; }
.send-btn svg { width: 20px; height: 20px; fill: #fff; }

/* ── Loading overlay ─────────────────────────────────────────── */
.loading-overlay {
  position: fixed; inset: 0; z-index: 100; background: var(--bg-deep);
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 28px;
  transition: opacity .8s ease;
}
.loading-overlay.hidden { opacity: 0; pointer-events: none; }
.loader-brand { font-size: 36px; font-weight: 800; background: linear-gradient(135deg, #f1f5f9, var(--accent), #a855f7); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: 1px; }
.loader-sub { font-size: 12px; color: var(--text-muted); letter-spacing: 4px; text-transform: uppercase; margin-top: -20px; }
.loader-spinner { width: 48px; height: 48px; position: relative; }
.loader-spinner::before, .loader-spinner::after { content: ''; position: absolute; inset: 0; border-radius: 50%; border: 2px solid transparent; }
.loader-spinner::before { border-top-color: var(--accent); animation: spin 1s linear infinite; }
.loader-spinner::after { border-bottom-color: #7c3aed; animation: spin 1.5s linear infinite reverse; inset: 4px; }
@keyframes spin { to { transform: rotate(360deg); } }
.loader-status { font-size: 13px; color: var(--text-dim); text-align: center; max-width: 320px; line-height: 1.5; }
</style>
</head>
<body>

<!-- Background -->
<div class="bg-ambient">
  <div class="bg-gradient bg-g1"></div>
  <div class="bg-gradient bg-g2"></div>
  <div class="bg-gradient bg-g3"></div>
  <div class="bg-grid-pattern"></div>
</div>

<!-- Loading overlay -->
<div class="loading-overlay" id="loadingOverlay">
  <div class="loader-brand">AURA</div>
  <div class="loader-sub">Autonomous Universal Reasoning Agent</div>
  <div class="loader-spinner"></div>
  <div class="loader-status" id="loaderStatus">Connecting to server...</div>
</div>

<!-- Sidebar -->
<div class="sidebar" id="sidebar">
  <div class="sidebar-header">
    <div class="sidebar-brand">
      <div class="brand-icon">A</div>
      <div class="brand-text">AURA</div>
    </div>
    <div class="brand-sub">Autonomous Universal Reasoning Agent</div>
  </div>

  <div class="status-panel">
    <div class="status-label">Active Systems</div>

    <div class="status-card" id="statusServer">
      <div class="status-dot" id="dotServer"></div>
      <div class="status-info">
        <div class="status-name">Server</div>
        <div class="status-state" id="stateServer">Connecting...</div>
      </div>
    </div>

    <div class="status-card" id="statusTts">
      <div class="status-dot" id="dotTts"></div>
      <div class="status-info">
        <div class="status-name">Text-to-Speech</div>
        <div class="status-state" id="stateTts">Off</div>
      </div>
    </div>

    <div class="status-card" id="statusStt">
      <div class="status-dot" id="dotStt"></div>
      <div class="status-info">
        <div class="status-name">Speech-to-Text</div>
        <div class="status-state" id="stateStt">Idle</div>
      </div>
    </div>

    <div class="status-card" id="statusOs">
      <div class="status-dot active" id="dotOs"></div>
      <div class="status-info">
        <div class="status-name">OS Commands</div>
        <div class="status-state on" id="stateOs">Active</div>
      </div>
    </div>
  </div>

  <div class="sidebar-footer">
    <div class="footer-dot" id="footerDot"></div>
    <span id="footerLabel">Qwen 2.5-7B &bull; Local inference</span>
  </div>
</div>

<!-- Main chat -->
<div class="main">
  <div class="chat-header" id="chatHeader">
    <div class="header-avatar">A</div>
    <div class="header-info">
      <div class="header-name">AURA</div>
      <div class="header-status" id="headerStatus">Connecting...</div>
    </div>
    <div class="header-actions">
      <button class="header-btn" id="ttsBtn" title="Toggle voice">
        <svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
      </button>
      <button class="header-btn" id="clearBtn" title="Clear chat">
        <svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
      </button>
    </div>
  </div>

  <div class="messages" id="messages"></div>

  <div class="typing-indicator" id="typingIndicator">
    <div class="typing-dot" id="td1"></div>
    <div class="typing-dot" id="td2"></div>
    <div class="typing-dot" id="td3"></div>
  </div>

  <div class="input-bar" id="inputBar">
    <div class="input-wrapper">
      <textarea id="userInput" placeholder="Ask AURA anything... or give a command" disabled rows="1" autocomplete="off"></textarea>
    </div>
    <button class="mic-btn" id="micBtn" title="Voice input" disabled>
      <svg viewBox="0 0 24 24"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg>
    </button>
    <button class="send-btn" id="sendBtn" disabled>
      <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
    </button>
  </div>
</div>

<script>
// ═══════════════════════════════════════════════════════════════
//  Utility
// ═══════════════════════════════════════════════════════════════
const $ = id => document.getElementById(id);
const esc = t => t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

function formatTime() {
  const d = new Date();
  return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
}

function renderMarkdown(text) {
  text = text.replace(/```([\s\S]*?)```/g, (_, code) => '<pre>' + esc(code.trim()) + '</pre>');
  text = text.replace(/`([^`]+)`/g, (_, code) => '<code>' + esc(code) + '</code>');
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
  text = text.replace(/\n/g, '<br>');
  return text;
}

// ═══════════════════════════════════════════════════════════════
//  State
// ═══════════════════════════════════════════════════════════════
let currentAuraBubble = null;
let currentAuraRaw = '';
let isStreaming = false;
let typingAnim = null;
let ttsEnabled = true;
let isRecording = false;

const $msgs     = $('messages');
const $input    = $('userInput');
const $sendBtn  = $('sendBtn');
const $micBtn   = $('micBtn');
const $ttsBtn   = $('ttsBtn');
const $overlay  = $('loadingOverlay');
const $loaderSt = $('loaderStatus');
const $headerSt = $('headerStatus');
const $typing   = $('typingIndicator');

// ═══════════════════════════════════════════════════════════════
//  Ambient gradients fade-in
// ═══════════════════════════════════════════════════════════════
setTimeout(() => {
  document.querySelectorAll('.bg-gradient').forEach((el, i) => {
    setTimeout(() => el.classList.add('visible'), i * 400);
  });
}, 200);

// ═══════════════════════════════════════════════════════════════
//  Auto-resize textarea
// ═══════════════════════════════════════════════════════════════
$input.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 160) + 'px';
});

// ═══════════════════════════════════════════════════════════════
//  Typing indicator animation
// ═══════════════════════════════════════════════════════════════
function startTypingAnim() {
  const dots = [$('td1'), $('td2'), $('td3')];
  let frame = 0;
  typingAnim = setInterval(() => {
    dots.forEach((d, i) => {
      const active = (frame % 3) === i;
      d.style.opacity = active ? '1' : '.4';
      d.style.transform = active ? 'scale(1.2)' : 'scale(1)';
      d.style.transition = 'opacity .25s, transform .25s';
    });
    frame++;
  }, 350);
}
function stopTypingAnim() {
  if (typingAnim) { clearInterval(typingAnim); typingAnim = null; }
}

// ═══════════════════════════════════════════════════════════════
//  Event bridge from Python
// ═══════════════════════════════════════════════════════════════
window.__aura_event = function(event, data) {
  switch(event) {

    case 'status':
      $loaderSt.textContent = data;
      break;

    case 'ready':
      $overlay.classList.add('hidden');
      setTimeout(() => $overlay.style.display = 'none', 800);
      $input.disabled = false;
      $sendBtn.disabled = false;
      $micBtn.disabled = false;
      $input.focus();
      $headerSt.textContent = 'Online — Voice Active';
      $headerSt.classList.add('online');
      $('footerDot').classList.add('live');
      $('dotServer').classList.add('active');
      $('stateServer').textContent = 'Online';
      $('stateServer').classList.add('on');
      $('sidebar').classList.add('visible');
      setTimeout(() => $('chatHeader').classList.add('visible'), 100);
      setTimeout(() => $('inputBar').classList.add('visible'), 200);
      document.querySelectorAll('.status-card').forEach((el, i) => {
        setTimeout(() => el.classList.add('visible'), 400 + i * 80);
      });
      addSystemMsg('AURA is online. Voice and OS commands are active. Try "open chrome" or click the mic.');
      break;

    case 'error':
      addSystemMsg('Error: ' + data);
      $headerSt.textContent = 'Error';
      $headerSt.classList.remove('online');
      isStreaming = false;
      setInputEnabled(true);
      break;

    case 'stream_start':
      $typing.classList.remove('visible');
      stopTypingAnim();
      currentAuraRaw = '';
      currentAuraBubble = addAuraBubble();
      break;

    case 'token':
      if (currentAuraBubble) {
        currentAuraRaw += data;
        currentAuraBubble.innerHTML = renderMarkdown(esc(currentAuraRaw)) + '<span class="cursor"></span>';
        scrollToBottom();
      }
      break;

    case 'stream_end':
      if (currentAuraBubble) {
        currentAuraBubble.innerHTML = renderMarkdown(esc(currentAuraRaw));
        const timeEl = currentAuraBubble.parentElement.querySelector('.msg-time');
        if (timeEl) timeEl.textContent = formatTime();
      }
      currentAuraBubble = null;
      currentAuraRaw = '';
      isStreaming = false;
      setInputEnabled(true);
      $input.focus();
      refreshMemory();
      break;

    case 'tts_state':
      ttsEnabled = (data === 'on');
      $ttsBtn.classList.toggle('active', ttsEnabled);
      $('dotTts').classList.toggle('active', ttsEnabled);
      $('stateTts').textContent = ttsEnabled ? 'Enabled' : 'Off';
      $('stateTts').classList.toggle('on', ttsEnabled);
      break;

    case 'stt_state':
      if (data === 'listening') {
        isRecording = true;
        $micBtn.classList.add('recording');
        $('dotStt').classList.remove('active');
        $('dotStt').classList.add('recording');
        $('stateStt').textContent = 'Listening...';
        $('stateStt').className = 'status-state recording';
      } else {
        isRecording = false;
        $micBtn.classList.remove('recording');
        $('dotStt').classList.remove('recording');
        $('dotStt').classList.remove('active');
        $('stateStt').textContent = 'Idle';
        $('stateStt').className = 'status-state';
      }
      break;

    case 'stt_result':
      $input.value = data;
      $input.style.height = 'auto';
      $input.style.height = Math.min($input.scrollHeight, 160) + 'px';
      // Auto-send voice input
      setTimeout(() => sendMessage(), 200);
      break;
  }
};

// ═══════════════════════════════════════════════════════════════
//  Chat helpers
// ═══════════════════════════════════════════════════════════════
function scrollToBottom() { $msgs.scrollTop = $msgs.scrollHeight; }

function addUserBubble(text) {
  const group = document.createElement('div');
  group.className = 'msg-group user-group';
  const el = document.createElement('div');
  el.className = 'msg user';
  el.textContent = text;
  group.appendChild(el);
  const time = document.createElement('div');
  time.className = 'msg-time';
  time.textContent = formatTime();
  group.appendChild(time);
  $msgs.appendChild(group);
  requestAnimationFrame(() => el.classList.add('visible'));
  scrollToBottom();
}

function addAuraBubble() {
  const group = document.createElement('div');
  group.className = 'msg-group';
  const el = document.createElement('div');
  el.className = 'msg aura';
  el.innerHTML = '<span class="cursor"></span>';
  group.appendChild(el);
  const time = document.createElement('div');
  time.className = 'msg-time';
  time.textContent = '';
  group.appendChild(time);
  $msgs.appendChild(group);
  requestAnimationFrame(() => el.classList.add('visible'));
  scrollToBottom();
  return el;
}

function addSystemMsg(text) {
  const el = document.createElement('div');
  el.className = 'msg system';
  el.textContent = text;
  $msgs.appendChild(el);
  requestAnimationFrame(() => { el.style.opacity = '0.7'; });
  scrollToBottom();
}

function showTyping() {
  $typing.classList.add('visible');
  startTypingAnim();
  scrollToBottom();
}

function setInputEnabled(v) {
  $input.disabled = !v;
  $sendBtn.disabled = !v;
  $micBtn.disabled = !v;
}

// ═══════════════════════════════════════════════════════════════
//  (Memory refresh removed — sidebar now shows system status)
// ═══════════════════════════════════════════════════════════════
function refreshMemory() { /* no-op — kept for compatibility */ }

// ═══════════════════════════════════════════════════════════════
//  Send logic
// ═══════════════════════════════════════════════════════════════
function sendMessage() {
  const text = $input.value.trim();
  if (!text || isStreaming) return;
  $input.value = '';
  $input.style.height = 'auto';
  isStreaming = true;
  setInputEnabled(false);
  addUserBubble(text);
  showTyping();
  window.pywebview.api.send_message(text);
}

$sendBtn.addEventListener('click', sendMessage);
$input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

// ═══════════════════════════════════════════════════════════════
//  TTS toggle
// ═══════════════════════════════════════════════════════════════
$ttsBtn.addEventListener('click', () => {
  window.pywebview.api.toggle_tts();
});

// ═══════════════════════════════════════════════════════════════
//  Mic button (STT)
// ═══════════════════════════════════════════════════════════════
$micBtn.addEventListener('click', () => {
  if (isStreaming) return;
  if (isRecording) {
    window.pywebview.api.stop_listening();
  } else {
    window.pywebview.api.start_listening();
  }
});

// Clear chat
$('clearBtn').addEventListener('click', () => {
  if (isStreaming) return;
  $msgs.innerHTML = '';
  addSystemMsg('Chat cleared. Memory preserved.');
  window.pywebview.api.stop_tts();
});

// ═══════════════════════════════════════════════════════════════
//  Boot
// ═══════════════════════════════════════════════════════════════
window.addEventListener('pywebviewready', function() {
  window.pywebview.api.init_backend();
});
</script>
</body>
</html>
"""


# ── Launch ──────────────────────────────────────────────────────────────────

def main():
    api = AuraAPI()

    window = webview.create_window(
        title="AURA Interface",
        html=HTML,
        width=1140,
        height=760,
        min_size=(800, 520),
        background_color="#0f235e",
        js_api=api,
    )
    api._window = window

    webview.start()


if __name__ == "__main__":
    main()
