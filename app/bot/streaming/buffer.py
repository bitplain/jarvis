from dataclasses import dataclass
from enum import StrEnum


class FlushReason(StrEnum):
    INTERVAL = "interval"
    CHARS = "chars"
    SENTENCE = "sentence"
    FINAL = "final"


@dataclass(frozen=True)
class FlushDecision:
    text: str
    delta_length: int
    is_final: bool
    reason: FlushReason


class StreamBuffer:
    def __init__(
        self,
        *,
        update_interval_ms: int = 800,
        min_chars_delta: int = 120,
        max_draft_seconds: int = 25,
    ) -> None:
        self.update_interval_seconds = update_interval_ms / 1000
        self.min_chars_delta = min_chars_delta
        self.max_draft_seconds = max_draft_seconds
        self.started_at: float | None = None
        self.last_flush_at: float | None = None
        self.last_flushed_length = 0
        self._parts: list[str] = []

    @property
    def text(self) -> str:
        return "".join(self._parts)

    @property
    def delta_length(self) -> int:
        return max(0, len(self.text) - self.last_flushed_length)

    def append(self, chunk: str, *, now: float | None = None) -> None:
        if now is not None and self.started_at is None:
            self.started_at = now
        if chunk:
            self._parts.append(chunk)

    def should_flush(self, *, now: float) -> FlushDecision | None:
        if self.started_at is None:
            self.started_at = now
        text = self.text
        delta = self.delta_length
        if not text or delta <= 0:
            return None
        reason: FlushReason | None = None
        if delta >= self.min_chars_delta:
            reason = FlushReason.CHARS
        elif self._has_sentence_boundary(text):
            reason = FlushReason.SENTENCE
        elif (
            self.last_flush_at is not None
            and now - self.last_flush_at >= self.update_interval_seconds
        ):
            reason = FlushReason.INTERVAL
        elif now - self.started_at >= self.max_draft_seconds:
            reason = FlushReason.INTERVAL
        if reason is None:
            return None
        return FlushDecision(text=text, delta_length=delta, is_final=False, reason=reason)

    def final_flush(self, *, now: float) -> FlushDecision:
        if self.started_at is None:
            self.started_at = now
        return FlushDecision(
            text=self.text,
            delta_length=self.delta_length,
            is_final=True,
            reason=FlushReason.FINAL,
        )

    def mark_flushed(self, *, now: float) -> None:
        if self.started_at is None:
            self.started_at = now
        self.last_flush_at = now
        self.last_flushed_length = len(self.text)

    def _has_sentence_boundary(self, text: str) -> bool:
        stripped = text.rstrip()
        if not stripped:
            return False
        return stripped[-1] in {".", "!", "?", "。", "…"}
