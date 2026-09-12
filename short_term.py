"""
AURA Short-Term Memory — sliding window + fact extraction.
"""

import re


class ShortTermMemory:
    def __init__(self, max_size=10):
        self.memory = []          # recent conversation turns
        self.max_size = max_size
        self.user_name = None
        self.user_age = None

    def add(self, text: str):
        text_lower = text.lower().strip()

        # ── Name detection ───────────────────────────────────────────────────
        for pattern in [
            r"my name is ([a-zA-Z]+)",
            r"i'?m ([a-zA-Z]+),?\s",
            r"call me ([a-zA-Z]+)",
            r"they call me ([a-zA-Z]+)",
        ]:
            match = re.search(pattern, text_lower)
            if match:
                name = match.group(1).capitalize()
                # Filter out common false positives
                if name not in ("Fine", "Good", "Okay", "Here", "Not", "The",
                                "Just", "Really", "So", "Very", "Also", "Sure"):
                    self.user_name = name
                break

        # ── Age detection ────────────────────────────────────────────────────
        age_patterns = [
            r"my age is (\d+)",
            r"i(?:'m| am) (\d+)\s*years?\s*old",
            r"i(?:'m| am) (\d+)\b(?!\s*(?:percent|kg|lbs|cm|ft|meters))",
            r"age[:\s]+(\d+)",
        ]
        for pattern in age_patterns:
            match = re.search(pattern, text_lower)
            if match:
                age_val = int(match.group(1))
                if 1 <= age_val <= 120:
                    self.user_age = str(age_val)
                break

        # Store the turn (both questions and statements for context)
        self.memory.append(text)
        if len(self.memory) > self.max_size:
            self.memory.pop(0)

    def get_context(self) -> str:
        if not self.memory:
            return ""
        return "\n".join(self.memory[-self.max_size:])

    def get_facts(self) -> dict:
        return {
            "name": self.user_name,
            "age": self.user_age,
        }
