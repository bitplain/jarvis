# Stage 4F-2 Prompt Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить управляемые Prompt Profiles для private, group и будущего watcher каналов Jarvis.

**Architecture:** Профили будут фиксированными enum-значениями в `runtime_settings`, чтобы не добавлять новую таблицу и не хранить произвольные prompt-тексты. Worker читает профиль перед каждым job и передает его в `MemoryService`, который строит безопасный system prompt. Telegram `/settings` получает admin-only раздел `Профили`.

**Tech Stack:** Python 3.12, aiogram, SQLAlchemy async, Alembic runtime settings, pytest, uv.

---

### Task 1: Prompt Profile Service

**Files:**
- Modify: `app/services/runtime_settings_service.py`
- Modify: `tests/test_runtime_settings_service.py`

- [ ] **Step 1: Write failing tests**

Add tests for default profile, saving a profile per scope, rejecting unknown profile values, rejecting unknown scopes, and treating invalid DB values as `balanced`.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/test_runtime_settings_service.py -q
```

Expected: new tests fail because prompt profile enums and service methods do not exist.

- [ ] **Step 3: Implement minimal service**

Add `PromptProfile`, `PromptProfileScope`, key mapping, `get_prompt_profile(scope)`, and `set_prompt_profile(scope, value, updated_by_telegram_id=...)`.

- [ ] **Step 4: Run tests to verify GREEN**

Run the same pytest command and expect PASS.

### Task 2: Memory Context Prompt Rendering

**Files:**
- Modify: `app/services/memory_service.py`
- Modify: `tests/test_memory_service.py`

- [ ] **Step 1: Write failing tests**

Add tests that `build_context(..., prompt_profile=PromptProfile.SHORT, chat_kind="private")` includes the short profile instruction and that group/deep includes group-oriented wording while preserving existing message history.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/test_memory_service.py -q
```

Expected: failure because `build_context` does not accept profile arguments.

- [ ] **Step 3: Implement prompt rendering**

Add a small `build_system_prompt()` helper and optional `prompt_profile` / `chat_kind` parameters to `MemoryService.build_context()`.

- [ ] **Step 4: Run tests to verify GREEN**

Run the same pytest command and expect PASS.

### Task 3: Worker Applies Private And Group Profiles

**Files:**
- Modify: `app/workers/jobs.py`
- Modify: `tests/test_worker_jobs.py`

- [ ] **Step 1: Write failing tests**

Add tests that private jobs read `PromptProfileScope.PRIVATE`, group jobs read `PromptProfileScope.GROUP`, and missing runtime settings falls back to `balanced`.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/test_worker_jobs.py -q
```

Expected: failure because worker does not read prompt profiles.

- [ ] **Step 3: Implement worker integration**

Read the active profile after active provider, select scope from `payload["private"]`, and pass the profile plus chat kind into `MemoryService.build_context()`.

- [ ] **Step 4: Run tests to verify GREEN**

Run the same pytest command and expect PASS.

### Task 4: Telegram Settings UI

**Files:**
- Modify: `app/bot/routers/commands.py`
- Modify: `tests/test_settings_command.py`

- [ ] **Step 1: Write failing tests**

Add tests for settings home button `Профили`, profile overview, private/group/watcher profile pages, saving a profile, repeated selection no-op, non-admin denial, and missing runtime settings message.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/test_settings_command.py -q
```

Expected: failure because profile callbacks and keyboards do not exist.

- [ ] **Step 3: Implement UI**

Add callback constants, render helpers, keyboards, and handler branches reusing `RuntimeSettingsService`.

- [ ] **Step 4: Run tests to verify GREEN**

Run the same pytest command and expect PASS.

### Task 5: Readiness, Docs, And Project Rules

**Files:**
- Create: `scripts/smoke_prompt_profiles_readiness.py`
- Create: `tests/test_smoke_prompt_profiles_readiness.py`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Create: `docs/STAGE_4F2_PROMPT_PROFILES_REPORT.md`

- [ ] **Step 1: Write failing readiness test**

Test that readiness returns PASS only when service, callbacks, and worker profile integration are present and that it never calls Telegram `getUpdates`.

- [ ] **Step 2: Run readiness test to verify RED**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/test_smoke_prompt_profiles_readiness.py -q
```

Expected: failure because the script does not exist.

- [ ] **Step 3: Implement readiness and docs**

Add the script, Stage 4F-2 AGENTS rules, README section, and stage report.

- [ ] **Step 4: Run targeted and broad checks**

Run targeted tests first, then the project checks required by `AGENTS.md` as far as the local machine allows.

### Task 6: Private Ingress Regression Guard

**Files:**
- Modify: `app/api/routes_telegram.py`
- Modify: `tests/test_telegram_webhook_ingress.py`
- Modify: `tests/test_worker_jobs.py`
- Create: `scripts/smoke_private_ingress_readiness.py`
- Create: `tests/test_smoke_private_ingress_readiness.py`
- Modify: `scripts/smoke_prompt_profiles_readiness.py`

- [ ] **Step 1: Reproduce private silence with a failing test**

Add synthetic webhook tests proving `/start` reaches `cmd_start`, private text from admin/allowed user enqueues exactly one `process_llm_message`, unknown private user gets `Доступ запрещён.`, and `/start` still replies if Redis pool creation fails before dispatcher feed.

- [ ] **Step 2: Fix the root cause minimally**

Do not let Redis connection failure abort `POST /telegram/webhook` before `dispatcher.feed_update(...)`. Log only sanitized `telegram_webhook_redis_unavailable`, pass `redis=None` for handlers that can continue, and persist a successfully created Redis pool on `app.state.redis_pool`.

- [ ] **Step 3: Guard Prompt Profiles against FSM capture**

Verify Prompt Profiles callbacks do not set FSM state and the next normal private message still reaches the private LLM handler.

- [ ] **Step 4: Add readiness coverage**

`scripts/smoke_private_ingress_readiness.py` must return `PASS_PRIVATE_INGRESS_READINESS`, and `scripts/smoke_prompt_profiles_readiness.py` must require the private ingress regression tests and worker prompt profile fallback.
