class StreamBuffer:
    def __init__(self, *, min_interval_seconds: float = 0.8, min_chars: int = 100) -> None:
        self.min_interval_seconds = min_interval_seconds
        self.min_chars = min_chars
        self.last_flush_at: float | None = None

    def should_flush(self, *, now: float, text: str) -> bool:
        if len(text) >= self.min_chars:
            return True
        if self.last_flush_at is None:
            return False
        return now - self.last_flush_at >= self.min_interval_seconds

    def mark_flushed(self, *, now: float) -> None:
        self.last_flush_at = now
