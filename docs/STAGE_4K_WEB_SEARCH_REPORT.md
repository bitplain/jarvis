# Stage 4K Web Search Report

## Архитектура

Stage 4K добавляет provider-agnostic интернет-поиск как отдельный инструмент Jarvis.
Поток такой:

1. Private/group router распознаёт только явную команду поиска.
2. Worker вызывает отдельный search provider.
3. Jarvis собирает snippets-only context из безопасных URL.
4. Context передаётся в текущий LLM provider как обычные `LLMMessage`.
5. Telegram ответ получает deterministic список источников.

LLM provider не получает прямой доступ в интернет.
Одинаковый context работает с Yandex, OpenRouter, OpenAI-compatible и будущими providers.

## Providers

Поддержаны provider names:

- `disabled`
- `tavily`
- `brave`

Ключи задаются только через env/Railway Variables, значения не логируются и не документируются:

- `WEB_SEARCH_PROVIDER`
- `TAVILY_API_KEY`
- `BRAVE_SEARCH_API_KEY`

Если provider включён без ключа, пользователь получает безопасную русскую ошибку, а `/settings -> Интернет-поиск` показывает degraded status без значения ключа.

## Команды

Поддержаны только explicit triggers:

- `найди ...`
- `поищи ...`
- `проверь в интернете ...`
- `посмотри в интернете ...`
- `что нового по ...`
- `найди актуальную информацию ...`

В group/supergroup команда работает только через mention/reply по текущей access policy.
Обычные сообщения без explicit trigger не запускают search.

## Настройки

Admin-only путь: `/settings -> Интернет-поиск`.

Runtime settings:

- `web_search.enabled`
- `web_search.provider`
- `web_search.max_results`

UI показывает:

- статус включён/выключен;
- provider;
- режим `только явные команды`;
- максимум источников;
- примеры команд.

## Cache

PostgreSQL таблица: `web_search_cache`.

Поля:

- `id`
- `provider`
- `query_hash`
- `query_text`
- `results_json`
- `created_at`
- `expires_at`

Уникальность: `(provider, query_hash)`.
TTL: 1 час по умолчанию, 30 минут для новостных/актуальных запросов.
Provider error не cache-ится.

## Safety

URL safety отбрасывает:

- `localhost`;
- `127.0.0.0/8`;
- `10.0.0.0/8`;
- `172.16.0.0/12`;
- `192.168.0.0/16`;
- link-local;
- `169.254.169.254`;
- non-http/https schemes;
- пустые или подозрительные hosts.

Stage 4K использует snippets-only search API и не fetch-ит страницы.
Логи не содержат full query text, API keys, Authorization headers, provider response body или private message text.

## Не входит в Stage 4K

- auto-search на все вопросы;
- watcher;
- browser automation;
- выполнение кода со страниц;
- scraping private/auth/paywalled pages;
- обход login/paywall;
- локальные/private IP URLs;
- voice/media;
- Telegram Business.

## Проверки

Добавлен smoke:

```bash
uv run --python 3.12 --extra dev python scripts/smoke_web_search_readiness.py
```

Ожидаемый verdict:

```text
PASS_WEB_SEARCH_READINESS
```
