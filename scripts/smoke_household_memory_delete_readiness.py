from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(path: str, needle: str) -> None:
    content = (ROOT / path).read_text(encoding="utf-8")
    if needle not in content:
        raise SystemExit(f"Missing {needle!r} in {path}")


def main() -> None:
    require("app/bot/routers/household_memory.py", "render_memory_list_html")
    require("app/bot/routers/household_memory.py", "🗑 {index}")
    require("app/bot/routers/household_memory.py", "parse_delete_number")
    require("app/bot/routers/household_memory.py", "delete_memory_by_number")
    require("app/bot/routers/household_memory.py", "Нашёл несколько похожих записей")
    require("app/bot/routers/household_memory.py", "Не нашёл похожую запись")
    require("app/bot/routers/household_memory.py", "delete_memory_by_id_in_scope")
    require("app/bot/routers/household_memory.py", "_is_callback_allowed")
    require("app/services/household_memory_service.py", "normalize_delete_query_text")
    require("app/services/household_memory_service.py", "memory_match_score")
    require("app/services/household_memory_service.py", "DELETE_QUERY_FILLER_WORDS")
    require("tests/test_household_memory_service.py", "matches_live_filler_and_connector_words")
    require("tests/test_household_memory_service.py", "delete_memory_by_number")
    require("tests/test_household_memory_service.py", "multiple_matches_returns_choice")
    require("tests/test_household_memory_service.py", "does_not_cross_delete_other_scope")
    require("tests/test_household_memory_router.py", "забудь #1")
    require("tests/test_household_memory_router.py", "unknown_user_is_silent")
    require("tests/test_household_memory_router.py", "uses_current_scope_guard")
    print("PASS_HOUSEHOLD_MEMORY_DELETE_READINESS")  # noqa: T201


if __name__ == "__main__":
    main()
