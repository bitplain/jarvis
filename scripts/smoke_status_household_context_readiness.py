from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(path: str, needle: str) -> None:
    content = (ROOT / path).read_text(encoding="utf-8")
    if needle not in content:
        raise SystemExit(f"Missing {needle!r} in {path}")


def main() -> None:
    require("app/services/status_service.py", "jarvis:worker:heartbeat")
    require("app/workers/jobs.py", "record_worker_heartbeat")
    require("app/bot/routers/commands.py", "StatusService")
    require("alembic/versions/20260626_0009_household_memory.py", "household_memory_entries")
    require("app/db/models.py", "HouseholdMemoryEntry")
    require("app/db/repositories/household_memory.py", "HouseholdMemoryRepository")
    require("app/services/household_memory_service.py", "Похоже на секрет")
    require("app/services/household_memory_service.py", "normalize_delete_query_text")
    require("app/bot/routers/household_memory.py", "HouseholdMemoryInput")
    require("app/bot/routers/household_memory.py", "parse_delete_number")
    require("app/bot/routers/household_memory.py", "_is_callback_allowed")
    require("app/bot/routers/household_memory.py", "delete_memory_by_id_in_scope")
    require("app/bot/dispatcher.py", "household_memory")
    require("app/services/memory_service.py", "Память о текущем чате")
    require("tests/test_status_diagnostics.py", "is_worker_heartbeat_fresh")
    require("tests/test_household_memory_service.py", "secret")
    require("tests/test_household_memory_service.py", "matches_live_filler_and_connector_words")
    require("tests/test_household_memory_router.py", "does_not_enqueue")
    require("tests/test_household_memory_router.py", "забудь #1")
    require("tests/test_household_memory_router.py", "unknown_user_is_silent")
    require("tests/test_household_memory_llm_injection.py", "другая группа")
    require("AGENTS.md", "Stage 4I Status And Household Context")
    print("PASS_STATUS_HOUSEHOLD_CONTEXT_READINESS")  # noqa: T201


if __name__ == "__main__":
    main()
