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
YOUTRACK_ASSIGNEE_FIELD=Assignee
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
Если задан `TELEGRAM_BOT_TOKEN`, после обновления JSON скрипт отправит красиво
отформатированный отчет в Telegram: с датой-временем обновления по Москве и
кликабельными ссылками на задачи.

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

Если поле исполнителя в YouTrack называется не `Assignee`, укажите его явно:

```powershell
python .\youtrack_activity.py --assignee-field "Исполнитель"
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
