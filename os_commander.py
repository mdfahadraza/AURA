"""
AURA OS Commander — JARVIS-style system control.
Detects user intent and executes OS-level actions.
"""

import os
import re
import subprocess
import urllib.parse
import webbrowser
import ctypes
import psutil
import pyautogui
from datetime import datetime

# ── Audio endpoint (pycaw) ───────────────────────────────────────────────────
# Cached COM interface to the default speaker endpoint. Activating it on every
# call is slow (~50ms) and leaks COM refs under repeated use.
_VOLUME_IFACE = None


def _audio_volume():
    """Return the cached IAudioEndpointVolume on the default speaker."""
    global _VOLUME_IFACE
    if _VOLUME_IFACE is not None:
        return _VOLUME_IFACE
    from pycaw.pycaw import AudioUtilities
    _VOLUME_IFACE = AudioUtilities.GetSpeakers().EndpointVolume
    return _VOLUME_IFACE


# ── App aliases ──────────────────────────────────────────────────────────────

APP_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "browser": "chrome",
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    "cmd": "cmd",
    "command prompt": "cmd",
    "terminal": "cmd",
    "powershell": "powershell",
    "task manager": "taskmgr",
    "paint": "mspaint",
    "word": "winword",
    "excel": "excel",
    "settings": "ms-settings:",
    "control panel": "control",
    "spotify": "spotify",
    "discord": "discord",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "snipping tool": "snippingtool",
    "camera": "microsoft.windows.camera:",
    "clock": "ms-clock:",
    "calendar": "outlookcal:",
    "maps": "bingmaps:",
    "store": "ms-windows-store:",
    "photos": "ms-photos:",
    "mail": "outlookmail:",
    "weather": "bingweather:",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "firefox": "firefox",
    "brave": "brave",
    "telegram": "telegram",
    "whatsapp": "whatsapp",
    "zoom": "zoom",
    "obs": "obs64",
    "steam": "steam",
    "vlc": "vlc",
}

# ── Intent patterns ──────────────────────────────────────────────────────────

_INTENT_PATTERNS = [
    # ── Compound commands (must come FIRST) ─────────────────────────────────
    # "open chrome and search X" / "open browser and google X"
    (r"(?:open|launch|start)\s+(?:chrome|browser|google chrome)\s+(?:and|then)\s+(?:search|google|look up|find)\s+(?:for\s+)?(.+)", "web_search"),
    # "open chrome and go to X" / "open browser and open X.com"
    (r"(?:open|launch|start)\s+(?:chrome|browser|google chrome)\s+(?:and|then)\s+(?:go to|open|visit)\s+(.+)", "open_url"),

    # ── App launch / close ──────────────────────────────────────────────────
    (r"(?:open|launch|start|run)\s+(.+?)(?:\s+(?:and|then)\s+.*)?$", "open_app"),
    (r"(?:close|kill|stop|quit|exit)\s+(.+)",                   "close_app"),
    # System info
    (r"(?:system|pc|computer)\s*(?:info|status|stats|health)",  "system_info"),
    (r"(?:how much|what(?:'s| is))\s+(?:my\s+)?(?:cpu|ram|memory|disk|battery|storage)", "system_info"),
    (r"(?:cpu|ram|memory|battery|disk|storage)\s*(?:usage|status|level|info|percent)", "system_info"),
    # Volume
    (r"(?:set|change)\s+(?:the\s+)?volume\s+(?:to\s+)?(\d+)",  "set_volume"),
    (r"volume\s+(?:up|increase)",                                "volume_up"),
    (r"volume\s+(?:down|decrease|lower)",                        "volume_down"),
    (r"(?:mute|unmute)\s*(?:the\s+)?(?:volume|sound|audio)?",   "mute_toggle"),
    (r"(?:what(?:'s| is))\s+(?:the\s+)?(?:current\s+)?volume",  "get_volume"),
    (r"(?:current\s+)?volume\s+(?:level|status)",                "get_volume"),
    # Screenshot
    (r"(?:take|capture|grab)\s+(?:a\s+)?screenshot",            "screenshot"),
    (r"screenshot",                                              "screenshot"),
    # Web search
    (r"(?:search|google|look up|find)\s+(?:for\s+|the web for\s+|on google\s+)?(.+)", "web_search"),
    # Time/date
    (r"(?:what(?:'s| is))\s+(?:the\s+)?(?:time|date|day)",      "time_date"),
    (r"(?:current|today(?:'s)?)\s+(?:time|date|day)",            "time_date"),
    # Lock/shutdown/restart
    (r"lock\s+(?:my\s+)?(?:computer|pc|screen|system)",          "lock_screen"),
    (r"(?:shutdown|shut down|turn off)\s*(?:my\s+)?(?:computer|pc|system)?", "shutdown"),
    (r"restart\s*(?:my\s+)?(?:computer|pc|system)?",             "restart"),
    (r"(?:sleep|hibernate)\s*(?:my\s+)?(?:computer|pc|system)?", "sleep"),
    # Open URL/website
    (r"(?:go to|open|visit)\s+((?:https?://|www\.)\S+)",         "open_url"),
    (r"(?:open|go to)\s+(\w+(?:\.\w+)+)",                       "open_url"),
    # IP address
    (r"(?:what(?:'s| is))\s+(?:my\s+)?ip\s*(?:address)?",       "ip_address"),
    (r"(?:my\s+)?ip\s*(?:address)",                              "ip_address"),
    # Processes
    (r"(?:list|show|what)\s*(?:are\s+)?(?:the\s+)?(?:running\s+)?(?:processes|apps|programs|tasks)", "list_processes"),
    # Brightness
    (r"(?:set|change)\s+(?:the\s+)?brightness\s+(?:to\s+)?(\d+)", "set_brightness"),
    (r"brightness\s+(?:up|increase)",                             "brightness_up"),
    (r"brightness\s+(?:down|decrease|lower)",                     "brightness_down"),
    # Empty recycle bin
    (r"(?:empty|clear|clean)\s+(?:the\s+)?(?:recycle\s*bin|trash|dustbin)", "empty_recycle_bin"),
]

