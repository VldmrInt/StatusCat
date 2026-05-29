#!/usr/bin/env python3
"""Export current YouTrack assignments to JSON and optionally send Telegram report."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from html import escape
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_STATE = "In Progress"
DEFAULT_TELEGRAM_CHAT_ID = "6274298423"
TELEGRAM_MESSAGE_LIMIT = 4096
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
DEFAULT_ENV_FILE = ".env"
DEFAULT_FIELDS = (
    "idReadable,summary,customFields("
    "name,value(name,fullName,login)"
    ")"
)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


def load_issues(base_url: str, token: str, query: str, page_size: int) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    skip = 0

    while True:
        params = urlencode(
            {
                "query": query,
                "fields": DEFAULT_FIELDS,
                "$top": page_size,
                "$skip": skip,
            }
        )
        url = f"{base_url.rstrip('/')}/api/issues?{params}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )

        with urlopen(request, timeout=30) as response:
            page = json.loads(response.read().decode("utf-8"))

        if not page:
            break

        issues.extend(page)
        if len(page) < page_size:
            break
        skip += page_size

    return issues


def get_assignees(issue: dict[str, Any], field_name: str) -> list[str]:
    for field in issue.get("customFields", []):
        if field.get("name") != field_name:
            continue

        value = field.get("value")
        users = value if isinstance(value, list) else [value]
        result = []
        for user in users:
            if not isinstance(user, dict):
                continue
            name = user.get("fullName") or user.get("name") or user.get("login")
            if name:
                result.append(name)
        return result

    return []


def build_task_text(issue: dict[str, Any], base_url: str) -> str:
    task_id = issue.get("idReadable", "").strip()
    summary = issue.get("summary", "").strip()

    if not task_id:
        return summary

    task_url = f"{base_url.rstrip('/')}/issue/{task_id}"
    return f"{task_id}: {summary} ({task_url})" if summary else f"{task_id} ({task_url})"


def build_activity(
    issues: list[dict[str, Any]], assignee_field: str, base_url: str
) -> dict[str, list[str]]:
    activity: dict[str, list[str]] = {}

    for issue in issues:
        task = build_task_text(issue, base_url)

        if not task:
            continue

        for user in get_assignees(issue, assignee_field):
            activity.setdefault(user, []).append(task)

    return dict(sorted(activity.items(), key=lambda item: item[0].casefold()))


def build_query(state: str) -> str:
    return f"Assignee: * State: {{{state}}}"


def parse_task_text(task: str) -> tuple[str, str | None]:
    if not task.endswith(")"):
        return task, None

    marker = " ("
    text, separator, url = task.rpartition(marker)
    if not separator or not url.startswith(("http://", "https://")):
        return task, None

    return text, url[:-1]


def format_telegram_task(task: str) -> str:
    text, url = parse_task_text(task)
    if not url:
        return escape(text)
    return f'<a href="{escape(url, quote=True)}">{escape(text)}</a>'


def format_moscow_datetime(now: datetime | None = None) -> str:
    value = now.astimezone(MOSCOW_TZ) if now else datetime.now(MOSCOW_TZ)
    return value.strftime("%d.%m.%Y %H:%M:%S МСК")


def format_telegram_report(activity: dict[str, list[str]]) -> str:
    updated_at = format_moscow_datetime()

    if not activity:
        return (
            "<b>YouTrack: сейчас задач в работе нет</b>\n"
            f"Обновлено: <b>{updated_at}</b>"
        )

    task_count = sum(len(tasks) for tasks in activity.values())
    lines = [
        "<b>YouTrack: кто чем занят</b>",
        f"Обновлено: <b>{updated_at}</b>",
        f"Пользователей: <b>{len(activity)}</b>, задач: <b>{task_count}</b>",
        "",
    ]

    for user, tasks in activity.items():
        lines.append(f"<b>{escape(user)}</b>")
        for task in tasks:
            lines.append(f"  - {format_telegram_task(task)}")
        lines.append("")

    return "\n".join(lines).strip()


def split_message(message: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    parts: list[str] = []
    current = ""

    for line in message.splitlines():
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            parts.append(current)
        current = line

    if current:
        parts.append(current)

    return parts


def send_telegram_report(bot_token: str, chat_id: str, message: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    for part in split_message(message):
        payload = urlencode(
            {
                "chat_id": chat_id,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        request = Request(
            url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        with urlopen(request, timeout=30) as response:
            json.loads(response.read().decode("utf-8"))


def write_json(path: Path, data: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as temp_file:
        json.dump(data, temp_file, ensure_ascii=False, indent=2)
        temp_file.write("\n")
        temp_name = temp_file.name

    Path(temp_name).replace(path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    env_parser = argparse.ArgumentParser(add_help=False)
    env_parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    env_args, _ = env_parser.parse_known_args(argv)
    load_env_file(Path(env_args.env_file))

    parser = argparse.ArgumentParser(
        description="Write current YouTrack assignees and their tasks to JSON."
    )
    parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE,
        help=f"Path to .env file with settings. Default: {DEFAULT_ENV_FILE}",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="youtrack_activity.json",
        help="Output JSON path. Default: youtrack_activity.json",
    )
    parser.add_argument(
        "-q",
        "--query",
        default=os.getenv("YOUTRACK_QUERY"),
        help="Full YouTrack search query. Overrides --state.",
    )
    parser.add_argument(
        "--state",
        default=os.getenv("YOUTRACK_STATE", DEFAULT_STATE),
        help=f"State that means the task is currently in work. Default: {DEFAULT_STATE}",
    )
    parser.add_argument(
        "--assignee-field",
        default=os.getenv("YOUTRACK_ASSIGNEE_FIELD", "Assignee"),
        help="Assignee custom field name. Default: Assignee",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=int(os.getenv("YOUTRACK_PAGE_SIZE", "100")),
        help="YouTrack API page size. Default: 100",
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=os.getenv("TELEGRAM_CHAT_ID", DEFAULT_TELEGRAM_CHAT_ID),
        help=f"Telegram chat/user id. Default: {DEFAULT_TELEGRAM_CHAT_ID}",
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Do not send Telegram report even if TELEGRAM_BOT_TOKEN is set.",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    base_url = os.getenv("YOUTRACK_URL")
    token = os.getenv("YOUTRACK_TOKEN")

    if not base_url or not token:
        print(
            "Set YOUTRACK_URL and YOUTRACK_TOKEN environment variables first.",
            file=sys.stderr,
        )
        return 2

    try:
        query = args.query or build_query(args.state)
        issues = load_issues(base_url, token, query, args.page_size)
        activity = build_activity(issues, args.assignee_field, base_url)
        write_json(Path(args.output), activity)

        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if telegram_token and not args.no_telegram:
            send_telegram_report(
                telegram_token,
                args.telegram_chat_id,
                format_telegram_report(activity),
            )
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        print(f"HTTP error {error.code}: {details}", file=sys.stderr)
        return 1
    except URLError as error:
        print(f"Connection error: {error.reason}", file=sys.stderr)
        return 1

    print(f"Written {len(activity)} users to {args.output}")
    if os.getenv("TELEGRAM_BOT_TOKEN") and not args.no_telegram:
        print(f"Sent Telegram report to {args.telegram_chat_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
