from __future__ import annotations

import argparse
import re
import secrets
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

YANDEX_DEFAULT_BASE_URL = "https://ai.api.cloud.yandex.net/v1"
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
TELEGRAM_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
OPENROUTER_PREFERRED_MODELS = [
    "openai/gpt-4.1-mini",
    "openai/gpt-4o-mini",
    "google/gemini-2.0-flash-001",
    "google/gemini-flash-1.5",
    "anthropic/claude-3.5-haiku",
    "meta-llama/llama-3.1-8b-instruct",
]
REQUIRED_ENV_KEYS = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_BOT_USERNAME",
    "TELEGRAM_WEBHOOK_SECRET",
    "ADMIN_API_TOKEN",
    "ADMIN_TELEGRAM_IDS",
    "YANDEX_AI_BASE_URL",
    "YANDEX_AI_API_KEY",
    "YANDEX_AI_MODEL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
]


class JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, Any]:
        ...


class HttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, object] | None = None,
        timeout: float | None = None,
    ) -> JsonResponse:
        ...

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        timeout: float | None = None,
    ) -> JsonResponse:
        ...


@dataclass
class BootstrapResult:
    statuses: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    provider_status: dict[str, str] = field(default_factory=dict)
    generated: list[str] = field(default_factory=list)
    derived: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    applied: bool = False
    verdict: str = "BLOCKED_NEEDS_REAL_ENV"

    def render_sanitized(self) -> str:
        lines = ["Stage 1R env bootstrap sanitized result:"]
        lines.append(f"mode: {'apply' if self.applied else 'dry-run'}")
        for key in sorted(self.statuses):
            lines.append(f"{key}: {self.statuses[key]}")
        if self.provider_status:
            lines.append("provider status:")
            for provider, status in sorted(self.provider_status.items()):
                lines.append(f"- {provider}: {status}")
        if self.notes:
            lines.append("notes:")
            lines.extend(f"- {note}" for note in self.notes)
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            continue
        key, raw_value = raw_line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        values[key] = value
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in existing_lines:
        if "=" not in line or line.lstrip().startswith("#"):
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in values:
            output.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in values.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def is_valid_telegram_secret(value: str) -> bool:
    return len(value) in {48, 64} and TELEGRAM_SECRET_PATTERN.fullmatch(value) is not None


def generate_telegram_webhook_secret() -> str:
    while True:
        value = secrets.token_urlsafe(48).replace("=", "")
        if len(value) >= 64:
            value = value[:64]
        if len(value) in {48, 64} and is_valid_telegram_secret(value):
            return value


def generate_admin_api_token() -> str:
    return secrets.token_urlsafe(48).replace("=", "")


def _status_for_value(value: str | None) -> str:
    return "<set>" if value else "<missing>"


def _sanitize_error_text(value: str) -> str:
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", value)
    sanitized = re.sub(r"sk-[A-Za-z0-9._-]+", "sk-<redacted>", sanitized)
    return sanitized[:240]


def _safe_error(provider: str, action: str, response: JsonResponse | None = None) -> str:
    if response is None:
        return f"{provider} {action}: network_error"
    details: list[str] = [f"{provider} {action}: http_{response.status_code}"]
    request_id = ""
    headers = getattr(response, "headers", {})
    if headers:
        request_id = headers.get("x-request-id") or headers.get("cf-ray") or ""
    if request_id:
        details.append(f"request_id={_sanitize_error_text(str(request_id))}")
    try:
        payload = response.json()
        raw_description: object = payload.get("description") or payload.get("message")
        error = payload.get("error")
        if isinstance(error, dict):
            raw_description = error.get("message") or raw_description
            metadata = error.get("metadata")
            if isinstance(metadata, dict):
                provider_name = metadata.get("provider_name")
                if isinstance(provider_name, str) and provider_name:
                    details.append(f"provider_name={_sanitize_error_text(provider_name)}")
                raw = metadata.get("raw")
                if isinstance(raw, str) and raw:
                    details.append(f"raw={_sanitize_error_text(raw)}")
                previous_errors = metadata.get("previous_errors")
                if isinstance(previous_errors, list):
                    details.append(f"previous_errors={len(previous_errors)}")
        elif isinstance(error, str):
            raw_description = error
        if isinstance(raw_description, str):
            details.append(f"message={_sanitize_error_text(raw_description)}")
    except Exception:
        details.append("message=invalid_json")
    return " ".join(details)


