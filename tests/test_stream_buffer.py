from app.bot.streaming.buffer import StreamBuffer


def test_stream_buffer_throttles_updates() -> None:
    buffer = StreamBuffer(min_interval_seconds=0.8, min_chars=10)

    assert buffer.should_flush(now=0.0, text="12345") is False
    assert buffer.should_flush(now=0.1, text="1234567890") is True
    buffer.mark_flushed(now=0.1)
    assert buffer.should_flush(now=0.2, text="123456789") is False
    assert buffer.should_flush(now=1.0, text="1") is True
