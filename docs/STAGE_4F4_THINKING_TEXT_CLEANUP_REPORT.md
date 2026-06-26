# Stage 4F-4 Thinking Text Cleanup

## Цель

Убрать старые accepted/provisional тексты и оставить единый короткий thinking text `Думаю`.

## Изменения

- Private webhook enqueue без Mira draft отвечает `Думаю`.
- Private webhook enqueue с Mira draft не отправляет отдельное обычное сообщение: thinking остаётся в rich/text draft path worker.
- Private draft fallback использует `Думаю`.
- Group/supergroup fallback использует обычное provisional message `Думаю`; Mira-style draft animation в group не применяется.
- Финальная доставка, group final dedup и safe `message is not modified` поведение не менялись.

## Границы

- Railway Variables не менялись.
- Prompt Profiles, Access Settings, webhook self-healing, watcher, shopping list, reminders и PR #5 не менялись.
- Guest Mode остаётся final-only.

## Live checklist

- Private с Mira enabled: виден draft/rich draft `Думаю`, отдельного обычного accepted message нет.
- Private final: финальный ответ отправляется один раз.
- Group mention/reply: появляется обычное provisional message `Думаю`.
- Group final: финальный ответ delivered once через edit или fallback send.
- `/start`, `/settings`, `/whoami`, prompt/access FSM: `Думаю` не показывается.
