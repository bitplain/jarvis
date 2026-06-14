TELEGRAM_TEXT_LIMIT = 4096


def clip_telegram_preview(text: str) -> str:
    return text[:TELEGRAM_TEXT_LIMIT]


def split_telegram_text(text: str) -> list[str]:
    if not text:
        return [""]
    return [
        text[index : index + TELEGRAM_TEXT_LIMIT]
        for index in range(0, len(text), TELEGRAM_TEXT_LIMIT)
    ]
