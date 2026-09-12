"""
AURA Long-Term Vector Memory — offline persistent knowledge base.
Stores embeddings + text on E:/AURA_DATA/.
Auto-loads on startup, auto-saves on every write.
Supports bulk ingestion from text/PDF/JSON files.
"""

import json
import os
import re
import numpy as np
from sentence_transformers import SentenceTransformer

DATA_DIR = "E:/AURA_DATA"
TEXTS_FILE = os.path.join(DATA_DIR, "texts.json")
EMBEDS_FILE = os.path.join(DATA_DIR, "embeddings.npy")
CHUNK_SIZE = 300  # chars per chunk when ingesting large text


# ── ingestion filter ─────────────────────────────────────────────────────────

_INTERROGATIVE_STARTS = (
    "what", "who", "whom", "whose", "when", "where", "why", "how", "which",
    "can", "could", "do", "does", "did", "is", "are", "am", "was", "were",
    "will", "would", "should", "shall", "may", "might", "have", "has", "had",
)

_GREETINGS_AND_NOISE = {
    "hi", "hii", "hiii", "hello", "hey", "heyy", "yo", "sup", "howdy",
    "bye", "goodbye", "cya", "thanks", "thank you", "ty", "thx",
    "ok", "okay", "k", "kk", "cool", "nice", "great", "lol", "lmao",
    "yes", "yeah", "yep", "no", "nope", "nah",
    "umm", "uhh", "hmm", "oh", "ah",
}

_COMMAND_VERBS = (
    "open ", "close ", "launch ", "start ", "stop ", "play ", "pause ",
    "shutdown", "restart", "reboot", "mute ", "unmute",
    "volume ", "brightness ", "screenshot", "take a screenshot",
    "search for ", "find ",
)


def is_storable_fact(text: str) -> bool:
    """Decide whether a user utterance is durable enough for long-term memory.

    Reject: questions, greetings/acknowledgements, OS commands, STT junk
    (too short, no alphabetic content, or mostly punctuation).
    """
    if not text:
        return False
    t = text.strip()
    if not t:
        return False

    # Length gate — too short is almost always noise
    if len(t) < 12 or len(t) > 400:
        return False

    # Must contain letters
    letters = sum(c.isalpha() for c in t)
    if letters < 6 or letters / len(t) < 0.5:
        return False

    lower = t.lower().rstrip(" .!")

    # Questions
    if t.rstrip().endswith("?"):
        return False
    first_word = lower.split(" ", 1)[0]
    if first_word in _INTERROGATIVE_STARTS:
        return False

    # Greetings / fillers
    if lower in _GREETINGS_AND_NOISE:
        return False
    # Leading greeting + nothing substantial after
    for g in ("hi ", "hii ", "hello ", "hey "):
        if lower.startswith(g) and len(lower) - len(g) < 15:
            return False

    # OS commands
    if lower.startswith(_COMMAND_VERBS):
        return False

    return True


