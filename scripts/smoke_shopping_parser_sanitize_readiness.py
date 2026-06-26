from pathlib import Path

from app.services.simple_intent_parser import (
    ShoppingAddIntent,
    parse_explicit_intent,
    sanitize_shopping_items_input,
    split_shopping_colon_items,
    split_shopping_items,
)

ROOT = Path(__file__).resolve().parents[1]


def require(path: str, needle: str) -> None:
    content = (ROOT / path).read_text(encoding="utf-8")
    if needle not in content:
        raise SystemExit(f"Missing {needle!r} in {path}")


def main() -> None:
    parser = ROOT / "app/services/simple_intent_parser.py"
    router = ROOT / "app/bot/routers/lists_reminders.py"
    parser_content = parser.read_text(encoding="utf-8")
    router_content = router.read_text(encoding="utf-8")

    if split_shopping_items("мазик и молоко") != ["мазик", "молоко"]:
        raise SystemExit("split by simple connector is broken")
    if split_shopping_items("хлеб, молоко и яйца") != ["хлеб", "молоко", "яйца"]:
        raise SystemExit("comma plus connector split is broken")
    if sanitize_shopping_items_input("@Home_ai_my_bot творожок", "Home_ai_my_bot") != "творожок":
        raise SystemExit("bot mention sanitizer is broken")
    if split_shopping_colon_items("хлеб сок молоко") != ["хлеб", "сок", "молоко"]:
        raise SystemExit("buy-colon plain payload split is broken")
    parsed = parse_explicit_intent(
        "добавь @Home_ai_my_bot хлеб и молоко в список",
        bot_username="Home_ai_my_bot",
    )
    if not isinstance(parsed, ShoppingAddIntent) or parsed.items != ["хлеб", "молоко"]:
        raise SystemExit("shopping parser does not reuse sanitizer and splitter")

    for needle in [
        "def sanitize_shopping_items_input",
        "def split_shopping_items",
        "def split_shopping_colon_items",
        "re.IGNORECASE",
        "re.split",
        r"\s+и\s+",
    ]:
        if needle not in parser_content:
            raise SystemExit(f"Missing {needle!r} in parser")
    for needle in [
        "bot_username=",
        "parse_explicit_intent(",
        'Можно несколько позиций через запятую или "и"',
    ]:
        if needle not in router_content:
            raise SystemExit(f"Missing {needle!r} in router")

    require("tests/test_simple_intent_parser.py", "мазик и молоко")
    require("tests/test_simple_intent_parser.py", "хлеб, молоко и яйца")
    require("tests/test_simple_intent_parser.py", "@Home_ai_my_bot творожок")
    require("tests/test_telegram_webhook_ingress.py", "strips_bot_mention")
    require("tests/test_telegram_webhook_ingress.py", "rejects_empty_after_mention")
    print("PASS_SHOPPING_PARSER_SANITIZE_READINESS")  # noqa: T201


if __name__ == "__main__":
    main()
