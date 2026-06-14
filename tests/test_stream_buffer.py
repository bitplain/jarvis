from app.bot.streaming.buffer import FlushReason, StreamBuffer


def test_stream_buffer_flushes_by_interval() -> None:
    buffer = StreamBuffer(update_interval_ms=800, min_chars_delta=120)

    buffer.append("Начало")
    assert buffer.should_flush(now=0.0) is None
    buffer.mark_flushed(now=0.0)
    buffer.append(" продолжение")

    decision = buffer.should_flush(now=0.8)

    assert decision is not None
    assert decision.reason == FlushReason.INTERVAL
    assert decision.delta_length == len(" продолжение")
    assert decision.text == "Начало продолжение"


def test_stream_buffer_flushes_by_chars_delta() -> None:
    buffer = StreamBuffer(update_interval_ms=800, min_chars_delta=10)

    buffer.append("12345")
    assert buffer.should_flush(now=0.0) is None
    buffer.append("67890")

    decision = buffer.should_flush(now=0.1)

    assert decision is not None
    assert decision.reason == FlushReason.CHARS
    assert decision.delta_length == 10


def test_stream_buffer_flushes_by_sentence_boundary() -> None:
    buffer = StreamBuffer(update_interval_ms=800, min_chars_delta=120)

    buffer.append("Короткое предложение.")

    decision = buffer.should_flush(now=0.1)

    assert decision is not None
    assert decision.reason == FlushReason.SENTENCE


def test_stream_buffer_does_not_flush_every_token() -> None:
    buffer = StreamBuffer(update_interval_ms=800, min_chars_delta=120)

    buffer.append("Это")
    assert buffer.should_flush(now=0.0) is None
    buffer.append(" не")
    assert buffer.should_flush(now=0.1) is None
    buffer.append(" всё")
    assert buffer.should_flush(now=0.2) is None


def test_stream_buffer_final_flush() -> None:
    buffer = StreamBuffer(update_interval_ms=800, min_chars_delta=120)

    buffer.append("Финальный хвост без точки")
    decision = buffer.final_flush(now=0.2)

    assert decision.is_final is True
    assert decision.reason == FlushReason.FINAL
    assert decision.text == "Финальный хвост без точки"