class LongTermMemory:

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.makedirs(DATA_DIR, exist_ok=True)
        self.model = SentenceTransformer(model_name, local_files_only=True)
        self.memory: list[str] = []
        self._embeddings: np.ndarray | None = None
        self._load()

    # ── Persistence ─────────────────────────────────────────────────────────

    def _load(self):
        """Load stored texts and embeddings from E: drive."""
        if os.path.exists(TEXTS_FILE) and os.path.exists(EMBEDS_FILE):
            try:
                with open(TEXTS_FILE, "r", encoding="utf-8") as f:
                    self.memory = json.load(f)
                self._embeddings = np.load(EMBEDS_FILE)
                # Sanity check
                if len(self.memory) != self._embeddings.shape[0]:
                    print("[LTM] Warning: text/embedding count mismatch, rebuilding...")
                    self._rebuild_embeddings()
                print(f"[LTM] Loaded {len(self.memory)} entries from disk.")
            except Exception as e:
                print(f"[LTM] Error loading data: {e}")
                self.memory = []
                self._embeddings = None
        else:
            print("[LTM] No existing data found, starting fresh.")

    def _save(self):
        """Persist texts and embeddings to E: drive."""
        try:
            with open(TEXTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, ensure_ascii=False)
            if self._embeddings is not None:
                np.save(EMBEDS_FILE, self._embeddings)
        except Exception as e:
            print(f"[LTM] Error saving: {e}")

    def _rebuild_embeddings(self):
        """Re-encode all texts (recovery from corruption)."""
        if self.memory:
            self._embeddings = self.model.encode(
                self.memory, normalize_embeddings=True, show_progress_bar=True
            )
        else:
            self._embeddings = None
        self._save()

    # ── Core API ────────────────────────────────────────────────────────────

    def store(self, text: str):
        """Store a single piece of text. Auto-saves to disk."""
        text = text.strip()
        if not text or text in self.memory:
            return

        emb = self.model.encode(text, normalize_embeddings=True)
        self.memory.append(text)
        if self._embeddings is None:
            self._embeddings = emb.reshape(1, -1)
        else:
            self._embeddings = np.vstack([self._embeddings, emb.reshape(1, -1)])
        self._save()

    def store_batch(self, texts: list[str]):
        """Store multiple texts at once. Much faster than store() in a loop."""
        new_texts = []
        for t in texts:
            t = t.strip()
            if t and t not in self.memory:
                new_texts.append(t)

        if not new_texts:
            return 0

        embs = self.model.encode(new_texts, normalize_embeddings=True, show_progress_bar=True)
        self.memory.extend(new_texts)
        if self._embeddings is None:
            self._embeddings = embs
        else:
            self._embeddings = np.vstack([self._embeddings, embs])
        self._save()
        return len(new_texts)

    def retrieve(self, query: str, top_k: int = 3, threshold: float = 0.25) -> list[str]:
        """Find the most relevant stored texts for a query."""
        if not self.memory or self._embeddings is None:
            return []

        query_emb = self.model.encode(query, normalize_embeddings=True).reshape(1, -1)
        scores = (self._embeddings @ query_emb.T).flatten()

        mask = scores >= threshold
        if not mask.any():
            return []

        filtered_idx = np.where(mask)[0]
        top_idx = filtered_idx[np.argsort(scores[filtered_idx])[-top_k:][::-1]]
        return [self.memory[i] for i in top_idx]

    def count(self) -> int:
        return len(self.memory)

    def clear(self):
        """Wipe all stored data."""
        self.memory = []
        self._embeddings = None
        self._save()

    # ── Data Ingestion ──────────────────────────────────────────────────────

    def ingest_text(self, text: str) -> int:
        """Ingest a large block of text — splits into chunks and stores."""
        chunks = self._chunk_text(text)
        return self.store_batch(chunks)

    def ingest_file(self, filepath: str) -> int:
        """Ingest a file from disk. Supports .txt, .md, .json, .pdf."""
        filepath = filepath.strip()
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        ext = os.path.splitext(filepath)[1].lower()

        if ext in (".txt", ".md", ".log"):
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            return self.ingest_text(text)

        elif ext == ".csv":
            texts = self._read_tabular(filepath, fmt="csv")
            return self.store_batch(texts)

        elif ext == ".parquet":
            texts = self._read_tabular(filepath, fmt="parquet")
            return self.store_batch(texts)

        elif ext == ".json":
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            texts = self._flatten_json(data)
            return self.store_batch(texts)

        elif ext == ".pdf":
            text = self._read_pdf(filepath)
            return self.ingest_text(text)

        else:
            # Try reading as plain text
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            return self.ingest_text(text)

    def ingest_folder(self, folder: str) -> int:
        """Ingest all supported files in a folder recursively."""
        total = 0
        supported = (".txt", ".md", ".json", ".pdf", ".log", ".csv", ".parquet")
        for root, dirs, files in os.walk(folder):
            for fname in files:
                if os.path.splitext(fname)[1].lower() in supported:
                    try:
                        count = self.ingest_file(os.path.join(root, fname))
                        total += count
                        print(f"[LTM] Ingested {fname}: {count} chunks")
                    except Exception as e:
                        print(f"[LTM] Failed to ingest {fname}: {e}")
        return total

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        """Split text into meaningful chunks by paragraphs, then by size."""
        # Split on double newlines (paragraphs)
        paragraphs = re.split(r"\n\s*\n", text)
        chunks = []
        for para in paragraphs:
            para = para.strip()
            if not para or len(para) < 20:
                continue
            if len(para) <= CHUNK_SIZE:
                chunks.append(para)
            else:
                # Split long paragraphs by sentences
                sentences = re.split(r"(?<=[.!?])\s+", para)
                buf = ""
                for sent in sentences:
                    if len(buf) + len(sent) > CHUNK_SIZE and buf:
                        chunks.append(buf.strip())
                        buf = sent
                    else:
                        buf = (buf + " " + sent).strip()
                if buf.strip():
                    chunks.append(buf.strip())
        return chunks

    @staticmethod
    def _flatten_json(data, prefix="") -> list[str]:
        """Flatten JSON into text entries."""
        texts = []
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str) and len(v.strip()) > 10:
                    texts.append(f"{k}: {v.strip()}")
                elif isinstance(v, (dict, list)):
                    texts.extend(LongTermMemory._flatten_json(v, f"{k} > "))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, str) and len(item.strip()) > 10:
                    texts.append(item.strip())
                elif isinstance(item, dict):
                    texts.extend(LongTermMemory._flatten_json(item, prefix))
        return texts

    @staticmethod
    def _read_tabular(filepath: str, fmt: str) -> list[str]:
        """Project tabular rows (CSV via pandas, Parquet via pyarrow) into
        'col: val | col: val' strings — one entry per row, filtering empties.
        Fully offline."""
        import pandas as pd
        if fmt == "csv":
            df = pd.read_csv(filepath, dtype=str, keep_default_na=False, on_bad_lines="skip")
        elif fmt == "parquet":
            # pandas delegates to pyarrow when engine="pyarrow"
            df = pd.read_parquet(filepath, engine="pyarrow")
            df = df.astype(str).fillna("")
        else:
            raise ValueError(f"Unsupported tabular fmt: {fmt}")

        cols = [str(c) for c in df.columns]
        texts: list[str] = []
        for row in df.itertuples(index=False, name=None):
            parts = [
                f"{cols[i]}: {str(v).strip()}"
                for i, v in enumerate(row)
                if str(v).strip()
            ]
            if parts:
                line = " | ".join(parts)
                if len(line) > 20:
                    texts.append(line)
        return texts

    @staticmethod
    def _read_pdf(filepath: str) -> str:
        """Extract text from PDF using PyMuPDF (fitz) — fully offline."""
        try:
            import fitz
            doc = fitz.open(filepath)
            text = ""
            for page in doc:
                text += page.get_text() + "\n"
            doc.close()
            return text
        except ImportError:
            raise ImportError(
                "PyMuPDF is required for PDF ingestion. "
                "Install with: pip install PyMuPDF"
            )