def derive_telegram_username(
    env: dict[str, str],
    http: HttpClient,
    result: BootstrapResult,
) -> str | None:
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        result.notes.append("TELEGRAM_BOT_USERNAME requires TELEGRAM_BOT_TOKEN")
        return None
    try:
        response = http.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20.0)
    except httpx.HTTPError:
        result.notes.append("telegram getMe: network_error")
        return None
    if response.status_code >= 400:
        result.notes.append(_safe_error("telegram", "getMe", response))
        return None
    payload = response.json()
    result_payload = payload.get("result")
    if not payload.get("ok") or not isinstance(result_payload, dict):
        result.notes.append("telegram getMe: invalid_response")
        return None
    username = result_payload.get("username")
    if not isinstance(username, str) or not username:
        result.notes.append("telegram getMe: username_missing")
        return None
    return username


def derive_admin_telegram_id(
    env: dict[str, str],
    http: HttpClient,
    result: BootstrapResult,
) -> str | None:
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        result.notes.append("ADMIN_TELEGRAM_IDS requires TELEGRAM_BOT_TOKEN")
        return None
    try:
        response = http.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"allowed_updates": '["message"]'},
            timeout=20.0,
        )
    except httpx.HTTPError:
        result.notes.append("telegram getUpdates: network_error")
        return None
    if response.status_code >= 400:
        note = _safe_error("telegram", "getUpdates", response)
        result.notes.append(note)
        if "webhook" in note.lower():
            result.notes.append(
                "getUpdates may require deleting webhook first; rerun with "
                "--delete-webhook-for-getupdates only if you explicitly allow it"
            )
        return None
    payload = response.json()
    updates = payload.get("result")
    if not payload.get("ok") or not isinstance(updates, list):
        result.notes.append("telegram getUpdates: invalid_response")
        return None
    for update in reversed(updates):
        if not isinstance(update, dict):
            continue
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            continue
        if chat.get("type") != "private":
            continue
        sender_id = sender.get("id")
        if isinstance(sender_id, int):
            return str(sender_id)
    result.notes.append(
        "ADMIN_TELEGRAM_IDS requires a private /start message to the bot, then rerun --apply"
    )
    return None


def delete_webhook_for_getupdates(
    env: dict[str, str],
    http: HttpClient,
    result: BootstrapResult,
    *,
    drop_pending_updates: bool = False,
) -> None:
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        result.notes.append("deleteWebhook skipped: TELEGRAM_BOT_TOKEN missing")
        return
    try:
        response = http.post(
            f"https://api.telegram.org/bot{token}/deleteWebhook",
            json={"drop_pending_updates": drop_pending_updates},
            timeout=20.0,
        )
    except httpx.HTTPError:
        result.notes.append("telegram deleteWebhook: network_error")
        return
    if response.status_code >= 400:
        result.notes.append(_safe_error("telegram", "deleteWebhook", response))
        return
    result.notes.append("telegram deleteWebhook: ok")


def parse_models_response(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data", [])
    if not isinstance(data, list):
        return []
    models: list[str] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            models.append(item["id"])
    return models


def chat_smoke(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    http: HttpClient,
    result: BootstrapResult,
    extra_headers: dict[str, str] | None = None,
) -> bool:
    if not base_url or not api_key or not model:
        result.provider_status[provider] = "<missing>"
        return False
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **(extra_headers or {}),
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Ответь одним словом: тест"}],
        "max_tokens": 10,
    }
    try:
        response = http.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60.0,
        )
    except httpx.HTTPError:
        result.provider_status[provider] = "network_error"
        return False
    if response.status_code >= 400:
        result.provider_status[provider] = _safe_error(provider, "chat_completions", response)
        return False
    payload_response = response.json()
    choices = payload_response.get("choices")
    if not isinstance(choices, list) or not choices:
        result.provider_status[provider] = "invalid_response"
        return False
    result.provider_status[provider] = "chat_smoke_ok"
    return True


def choose_yandex_model(
    env: dict[str, str],
    http: HttpClient,
    result: BootstrapResult,
) -> str | None:
    base_url = env.get("YANDEX_AI_BASE_URL", YANDEX_DEFAULT_BASE_URL)
    api_key = env.get("YANDEX_AI_API_KEY", "")
    folder_id = env.get("YANDEX_AI_FOLDER_ID", "")
    existing_model = env.get("YANDEX_AI_MODEL", "")
    if existing_model:
        if chat_smoke(
            provider="yandex",
            base_url=base_url,
            api_key=api_key,
            model=existing_model,
            http=http,
            result=result,
            extra_headers={"x-folder-id": folder_id} if folder_id else None,
        ):
            return existing_model
        return None
    if not folder_id:
        result.notes.append(
            "YANDEX_AI_MODEL requires YANDEX_AI_FOLDER_ID or a manually configured model URI"
        )
        result.provider_status["yandex"] = "<missing>"
        return None
    candidates = [
        f"gpt://{folder_id}/qwen3-235b-a22b-fp8/latest",
        f"gpt://{folder_id}/gpt-oss-120b/latest",
    ]
    for candidate in candidates:
        if chat_smoke(
            provider="yandex",
            base_url=base_url,
            api_key=api_key,
            model=candidate,
            http=http,
            result=result,
            extra_headers={"x-folder-id": folder_id},
        ):
            return candidate
    result.notes.append(
        "YANDEX_AI_MODEL not selected; get available model URI from Yandex AI Studio "
        "or set it manually"
    )
    return None