# Commands that need confirmation before execution
_DANGEROUS_COMMANDS = {"shutdown", "restart", "sleep", "empty_recycle_bin"}


class OSCommander:

    def __init__(self):
        self._pending_confirm = None  # (action, params) awaiting "yes"

    def detect_intent(self, text: str):
        """Returns (action, params) or None if no OS command detected."""
        t = text.lower().strip()

        # Check for confirmation of pending dangerous command
        if self._pending_confirm:
            if any(w in t for w in ("yes", "yeah", "yep", "confirm", "do it", "go ahead", "sure")):
                action, params = self._pending_confirm
                self._pending_confirm = None
                return action, params
            else:
                self._pending_confirm = None
                return None, None

        for pattern, action in _INTENT_PATTERNS:
            match = re.search(pattern, t)
            if match:
                params = match.groups()
                if action in _DANGEROUS_COMMANDS:
                    self._pending_confirm = (action, params)
                    return "confirm_needed", (action,)
                return action, params

        return None, None

    def execute(self, action: str, params: tuple) -> str:
        """Execute an OS command and return a status message."""
        try:
            handler = getattr(self, f"_do_{action}", None)
            if handler:
                return handler(params)
            return f"Unknown command: {action}"
        except Exception as e:
            return f"Error executing command: {e}"

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _do_confirm_needed(self, params):
        action = params[0]
        labels = {
            "shutdown": "shut down your computer",
            "restart": "restart your computer",
            "sleep": "put your computer to sleep",
            "empty_recycle_bin": "empty the recycle bin",
        }
        return f"Are you sure you want to {labels.get(action, action)}? Say **yes** to confirm."

    def _do_open_app(self, params):
        app_name = params[0].strip().lower()
        # Remove filler words (whole-word only to avoid stripping letters)
        app_name = re.sub(r'\b(?:the|my|please|app|application|program)\b', '', app_name).strip()
        app_name = re.sub(r'\s+', ' ', app_name).strip()

        exe = APP_ALIASES.get(app_name, app_name)

        # URI-style apps (ms-settings:, etc.)
        if ":" in exe:
            os.startfile(exe)
        else:
            subprocess.Popen(f"start {exe}", shell=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Opening **{app_name.title()}**."

    def _do_close_app(self, params):
        app_name = params[0].strip().lower()
        app_name = re.sub(r'\b(?:the|my|please|app|application|program)\b', '', app_name).strip()
        app_name = re.sub(r'\s+', ' ', app_name).strip()

        exe = APP_ALIASES.get(app_name, app_name)
        os.system(f"taskkill /f /im {exe}.exe >nul 2>&1")
        return f"Closing **{app_name.title()}**."

    def _do_system_info(self, params):
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\")
        battery = psutil.sensors_battery()
        uptime_sec = (datetime.now() - datetime.fromtimestamp(psutil.boot_time())).total_seconds()
        hours, remainder = divmod(int(uptime_sec), 3600)
        minutes = remainder // 60

        lines = [
            f"**CPU:** {cpu}%",
            f"**RAM:** {ram.percent}% ({ram.used // (1024**3):.1f} / {ram.total // (1024**3):.1f} GB)",
            f"**Disk (C:):** {disk.percent}% ({disk.used // (1024**3):.0f} / {disk.total // (1024**3):.0f} GB)",
        ]
        if battery:
            plug = "Plugged in" if battery.power_plugged else "On battery"
            lines.append(f"**Battery:** {battery.percent}% ({plug})")
        lines.append(f"**Uptime:** {hours}h {minutes}m")
        lines.append(f"**Processes:** {len(psutil.pids())} running")

        return "\n".join(lines)

    def _do_set_volume(self, params):
        level = max(0, min(100, int(params[0])))
        vol = _audio_volume()
        if vol.GetMute():
            vol.SetMute(0, None)
        vol.SetMasterVolumeLevelScalar(level / 100, None)
        return f"Volume set to **{level}%**."

    def _do_volume_up(self, params):
        vol = _audio_volume()
        new = min(1.0, vol.GetMasterVolumeLevelScalar() + 0.10)
        vol.SetMasterVolumeLevelScalar(new, None)
        return f"Volume increased to **{int(round(new * 100))}%**."

    def _do_volume_down(self, params):
        vol = _audio_volume()
        new = max(0.0, vol.GetMasterVolumeLevelScalar() - 0.10)
        vol.SetMasterVolumeLevelScalar(new, None)
        return f"Volume decreased to **{int(round(new * 100))}%**."

    def _do_mute_toggle(self, params):
        vol = _audio_volume()
        new = 0 if vol.GetMute() else 1
        vol.SetMute(new, None)
        return "Audio **muted**." if new else "Audio **unmuted**."

    def _do_get_volume(self, params):
        vol = _audio_volume()
        level = int(round(vol.GetMasterVolumeLevelScalar() * 100))
        muted = " (muted)" if vol.GetMute() else ""
        return f"Volume is at **{level}%**{muted}."

    def _do_screenshot(self, params):
        path = os.path.join(os.path.expanduser("~"), "Desktop", f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        img = pyautogui.screenshot()
        img.save(path)
        return f"Screenshot saved to **Desktop**."

    def _do_web_search(self, params):
        query = params[0].strip()
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
        webbrowser.open(url)
        return f"Searching for **{query}**."

    def _do_time_date(self, params):
        now = datetime.now()
        return f"It's **{now.strftime('%I:%M %p')}** on **{now.strftime('%A, %B %d, %Y')}**."

    def _do_lock_screen(self, params):
        ctypes.windll.user32.LockWorkStation()
        return "Locking your computer."

    def _do_shutdown(self, params):
        os.system("shutdown /s /t 5")
        return "Shutting down in 5 seconds..."

    def _do_restart(self, params):
        os.system("shutdown /r /t 5")
        return "Restarting in 5 seconds..."

    def _do_sleep(self, params):
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        return "Putting computer to sleep."

    def _do_open_url(self, params):
        url = params[0].strip()
        # Handle bare names like "youtube" → "youtube.com"
        if "." not in url and "/" not in url:
            url = url + ".com"
        if not url.startswith("http"):
            url = "https://" + url
        webbrowser.open(url)
        return f"Opening **{url}**."

    def _do_ip_address(self, params):
        import socket
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        return f"**Hostname:** {hostname}\n**Local IP:** {local_ip}"

    def _do_list_processes(self, params):
        procs = []
        for p in psutil.process_iter(["name", "memory_percent"]):
            try:
                info = p.info
                if info["memory_percent"] and info["memory_percent"] > 0.5:
                    procs.append((info["name"], info["memory_percent"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x[1], reverse=True)
        lines = [f"**{name}** — {mem:.1f}% RAM" for name, mem in procs[:15]]
        return "**Top processes by RAM:**\n" + "\n".join(lines)

    def _do_set_brightness(self, params):
        level = int(params[0])
        level = max(0, min(100, level))
        os.system(f'powershell (Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})')
        return f"Brightness set to **{level}%**."

    def _do_brightness_up(self, params):
        pyautogui.hotkey("fn", "f12")  # Common brightness up
        return "Brightness increased."

    def _do_brightness_down(self, params):
        pyautogui.hotkey("fn", "f11")  # Common brightness down
        return "Brightness decreased."

    def _do_empty_recycle_bin(self, params):
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x07)
        return "Recycle bin emptied."
