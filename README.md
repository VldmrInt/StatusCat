# YouTrack activity export

Минимальный скрипт, который выгружает из YouTrack список задач в работе
и записывает JSON в формате:

```json
{
  "Иван Иванов": [
    "ABC-123: Починить авторизацию (https://your-company.youtrack.cloud/issue/ABC-123)"
  ]
}
```

## Настройка через файл

Скопируйте `.env.example` в `.env` и заполните значения:

```powershell
Copy-Item .\.env.example .\.env
notepad .\.env
```

Пример `.env`:

```text
YOUTRACK_URL=https://your-company.youtrack.cloud
YOUTRACK_TOKEN=perm-...
YOUTRACK_STATE=В работе
YOUTRACK_TESTING_STATE=Тестирование
YOUTRACK_REVIEW_STATE=Ревью
YOUTRACK_REVIEW_DAYS=7
YOUTRACK_STATE_FIELD=State
YOUTRACK_ASSIGNEE_FIELD=Assignee
YOUTRACK_PRIORITY_FIELD=Priority
YOUTRACK_PAGE_SIZE=100

TELEGRAM_BOT_TOKEN=123456789:AA...
TELEGRAM_CHAT_ID=6274298423
```

Для Telegram создайте бота через BotFather и вставьте токен в `TELEGRAM_BOT_TOKEN`.
По умолчанию отчет отправляется пользователю с id из `TELEGRAM_CHAT_ID`.
Пользователь должен хотя бы один раз написать боту сам, иначе Telegram не разрешит
боту отправить личное сообщение.

## Запуск

```powershell
python .\youtrack_activity.py
```

По умолчанию скрипт ищет задачи по запросу:

```text
Assignee: * State: {In Progress}
```

И создает или обновляет файл `youtrack_activity.json`.
Отдельный список задач на тестировании с приоритетами записывается в
`youtrack_testing.json`. Список задач на ревью, обновленных за последние 7 дней,
записывается в `youtrack_review.json`.

```json
[
  {
    "task": "ABC-124: Проверить авторизацию (https://your-company.youtrack.cloud/issue/ABC-124)",
    "priority": "High",
    "state_changed_at": "03.06.2026"
  }
]
```

Если задан `TELEGRAM_BOT_TOKEN`, после обновления JSON скрипт отправит красиво
отформатированный отчет в Telegram: с датой-временем обновления по Москве,
кликабельными ссылками на задачи и отдельным списком задач в статусе
`Тестирование` с их приоритетами и датами перехода в статус, а также списком
задач на ревью не старше 7 дней с датами перехода в статус.

Если в вашем YouTrack статус называется `В работе`, запускайте так:

```powershell
python .\youtrack_activity.py --state "В работе"
```

Или укажите это в `.env`:

```text
YOUTRACK_STATE=В работе
```

Можно указать другой файл или запрос:

```powershell
python .\youtrack_activity.py -o .\activity.json -q "project: ABC Assignee: * State: {В работе}"
```

Можно указать другой файл для списка задач на тестировании:

```powershell
python .\youtrack_activity.py --testing-output .\testing.json
```

Можно указать другой файл для списка задач на ревью:

```powershell
python .\youtrack_activity.py --review-output .\review.json
```

Если поле исполнителя в YouTrack называется не `Assignee`, укажите его явно:

```powershell
python .\youtrack_activity.py --assignee-field "Исполнитель"
```

Если поле статуса в YouTrack называется не `State`, укажите его явно. Это нужно
для поиска даты перехода задачи в статусы тестирования и ревью:

```powershell
python .\youtrack_activity.py --state-field "Статус"
```

Если поле приоритета называется не `Priority`, укажите его явно:

```powershell
python .\youtrack_activity.py --priority-field "Приоритет"
```

Если статус тестирования в YouTrack называется иначе, укажите его через аргумент
или `.env`:

```powershell
python .\youtrack_activity.py --testing-state "Ready for QA"
```

Можно задать полный запрос для списка тестирования:

```powershell
python .\youtrack_activity.py --testing-query "project: ABC State: {Тестирование}"
```

По умолчанию список ревью строится по запросу:

```text
State: {Ревью} updated: {minus 7d} .. *
```

Если статус ревью в YouTrack называется иначе или нужен другой период:

```powershell
python .\youtrack_activity.py --review-state "Code Review" --review-days 7
```

Можно задать полный запрос для списка ревью:

```powershell
python .\youtrack_activity.py --review-query "project: ABC State: {Ревью} updated: {minus 7d} .. *"
```

Отправить в другой чат:

```powershell
python .\youtrack_activity.py --telegram-chat-id "123456789"
```

Отключить отправку в Telegram для одного запуска:

```powershell
python .\youtrack_activity.py --no-telegram
```

Использовать другой файл настроек:

```powershell
python .\youtrack_activity.py --env-file .\.env.local
```
