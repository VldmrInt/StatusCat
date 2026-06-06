# StatusCat

StatusCat выгружает текущие задачи из YouTrack, группирует их по исполнителям и
опционально отправляет отчет в Telegram.

Скрипт формирует три JSON-отчета:

- `youtrack_activity.json` - задачи в работе, сгруппированные по исполнителям.
- `youtrack_testing.json` - задачи на тестировании с приоритетами и датами перехода.
- `youtrack_review.json` - задачи на ревью за последние N дней.

## Возможности

- Загрузка настроек из `.env`.
- Настраиваемые названия статусов и полей YouTrack.
- Отдельные запросы для задач в работе, на тестировании и на ревью.
- Отправка HTML-отчета в Telegram.
- Разделение задач выбранного проекта в отдельное Telegram-сообщение.
- Пагинация YouTrack API и повтор запросов при временных сетевых ошибках.

## Требования

- Python 3.9 или новее.
- Постоянный токен YouTrack с доступом к нужным задачам.
- Telegram-бот, если нужна отправка отчета в Telegram.

Внешние Python-зависимости не требуются, используется только стандартная
библиотека.

## Быстрый старт

Скопируйте пример настроек:

```powershell
Copy-Item .\.env.example .\.env
notepad .\.env
```

Заполните минимум:

```text
YOUTRACK_URL=https://your-company.youtrack.cloud
YOUTRACK_TOKEN=perm-...
```

Запустите выгрузку:

```powershell
python .\youtrack_activity.py
```

После успешного запуска в рабочей папке появятся JSON-отчеты. Эти файлы
являются локальными результатами выполнения и не должны коммититься.

## Настройки

Все настройки можно передать через `.env` или аргументы командной строки.
Аргументы командной строки имеют приоритет.

| Переменная | Аргумент | Назначение |
| --- | --- | --- |
| `YOUTRACK_URL` | - | URL YouTrack, например `https://your-company.youtrack.cloud`. |
| `YOUTRACK_TOKEN` | - | Постоянный токен YouTrack. |
| `YOUTRACK_QUERY` | `--query` | Полный запрос для задач в работе. |
| `YOUTRACK_STATE` | `--state` | Статус задач в работе. |
| `YOUTRACK_TESTING_QUERY` | `--testing-query` | Полный запрос для задач на тестировании. |
| `YOUTRACK_TESTING_STATE` | `--testing-state` | Статус задач на тестировании. |
| `YOUTRACK_REVIEW_QUERY` | `--review-query` | Полный запрос для задач на ревью. |
| `YOUTRACK_REVIEW_STATE` | `--review-state` | Статус задач на ревью. |
| `YOUTRACK_REVIEW_DAYS` | `--review-days` | Сколько последних дней включать в ревью-отчет. |
| `YOUTRACK_STATE_FIELD` | `--state-field` | Название поля статуса в YouTrack. |
| `YOUTRACK_ASSIGNEE_FIELD` | `--assignee-field` | Название поля исполнителя. |
| `YOUTRACK_PRIORITY_FIELD` | `--priority-field` | Название поля приоритета. |
| `YOUTRACK_PAGE_SIZE` | `--page-size` | Размер страницы для YouTrack API. |
| `YOUTRACK_SEPARATE_PROJECT` | `--separate-project` | Ключ проекта для отдельного Telegram-отчета. |
| `TELEGRAM_BOT_TOKEN` | - | Токен Telegram-бота. |
| `TELEGRAM_CHAT_ID` | `--telegram-chat-id` | ID чата или пользователя для отправки отчета. |

Дополнительные аргументы:

- `--env-file .\.env.local` - использовать другой файл настроек.
- `--output .\activity.json` - изменить файл отчета по исполнителям.
- `--testing-output .\testing.json` - изменить файл отчета по тестированию.
- `--review-output .\review.json` - изменить файл отчета по ревью.
- `--no-telegram` - не отправлять отчет в Telegram для текущего запуска.

## Примеры

Выгрузить задачи со статусом `В работе`:

```powershell
python .\youtrack_activity.py --state "В работе"
```

Задать полный YouTrack-запрос:

```powershell
python .\youtrack_activity.py -q "project: ABC Assignee: * State: {В работе}"
```

Изменить период ревью:

```powershell
python .\youtrack_activity.py --review-state "Ревью" --review-days 14
```

Отключить разделение проекта на отдельное Telegram-сообщение:

```powershell
python .\youtrack_activity.py --separate-project ""
```

## Telegram

Чтобы включить отправку:

1. Создайте бота через BotFather.
2. Добавьте токен в `TELEGRAM_BOT_TOKEN`.
3. Укажите `TELEGRAM_CHAT_ID`.
4. Если отправляете отчет пользователю лично, пользователь должен хотя бы один
   раз написать боту.

Если `TELEGRAM_BOT_TOKEN` не задан, скрипт только обновит JSON-файлы.

## Формат отчетов

`youtrack_activity.json`:

```json
{
  "Иван Иванов": [
    "ABC-123: Починить авторизацию (https://your-company.youtrack.cloud/issue/ABC-123)"
  ]
}
```

`youtrack_testing.json` и `youtrack_review.json`:

```json
[
  {
    "task": "ABC-124: Проверить авторизацию (https://your-company.youtrack.cloud/issue/ABC-124)",
    "priority": "High",
    "state_changed_at": "03.06.2026"
  }
]
```

## Что не коммитить

В репозиторий не должны попадать:

- `.env` и другие локальные env-файлы с токенами.
- Сгенерированные отчеты `youtrack_activity.json`, `youtrack_testing.json`,
  `youtrack_review.json`.
- Python-кэши, виртуальные окружения, логи и временные файлы редакторов.

Актуальные правила находятся в `.gitignore`.
