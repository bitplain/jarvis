# Hotfix: web search follow-up and Telegram formatting

Дата: 2026-06-27

## Симптомы

1. `Покажи погоду в Москве` не попадал в web search и уходил в generic LLM path.
2. После vague search вроде `Найди в интернете погода на сегодня` уточнение `Москва` или `Покажи погоду в Москве` не продолжало search flow.
3. Финальный Telegram ответ web search мог показывать raw Markdown markers, например `**Сейчас:**`.
4. `/settings -> Интернет-поиск` мог показывать `Статус: включён` вместе с `Provider: disabled`.

## Root cause

- Parser Stage 4K распознавал только старые prefix-команды (`найди`, `поищи`, `проверь в интернете`, `что нового по`) и не считал явные weather/current-info фразы search intent.
- Short-lived clarification state для vague explicit search отсутствовал, поэтому следующий ответ пользователя шёл как обычное сообщение.
- Worker отправлял web-search answer обычным Telegram text без HTML-safe post-processing, поэтому markdown markers от LLM могли стать видимым текстом.
- Settings renderer считал `web_search.enabled=true` достаточным для статуса `включён`, даже если provider/key фактически не настроены.

## Поведение до/после

До:

- `Покажи погоду в Москве` мог попасть в generic LLM path.
- `Москва` после weather clarification не восстанавливал исходный intent.
- `**bold**` мог уйти в Telegram как сырой markdown.
- `enabled + disabled provider` выглядел как включённый web search.

После:

- `Покажи погоду в Москве`, `погода в Москве сегодня`, `какая погода в Москве сейчас`, `покажи курс доллара`, `покажи новости про Telegram` распознаются как explicit web search.
- Vague explicit search создаёт Redis pending clarification на 10 минут; follow-up `Москва` превращается в `погода Москва сегодня`, а `Telegram` после `новости` — в `новости Telegram`.
- `/cancel` очищает pending clarification.
- Web-search Telegram answer форматируется как safe HTML, provider/model text экранируется, unsafe links не превращаются в HTML links, HTML send failure имеет один plain fallback.
- Если provider `disabled` или key отсутствует при включённом поиске, UI показывает `Статус: не настроен`, а runtime отвечает `Интернет-поиск не настроен: выберите provider и добавьте API key.`

## Граница без watcher/auto-search

Hotfix не включает Smart Watcher, auto-search на любые сообщения, чтение всех group messages, browser automation, page fetching, Railway Variables changes, Telegram Business changes или live destructive Telegram methods.

Обычные сообщения `Привет`, `Кто ты?`, `Помоги со списком` остаются вне web search.
Group/supergroup search по-прежнему работает только после mention/reply и текущей access policy.

## Тесты

- Intent parser: новые weather/current-info фразы и negative normal messages.
- Router: private explicit weather, vague weather clarification, city follow-up, explicit follow-up, `/cancel`, expired clarification, Redis fail-open, group mention search, group non-mention no search.
- Formatting: raw `**` не отправляется, provider `<script>` escaping, unsafe markdown link rejected.
- Worker: web-search answer отправляется HTML, HTML send failure делает plain fallback.
- Service/settings: secret-like query не уходит provider/cache, `enabled + disabled provider` даёт config error, settings screen показывает `Статус: не настроен`.
- Smoke: `scripts/smoke_web_search_followup_formatting_readiness.py`.

## Live checklist

После merge/deploy вручную проверить:

1. `/settings -> Интернет-поиск`: `Статус: включён`, `Provider: tavily`, `Режим: только явные команды`.
2. `Покажи погоду в Москве` запускает web search и отвечает по источникам.
3. `Найди в интернете погода на сегодня` просит город; follow-up `Москва` запускает `погода Москва сегодня`.
4. `Найди в интернете и покажи мне погоду в Москве` продолжает работать.
5. `Привет` не запускает search.
6. В группе `@bot_username покажи погоду в Москве` запускает search, а plain group non-mention не запускает.
7. В ответе нет raw `**`, `__` или сырого `[title](url)`.
