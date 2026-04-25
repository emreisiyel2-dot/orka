"""Session-based quota tracker for CLI providers.

Parallel to the token-based QuotaManager. Tracks session duration,
command count, prompt count, and task count per CLI provider.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class CLISessionUsage:
    provider: str
    session_count: int = 0
    total_duration_seconds: float = 0.0
    total_commands: int = 0
    total_prompts: int = 0
    total_tasks: int = 0
    status: str = "available"  # "available" | "throttled" | "blocked"
    blocked_until: datetime | None = None
    window_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CLIQuotaTracker:
    def __init__(
        self,
        max_concurrent: int = 3,
        max_sessions_per_hour: int = 20,
        throttle_threshold: float = 0.2,
    ):
        self._max_concurrent = max_concurrent
        self._max_sessions_per_hour = max_sessions_per_hour
        self._throttle_threshold = throttle_threshold
        self._usage: dict[str, CLISessionUsage] = {}
        self._active_sessions: dict[str, int] = {}

    def _get_or_create(self, provider: str) -> CLISessionUsage:
        if provider not in self._usage:
            self._usage[provider] = CLISessionUsage(provider=provider)
        return self._usage[provider]

    def check_available(self, provider: str) -> str:
        """Check if a CLI provider has quota available.

        Returns: "available" | "throttled" | "blocked".
        """
        self._auto_reset_if_needed(provider)
        usage = self._get_or_create(provider)

        if usage.status == "blocked":
            if usage.blocked_until and datetime.now(timezone.utc) >= usage.blocked_until:
                self.reset(provider)
                return "available"
            return "blocked"

        if usage.session_count >= self._max_sessions_per_hour:
            usage.status = "blocked"
            return "blocked"

        active = self._active_sessions.get(provider, 0)
        if active >= self._max_concurrent:
            return "throttled"

        threshold = self._max_sessions_per_hour * self._throttle_threshold
        remaining = self._max_sessions_per_hour - usage.session_count
        if remaining <= threshold:
            usage.status = "throttled"
            return "throttled"

        return "available"

    def record_session(
        self,
        provider: str,
        duration_seconds: float,
        command_count: int = 1,
        prompt_count: int = 0,
        task_count: int = 1,
    ) -> None:
        """Record a completed CLI session."""
        usage = self._get_or_create(provider)
        usage.session_count += 1
        usage.total_duration_seconds += duration_seconds
        usage.total_commands += command_count
        usage.total_prompts += prompt_count
        usage.total_tasks += task_count

    def start_session(self, provider: str) -> None:
        """Track an active session start."""
        self._active_sessions[provider] = self._active_sessions.get(provider, 0) + 1

    def end_session(self, provider: str) -> None:
        """Track an active session end."""
        current = self._active_sessions.get(provider, 0)
        if current > 0:
            self._active_sessions[provider] = current - 1

    def mark_blocked(self, provider: str, reason: str, blocked_until: datetime | None = None) -> None:
        """Mark a CLI provider as blocked (e.g., rate-limit detected)."""
        usage = self._get_or_create(provider)
        usage.status = "blocked"
        usage.blocked_until = blocked_until

    def reset(self, provider: str) -> None:
        """Reset session counters for a provider."""
        if provider in self._usage:
            self._usage[provider] = CLISessionUsage(provider=provider)

    def _auto_reset_if_needed(self, provider: str) -> None:
        """Reset hourly counters if the window has passed."""
        usage = self._get_or_create(provider)
        now = datetime.now(timezone.utc)
        elapsed = (now - usage.window_start).total_seconds()
        if elapsed >= 3600:
            self._usage[provider] = CLISessionUsage(provider=provider)

    def get_usage(self, provider: str) -> CLISessionUsage | None:
        return self._usage.get(provider)

    def get_all_usage(self) -> dict[str, CLISessionUsage]:
        return dict(self._usage)
