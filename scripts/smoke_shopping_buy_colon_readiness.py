from pathlib import Path

from app.services.simple_intent_parser import (
    ShoppingAddIntent,
    ShoppingListIntent,
    parse_explicit_intent,
    split_shopping_colon_items,
)

ROOT = Path(__file__).resolve().parents[1]


def require(path: str, needle: str) -> None:
    content = (ROOT / path).read_text(encoding="utf-8")
    if needle not in content:
        raise SystemExit(f"Missing {needle!r} in {path}")


def assert_shopping_items(
    text: str,
    expected: list[str],
    *,
    bot_username: str | None = None,
) -> None:
    parsed = parse_explicit_intent(text, bot_username=bot_username)
    if not isinstance(parsed, ShoppingAddIntent) or parsed.items != expected:
        raise SystemExit(f"Broken buy-colon parse for {text!r}: {parsed!r}")


def main() -> None:
    assert_shopping_items("Купить: хлеб сок мазик запеканку", ["хлеб", "сок", "мазик", "запеканку"])
    assert_shopping_items("купить: хлеб, сок и молоко", ["хлеб", "сок", "молоко"])
    assert_shopping_items(
        "@Home_ai_my_bot купить: творожок",
        ["творожок"],
        bot_username="Home_ai_my_bot",
    )
    assert_shopping_items("покупки: хлеб сок", ["хлеб", "сок"])
    assert_shopping_items("список покупок: хлеб сок", ["хлеб", "сок"])
    if parse_explicit_intent("где купить молоко?") is not None:
        raise SystemExit("natural language buy question was overbroadened")
    if parse_explicit_intent("можешь купить молоко?") is not None:
        raise SystemExit("natural language buy request was overbroadened")
    if not isinstance(parse_explicit_intent("что купить?"), ShoppingListIntent):
        raise SystemExit("shopping list query regression")
    if split_shopping_colon_items("хлеб сок мазик запеканку") != [
        "хлеб",
        "сок",
        "мазик",
        "запеканку",
    ]:
        raise SystemExit("plain buy-colon payload split is broken")

    require("app/services/simple_intent_parser.py", "SHOPPING_COLON_TRIGGERS")
    require("app/services/simple_intent_parser.py", "split_shopping_colon_items")
    require("tests/test_simple_intent_parser.py", "Купить: хлеб сок мазик запеканку")
    require("tests/test_simple_intent_parser.py", "где купить молоко?")
    require(
        "tests/test_telegram_webhook_ingress.py",
        "test_private_buy_colon_adds_items_without_llm_job",
    )
    require(
        "tests/test_telegram_webhook_ingress.py",
        "test_group_buy_colon_mention_adds_item_without_llm_job",
    )
    require(
        "tests/test_telegram_webhook_ingress.py",
        "test_group_buy_colon_without_mention_is_ignored",
    )
    print("PASS_SHOPPING_BUY_COLON_READINESS")  # noqa: T201


if __name__ == "__main__":
    main()