def choose_openrouter_model(
    env: dict[str, str],
    http: HttpClient,
    result: BootstrapResult,
) -> str | None:
    base_url = (
        env.get("OPENROUTER_BASE_URL", OPENROUTER_DEFAULT_BASE_URL)
        or OPENROUTER_DEFAULT_BASE_URL
    )
    api_key = env.get("OPENROUTER_API_KEY", "")
    existing_model = env.get("OPENROUTER_MODEL", "")
    if not api_key:
        result.provider_status["openrouter"] = "<missing>"
        result.notes.append("OPENROUTER_MODEL requires OPENROUTER_API_KEY")
        return None
    models: list[str] = []
    try:
        response = http.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        if response.status_code < 400:
            models = parse_models_response(response.json())
        else:
            result.notes.append(_safe_error("openrouter", "models", response))
    except httpx.HTTPError:
        result.notes.append("openrouter models: network_error")

    if existing_model and chat_smoke(
        provider="openrouter",
        base_url=base_url,
        api_key=api_key,
        model=existing_model,
        http=http,
        result=result,
        extra_headers={"HTTP-Referer": env.get("PUBLIC_BASE_URL", ""), "X-Title": "Jarvis"},
    ):
        result.provider_status["openrouter"] = "OPENROUTER_READY"
        return existing_model

    if existing_model:
        result.notes.append(
            f"openrouter existing model failed: {existing_model} "
            f"{result.provider_status.get('openrouter', '<unknown>')}"
        )

    available_candidates = [model for model in OPENROUTER_PREFERRED_MODELS if model in models]
    if not available_candidates and models:
        available_candidates = models[:1]
    if not available_candidates:
        available_candidates = OPENROUTER_PREFERRED_MODELS[:1]
        result.notes.append(
            "openrouter models unavailable; selected first preferred candidate for smoke"
        )

    for selected in available_candidates:
        if selected == existing_model:
            continue
        if chat_smoke(
            provider="openrouter",
            base_url=base_url,
            api_key=api_key,
            model=selected,
            http=http,
            result=result,
            extra_headers={"HTTP-Referer": env.get("PUBLIC_BASE_URL", ""), "X-Title": "Jarvis"},
        ):
            result.provider_status["openrouter"] = "OPENROUTER_READY"
            return selected

    if result.provider_status.get("openrouter", "").startswith(
        "openrouter chat_completions: http_400"
    ):
        result.provider_status["openrouter"] = (
            "OPENROUTER_BLOCKED_HTTP_400 "
            f"{result.provider_status.get('openrouter', '')}"
        )
    else:
        result.provider_status["openrouter"] = (
            "OPENROUTER_BLOCKED_NO_WORKING_MODEL "
            f"{result.provider_status.get('openrouter', '')}"
        )
    return existing_model or (available_candidates[0] if available_candidates else None)


def _set_value(
    values: dict[str, str],
    updates: dict[str, str],
    result: BootstrapResult,
    key: str,
    value: str,
    status: str,
) -> None:
    values[key] = value
    updates[key] = value
    result.statuses[key] = status
    if status == "<generated>":
        result.generated.append(key)
    if status == "<derived>":
        result.derived.append(key)


