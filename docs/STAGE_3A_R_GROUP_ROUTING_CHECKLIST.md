# Stage 3A-R Group Routing Checklist

## Ручные требования

1. Бот должен быть добавлен в тестовую Telegram group или supergroup как участник.
2. В BotFather нужно проверить:
   - `/setjoingroups` разрешает добавление бота в группы;
   - privacy mode:
     - для минимального теста reply/command mention privacy mode может быть включён;
     - для plain `@bot_username` text нужно явно проверить оба режима:
       - privacy enabled;
       - privacy disabled.
3. После изменения privacy mode лучше удалить и заново добавить бота в тестовую группу, потому что Telegram иногда применяет group privacy не мгновенно, будто это ритуал, а не настройка.
4. Для privacy enabled ожидаемо тестировать:
   - `/status@bot_username`;
   - reply на сообщение бота;
   - `@bot_username текст`, только если Telegram реально доставляет такой update в этом чате.
5. Для privacy disabled ожидаемо тестировать:
   - обычное сообщение без mention/reply должно прийти в polling, но бот обязан его проигнорировать на уровне кода;
   - `@bot_username текст` должен обрабатываться;
   - reply на сообщение бота должен обрабатываться.

## Что засчитывается как Group Assistant evidence

- update приходит как обычный Telegram `message`, не как `guest_message`;
- `chat.type` равен `group` или `supergroup`;
- plain message без mention/reply не создаёт regular memory row и не ставит LLM job;
- text mention или reply-to-bot создают regular memory row по group chat id;
- worker получает `process_llm_message` с `private=false`;
- ответ виден в группе;
- Guest tables и Business tables не получают regular group-сообщения.

## Что не засчитывается

- вызов через `@bot_username` в чужом чате, доставленный Telegram как `guest_message`;
- synthetic webhook/update payload;
- private chat с ботом;
- обычный чат пользователя с другим человеком, где бот не является участником;
- сообщение, которое пользователь видит в Telegram UI, но polling runner не получает как group/supergroup `message`.
