"""
AURA Reasoning Engine — Qwen2.5-7B-Instruct Q4_K_M (fully offline, CUDA-only)
Backed by llama-cpp-python with all layers offloaded to the GPU.
"""

import os
import re

# Make sure the CUDA runtime that ships with torch is on the DLL search path
# BEFORE llama_cpp tries to load ggml-cuda.dll. torch's lib dir contains
# cudart64_12.dll / cublas64_12.dll / etc.
import torch  # noqa: F401  (imported for DLL side-effect and cuda check)
_TORCH_LIB = os.path.join(os.path.dirname(torch.__file__), "lib")
if os.path.isdir(_TORCH_LIB):
    os.add_dll_directory(_TORCH_LIB)

from llama_cpp import Llama


# ── paths ────────────────────────────────────────────────────────────────────

MODEL_PATH = r"D:\AURA\models\Qwen2.5-7B-Instruct-Q4_K_M.gguf"


# ── helpers ──────────────────────────────────────────────────────────────────

_GREETING_WORDS = {
    "hi", "hii", "hiii", "hello", "hey", "heyy", "yo", "sup", "howdy",
    "good morning", "good afternoon", "good evening", "good night",
    "morning", "afternoon", "evening",
}

def _is_greeting(text: str) -> bool:
    t = text.lower().strip().rstrip("!., ")
    return t in _GREETING_WORDS


def _is_asking_about_aura(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in [
        r"\byour\b", r"\byours\b", r"\byourself\b", r"\byou\b", r"\baura\b"
    ])

def _is_asking_about_user(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in [
        r"\bmy\b", r"\bmine\b", r"\bme\b", r"\bi am\b", r"\bam i\b"
    ])


# ── system prompt ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are AURA (Autonomous Universal Reasoning Agent), a precise offline assistant.

HARD RULES:
1. Never invent facts, dates, names, statistics, URLs, quotes, or citations. If you do not know, say so plainly.
2. Use the user's Known facts and Recent conversation as ground truth when provided.
3. You have no internet access, no tool use, no real-time data. Do not claim otherwise.
4. Be concise: 1-3 sentences unless the user asks for depth.
5. Plain prose only. No markdown, bullets, headings, code fences, or emoji — your output is read aloud by a TTS engine.
6. Do not repeat yourself and stop as soon as the answer is complete.\
"""


# ── engine ───────────────────────────────────────────────────────────────────

class ReasoningEngine:

    def __init__(self):
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required but not available.")
        if not os.path.isfile(MODEL_PATH):
            raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")

        print(f"[AURA] Loading Qwen2.5-7B Q4_K_M on GPU ({torch.cuda.get_device_name(0)})")

        self.llm = Llama(
            model_path=MODEL_PATH,
            n_ctx=4096,
            n_gpu_layers=-1,          # offload every layer to CUDA
            n_batch=512,
            n_threads=8,
            flash_attn=True,
            use_mmap=True,
            use_mlock=False,
            verbose=False,
            chat_format="qwen",
        )

        print("[AURA] Model loaded and ready.")

    # ── prompt construction ─────────────────────────────────────────────────

    def _build_messages(self, prompt, stm_context, ltm_context, facts):
        fact_lines = []
        if facts:
            if facts.get("name"):
                fact_lines.append(f"User's name is {facts['name']}.")
            if facts.get("age"):
                fact_lines.append(f"User's age is {facts['age']}.")

        system_msg = _SYSTEM_PROMPT
        if fact_lines:
            system_msg += "\n\nKnown facts about the user:\n" + "\n".join(fact_lines)

        parts = []
        if ltm_context:
            filtered = [m for m in ltm_context if not m.strip().endswith("?")]
            if filtered:
                parts.append(
                    "Relevant past context:\n" + "\n".join(f"- {m}" for m in filtered)
                )
        if stm_context:
            parts.append(f"Recent conversation:\n{stm_context}")
        parts.append(prompt)
        user_content = "\n\n".join(parts)

        return [
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_content},
        ]

    # ── non-streaming ───────────────────────────────────────────────────────

    def think(self, prompt: str, stm_context="", ltm_context=None, facts=None) -> str:
        return "".join(self.think_stream(prompt, stm_context, ltm_context, facts))

    # ── streaming ───────────────────────────────────────────────────────────

    def think_stream(self, prompt: str, stm_context="", ltm_context=None, facts=None):
        prompt_lower = prompt.lower().strip()
        about_aura = _is_asking_about_aura(prompt_lower)
        about_user = _is_asking_about_user(prompt_lower)
        asking_name = bool(re.search(r"\bname\b", prompt_lower))
        asking_age  = bool(re.search(r"\bage\b|\bold\b|\byears\b", prompt_lower))

        instant_reply = None
        if _is_greeting(prompt_lower):
            instant_reply = "Hey! How can I help you?"
        elif about_aura and not about_user:
            if asking_name:
                instant_reply = "My name is AURA — Autonomous Universal Reasoning Agent."
            elif asking_age:
                instant_reply = "I don't have an age. I'm an AI."
        elif facts and about_user and not about_aura:
            if asking_name and asking_age:
                if facts.get("name") and facts.get("age"):
                    instant_reply = f"Your name is {facts['name']} and you are {facts['age']} years old."
                elif facts.get("name"):
                    instant_reply = f"Your name is {facts['name']}. I don't know your age yet."
                elif facts.get("age"):
                    instant_reply = f"You are {facts['age']} years old. I don't know your name yet."
            elif asking_name:
                instant_reply = (
                    f"Your name is {facts['name']}."
                    if facts.get("name")
                    else "I don't know your name yet. Please tell me!"
                )
            elif asking_age:
                instant_reply = (
                    f"You are {facts['age']} years old."
                    if facts.get("age")
                    else "I don't know your age yet. Please tell me!"
                )

        if instant_reply:
            for word in instant_reply.split(" "):
                yield word + " "
            return

        messages = self._build_messages(prompt, stm_context, ltm_context, facts)

        stream = self.llm.create_chat_completion(
            messages=messages,
            max_tokens=384,
            temperature=0.2,
            top_p=0.8,
            top_k=20,
            repeat_penalty=1.12,
            stream=True,
        )

        for chunk in stream:
            choice = chunk["choices"][0]
            delta = choice.get("delta") or {}
            token = delta.get("content")
            if token:
                yield token
            if choice.get("finish_reason"):
                break


# ── manual test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    engine = ReasoningEngine()
    while True:
        try:
            user_input = input(">> ")
        except (EOFError, KeyboardInterrupt):
            break
        print("AURA: ", end="", flush=True)
        for token in engine.think_stream(user_input):
            print(token, end="", flush=True)
        print()