def bootstrap_env(
    env_path: Path,
    example_path: Path,
    *,
    apply: bool = False,
    http: HttpClient | None = None,
    delete_webhook: bool = False,
    drop_pending_updates: bool = False,
) -> BootstrapResult:
    result = BootstrapResult(applied=apply)
    client: HttpClient = http or httpx.Client()
    if not env_path.exists():
        if apply and example_path.exists():
            shutil.copyfile(example_path, env_path)
            result.notes.append(".env created from .env.example")
        else:
            result.notes.append(".env missing; apply mode can create it from .env.example")

    values = parse_env_file(env_path)
    updates: dict[str, str] = {}

    if delete_webhook:
        delete_webhook_for_getupdates(
            values,
            client,
            result,
            drop_pending_updates=drop_pending_updates,
        )

    for key in REQUIRED_ENV_KEYS:
        result.statuses[key] = _status_for_value(values.get(key, ""))

    if not values.get("TELEGRAM_WEBHOOK_SECRET"):
        _set_value(
            values,
            updates,
            result,
            "TELEGRAM_WEBHOOK_SECRET",
            generate_telegram_webhook_secret(),
            "<generated>",
        )
    elif not is_valid_telegram_secret(values["TELEGRAM_WEBHOOK_SECRET"]):
        result.statuses["TELEGRAM_WEBHOOK_SECRET"] = "<invalid>"

    if not values.get("ADMIN_API_TOKEN"):
        _set_value(
            values,
            updates,
            result,
            "ADMIN_API_TOKEN",
            generate_admin_api_token(),
            "<generated>",
        )

    if not values.get("TELEGRAM_BOT_USERNAME"):
        username = derive_telegram_username(values, client, result)
        if username:
            _set_value(values, updates, result, "TELEGRAM_BOT_USERNAME", username, "<derived>")

    if not values.get("YANDEX_AI_BASE_URL"):
        _set_value(
            values,
            updates,
            result,
            "YANDEX_AI_BASE_URL",
            YANDEX_DEFAULT_BASE_URL,
            "<derived>",
        )

    if not values.get("YANDEX_AI_MODEL") or values.get("YANDEX_AI_API_KEY"):
        yandex_model = choose_yandex_model(values, client, result)
        if yandex_model and not values.get("YANDEX_AI_MODEL"):
            _set_value(values, updates, result, "YANDEX_AI_MODEL", yandex_model, "<derived>")
        elif yandex_model:
            result.statuses["YANDEX_AI_MODEL"] = "<set>"

    if not values.get("OPENROUTER_MODEL") or values.get("OPENROUTER_API_KEY"):
        openrouter_model = choose_openrouter_model(values, client, result)
        if openrouter_model and openrouter_model != values.get("OPENROUTER_MODEL"):
            _set_value(values, updates, result, "OPENROUTER_MODEL", openrouter_model, "<derived>")
        elif openrouter_model:
            result.statuses["OPENROUTER_MODEL"] = "<set>"

    if not values.get("ADMIN_TELEGRAM_IDS"):
        admin_id = derive_admin_telegram_id(values, client, result)
        if admin_id:
            _set_value(values, updates, result, "ADMIN_TELEGRAM_IDS", admin_id, "<derived>")

    for key in REQUIRED_ENV_KEYS:
        if not values.get(key):
            result.statuses[key] = "<missing>"
            result.blocked.append(key)

    if apply and updates:
        write_env_file(env_path, updates)
    elif updates:
        result.notes.append("dry-run: .env was not changed")

    result.verdict = compute_verdict(result)
    return result


def compute_verdict(result: BootstrapResult) -> str:
    if result.statuses.get("TELEGRAM_BOT_TOKEN") == "<missing>":
        return "BLOCKED_NEEDS_TELEGRAM_BOT_TOKEN"
    if result.statuses.get("ADMIN_TELEGRAM_IDS") == "<missing>":
        return "BLOCKED_NEEDS_MANUAL_TELEGRAM_START"
    if result.statuses.get("YANDEX_AI_MODEL") == "<missing>":
        return "BLOCKED_NEEDS_YANDEX_MODEL"
    if result.statuses.get("OPENROUTER_API_KEY") == "<missing>":
        return "BLOCKED_NEEDS_OPENROUTER_KEY"
    missing = [key for key in REQUIRED_ENV_KEYS if result.statuses.get(key) == "<missing>"]
    invalid = [key for key in REQUIRED_ENV_KEYS if result.statuses.get(key) == "<invalid>"]
    if missing or invalid:
        return "BLOCKED_NEEDS_REAL_ENV"
    return "PASS_STAGE_1R_ENV_READY"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap real local .env without printing secrets."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print sanitized plan without writing .env.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Write generated/derived missing values to .env.",
    )
    parser.add_argument(
        "--delete-webhook-for-getupdates",
        action="store_true",
        help="Explicitly delete Telegram webhook before getUpdates derivation.",
    )
    parser.add_argument(
        "--drop-pending-updates",
        action="store_true",
        help="Drop pending Telegram updates while deleting webhook.",
    )
    parser.add_argument("--env-file", default=".env", help=argparse.SUPPRESS)
    parser.add_argument("--example-file", default=".env.example", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    apply_mode = bool(args.apply)
    result = bootstrap_env(
        Path(args.env_file),
        Path(args.example_file),
        apply=apply_mode,
        delete_webhook=bool(args.delete_webhook_for_getupdates),
        drop_pending_updates=bool(args.drop_pending_updates),
    )
    print(result.render_sanitized())  # noqa: T201
    if result.verdict == "PASS_STAGE_1R_ENV_READY":
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
