"""
AURA — CLI Chat Interface
"""

from reasoning_engine import ReasoningEngine
from short_term import ShortTermMemory
from long_term_vector import LongTermMemory, is_storable_fact

print("[AURA] Loading reasoning engine...")
brain = ReasoningEngine()

print("[AURA] Loading memory systems...")
stm = ShortTermMemory()
ltm = LongTermMemory()

print("\n=== AURA v2 Ready ===\n")

while True:
    user_input = input("You: ").strip()

    if not user_input:
        continue

    if user_input.lower() in ("exit", "quit"):
        print("Goodbye.")
        break

    # Update memories
    stm.add(user_input)
    if is_storable_fact(user_input):
        ltm.store(user_input)

    # Gather context
    stm_context = stm.get_context()
    ltm_context = ltm.retrieve(user_input) if is_storable_fact(user_input) else []
    facts = stm.get_facts()

    # Stream response
    print("\nAURA: ", end="", flush=True)
    for token in brain.think_stream(user_input, stm_context, ltm_context, facts):
        print(token, end="", flush=True)
    print("\n")
