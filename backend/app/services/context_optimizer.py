"""Context optimizer — trims prompts before execution to reduce token usage.

Content tiers (trimming priority — preserved first, dropped last):
  REQUIRED  — task instruction, current file contents, error messages
  RELEVANT  — recent conversation history, related file snippets, prior decisions
  OPTIONAL  — full git diffs, verbose logs, historical context beyond window

Trimming process:
  1. If within max_context_tokens → return as-is
  2. If over → drop OPTIONAL content (blocks beyond history window)
  3. If still over → trim RELEVANT to history window
  4. REQUIRED is never trimmed
"""

_TOKENS_PER_WORD = 2

# Adaptive token limits by budget tier
_TIER_TOKEN_LIMITS: dict[str, tuple[int, int]] = {
    "low":    (2000, 4000),
    "medium": (4000, 8000),
    "high":   (8000, 16000),
}

# History window rules: (task_type, complexity) → keep_recent message blocks
_HISTORY_WINDOW: dict[tuple[str, str], int] = {
    ("analysis", "complex"): 10,
    ("review", "complex"): 10,
    ("code_gen", "complex"): 8,
    ("planning", "complex"): 8,
    ("docs", "simple"): 3,
    ("planning", "simple"): 3,
}

_DEFAULT_HISTORY_WINDOW = 5
_DEFAULT_MAX_TOKENS = 8000


class ContextOptimizer:
    def __init__(self, max_context_tokens: int | None = None):
        self._fixed_max_tokens = max_context_tokens

    def trim(self, prompt: str, complexity: str, task_type: str, budget_tier: str = "medium") -> str:
        max_tokens = self._resolve_max_tokens(budget_tier)
        max_words = max_tokens // _TOKENS_PER_WORD

        word_count = len(prompt.split())
        if word_count <= max_words:
            return prompt

        window = _HISTORY_WINDOW.get(
            (task_type, complexity), _DEFAULT_HISTORY_WINDOW
        )
        return self._trim_conversation(prompt, keep_recent=window)

    def _resolve_max_tokens(self, budget_tier: str) -> int:
        if self._fixed_max_tokens is not None:
            return self._fixed_max_tokens
        low, high = _TIER_TOKEN_LIMITS.get(budget_tier, (4000, 8000))
        return high

    def _trim_conversation(self, prompt: str, keep_recent: int) -> str:
        blocks = prompt.split("\n\n")
        if len(blocks) <= keep_recent:
            return prompt

        kept = blocks[-keep_recent:]
        trimmed_count = len(blocks) - keep_recent
        header = f"[{trimmed_count} earlier messages trimmed for context optimization]\n\n"
        return header + "\n\n".join(kept)
