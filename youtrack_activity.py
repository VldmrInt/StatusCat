#!/usr/bin/env python3
"""Export current YouTrack assignments to JSON and optionally send Telegram report."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from html import escape
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


DEFAULT_STATE = "In Progress"
DEFAULT_TESTING_STATE = "Тестирование"
DEFAULT_REVIEW_STATE = "Ревью"
DEFAULT_REVIEW_DAYS = 7
DEFAULT_SEPARATE_PROJECT = "scalebay"
DEFAULT_PRIORITY_FIELD = "Priority"
DEFAULT_TELEGRAM_CHAT_ID = "6274298423"
TELEGRAM_MESSAGE_LIMIT = 4096
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
DEFAULT_ENV_FILE = ".env"
DEFAULT_FIELDS = (
    "idReadable,summary,customFields("
    "name,value(name,fullName,login)"
    ")"
)
DEFAULT_ACTIVITY_FIELDS = (
    "id,timestamp,targetMember,field(name),"
    "added(name,localizedName,fullName,login),"
    "removed(name,localizedName,fullName,login)"
)
HTTP_RETRY_COUNT = 3
HTTP_RETRY_DELAY_SECONDS = 2


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


def load_json(request: Request) -> Any:
    for attempt in range(HTTP_RETRY_COUNT):
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError:
            raise
        except (TimeoutError, URLError):
            if attempt == HTTP_RETRY_COUNT - 1:
                raise
            time.sleep(HTTP_RETRY_DELAY_SECONDS * (attempt + 1))

    raise RuntimeError("Unexpected request retry state.")


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


def load_issue_activities(
    base_url: str, token: str, issue_id: str, page_size: int
) -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    skip = 0

    while True:
        params = urlencode(
            {
                "fields": DEFAULT_ACTIVITY_FIELDS,
                "categories": "CustomFieldCategory",
                "reverse": "true",
                "$top": page_size,
                "$skip": skip,
            }
        )
        encoded_issue_id = quote(issue_id, safe="")
        url = f"{base_url.rstrip('/')}/api/issues/{encoded_issue_id}/activities?{params}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )

        page = load_json(request)

        if not page:
            break

        activities.extend(page)
        if len(page) < page_size:
            break
        skip += page_size

    return activities


def get_assignees(issue: dict[str, Any], field_name: str) -> list[str]:
    value = get_custom_field_value(issue, field_name)
    users = value if isinstance(value, list) else [value]
    result = []
    for user in users:
        if not isinstance(user, dict):
            continue
        name = user.get("fullName") or user.get("name") or user.get("login")
        if name:
            result.append(name)
    return result


def get_custom_field_value(issue: dict[str, Any], field_name: str) -> Any:
    for field in issue.get("customFields", []):
        if field.get("name") == field_name:
            return field.get("value")

    return None


def get_field_display_value(issue: dict[str, Any], field_name: str) -> str:
    value = get_custom_field_value(issue, field_name)
    if isinstance(value, dict):
        return str(value.get("name") or value.get("fullName") or value.get("login") or "")
    if isinstance(value, list):
        values = [
            str(item.get("name") or item.get("fullName") or item.get("login") or item)
            if isinstance(item, dict)
            else str(item)
            for item in value
            if item
        ]
        return ", ".join(value for value in values if value)
    return str(value or "")


def get_activity_value_display(value: Any) -> str:
    if isinstance(value, dict):
        return str(
            value.get("localizedName")
            or value.get("name")
            or value.get("fullName")
            or value.get("login")
            or ""
        )
    return str(value or "")


def get_activity_value_displays(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [display for item in values if (display := get_activity_value_display(item))]


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


def build_priority_tasks(
    issues: list[dict[str, Any]],
    priority_field: str,
    base_url: str,
    state_changed_at_by_issue: dict[str, str | None] | None = None,
) -> list[dict[str, str]]:
    tasks: list[dict[str, str]] = []

    for issue in issues:
        task = build_task_text(issue, base_url)
        if not task:
            continue

        item = {
            "task": task,
            "priority": get_field_display_value(issue, priority_field)
            or "Без приоритета",
        }
        if state_changed_at_by_issue is not None:
            item["state_changed_at"] = (
                state_changed_at_by_issue.get(issue.get("idReadable", "")) or ""
            )
        tasks.append(item)

    return sorted(
        tasks,
        key=lambda item: (item["priority"].casefold(), item["task"].casefold()),
    )


def build_query(state: str) -> str:
    return f"Assignee: * State: {{{state}}}"


def build_state_query(state: str) -> str:
    return f"State: {{{state}}}"


def build_recent_state_query(state: str, days: int) -> str:
    return f"State: {{{state}}} updated: {{minus {days}d}} .. *"


def find_state_transition_timestamp(
    activities: list[dict[str, Any]], state_field: str, state: str
) -> int | None:
    state_casefold = state.casefold()
    state_field_casefold = state_field.casefold()

    for activity in activities:
        field = activity.get("field")
        field_name = field.get("name") if isinstance(field, dict) else None
        target_member = activity.get("targetMember")
        is_state_field = (
            isinstance(field_name, str) and field_name.casefold() == state_field_casefold
        ) or (
            isinstance(target_member, str)
            and target_member.casefold() == state_field_casefold
        ) or (
            isinstance(target_member, str)
            and target_member.startswith("__CUSTOM_FIELD__State_")
        )
        if not is_state_field:
            continue

        added_values = get_activity_value_displays(activity.get("added"))
        if any(value.casefold() == state_casefold for value in added_values):
            timestamp = activity.get("timestamp")
            return timestamp if isinstance(timestamp, int) else None

    return None


def format_moscow_date(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return ""
    value = datetime.fromtimestamp(timestamp_ms / 1000, tz=MOSCOW_TZ)
    return value.strftime("%d.%m.%Y")


def build_state_changed_at_by_issue(
    issues: list[dict[str, Any]],
    base_url: str,
    token: str,
    page_size: int,
    state_field: str,
    state: str,
) -> dict[str, str | None]:
    result: dict[str, str | None] = {}

    for issue in issues:
        issue_id = issue.get("idReadable", "")
        if not issue_id:
            continue

        activities = load_issue_activities(base_url, token, issue_id, page_size)
        result[issue_id] = format_moscow_date(
            find_state_transition_timestamp(activities, state_field, state)
        )

    return result


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


def get_task_project(task: str) -> str:
    task_text, _ = parse_task_text(task)
    task_id = task_text.split(":", 1)[0].strip()
    project, separator, _ = task_id.partition("-")
    return project.casefold() if separator else ""


def is_project_task(task: str, project: str) -> bool:
    return bool(project) and get_task_project(task) == project.casefold()


def split_activity_by_project(
    activity: dict[str, list[str]], project: str
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    other_activity: dict[str, list[str]] = {}
    project_activity: dict[str, list[str]] = {}

    for user, tasks in activity.items():
        other_tasks = [task for task in tasks if not is_project_task(task, project)]
        project_tasks = [task for task in tasks if is_project_task(task, project)]
        if other_tasks:
            other_activity[user] = other_tasks
        if project_tasks:
            project_activity[user] = project_tasks

    return other_activity, project_activity


def split_priority_tasks_by_project(
    tasks: list[dict[str, str]], project: str
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    other_tasks = [item for item in tasks if not is_project_task(item["task"], project)]
    project_tasks = [item for item in tasks if is_project_task(item["task"], project)]
    return other_tasks, project_tasks


def has_report_items(
    activity: dict[str, list[str]],
    testing_tasks: list[dict[str, str]],
    review_tasks: list[dict[str, str]],
) -> bool:
    return bool(activity or testing_tasks or review_tasks)


def format_telegram_report(
    activity: dict[str, list[str]],
    testing_tasks: list[dict[str, str]],
    review_tasks: list[dict[str, str]],
    review_days: int,
    title: str = "YouTrack: кто чем занят",
) -> str:
    updated_at = format_moscow_datetime()

    if not activity and not testing_tasks and not review_tasks:
        return (
            "<b>YouTrack: сейчас задач в работе, на тестировании и на ревью нет</b>\n"
            f"Обновлено: <b>{updated_at}</b>"
        )

    task_count = sum(len(tasks) for tasks in activity.values())
    lines = [
        f"<b>{escape(title)}</b>",
        f"Обновлено: <b>{updated_at}</b>",
        (
            f"Пользователей: <b>{len(activity)}</b>, "
            f"задач в работе: <b>{task_count}</b>, "
            f"на тестировании: <b>{len(testing_tasks)}</b>, "
            f"на ревью до {review_days} дней: <b>{len(review_tasks)}</b>"
        ),
        "",
    ]

    if activity:
        for user, tasks in activity.items():
            lines.append(f"<b>{escape(user)}</b>")
            for task in tasks:
                lines.append(f"  - {format_telegram_task(task)}")
            lines.append("")

    if testing_tasks:
        lines.append("<b>Тестирование</b>")
        for item in testing_tasks:
            priority = escape(item["priority"])
            changed_at = item.get("state_changed_at")
            date_text = f", с {escape(changed_at)}" if changed_at else ""
            lines.append(f"  - [{priority}{date_text}] {format_telegram_task(item['task'])}")
        lines.append("")

    if review_tasks:
        lines.append(f"<b>Ревью до {review_days} дней</b>")
        for item in review_tasks:
            priority = escape(item["priority"])
            changed_at = item.get("state_changed_at")
            date_text = f", с {escape(changed_at)}" if changed_at else ""
            lines.append(f"  - [{priority}{date_text}] {format_telegram_task(item['task'])}")
        lines.append("")

    return "\n".join(lines).strip()


def format_telegram_reports(
    activity: dict[str, list[str]],
    testing_tasks: list[dict[str, str]],
    review_tasks: list[dict[str, str]],
    review_days: int,
    separate_project: str,
) -> list[str]:
    project = separate_project.strip()
    if not project:
        return [
            format_telegram_report(activity, testing_tasks, review_tasks, review_days)
        ]

    other_activity, project_activity = split_activity_by_project(activity, project)
    other_testing_tasks, project_testing_tasks = split_priority_tasks_by_project(
        testing_tasks,
        project,
    )
    other_review_tasks, project_review_tasks = split_priority_tasks_by_project(
        review_tasks,
        project,
    )

    reports: list[str] = []
    if has_report_items(other_activity, other_testing_tasks, other_review_tasks):
        reports.append(
            format_telegram_report(
                other_activity,
                other_testing_tasks,
                other_review_tasks,
                review_days,
            )
        )

    if has_report_items(project_activity, project_testing_tasks, project_review_tasks):
        reports.append(
            format_telegram_report(
                project_activity,
                project_testing_tasks,
                project_review_tasks,
                review_days,
                title=f"YouTrack: {project}",
            )
        )

    return reports or [
        format_telegram_report(activity, testing_tasks, review_tasks, review_days)
    ]


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


def write_json(path: Path, data: Any) -> None:
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
        "--testing-output",
        default="youtrack_testing.json",
        help="Testing tasks JSON path. Default: youtrack_testing.json",
    )
    parser.add_argument(
        "--review-output",
        default="youtrack_review.json",
        help="Review tasks JSON path. Default: youtrack_review.json",
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
        "--testing-state",
        default=os.getenv("YOUTRACK_TESTING_STATE", DEFAULT_TESTING_STATE),
        help=(
            "State that means the task is currently in testing. "
            f"Default: {DEFAULT_TESTING_STATE}"
        ),
    )
    parser.add_argument(
        "--testing-query",
        default=os.getenv("YOUTRACK_TESTING_QUERY"),
        help="Full YouTrack search query for testing tasks. Overrides --testing-state.",
    )
    parser.add_argument(
        "--review-state",
        default=os.getenv("YOUTRACK_REVIEW_STATE", DEFAULT_REVIEW_STATE),
        help=f"State that means the task is currently on review. Default: {DEFAULT_REVIEW_STATE}",
    )
    parser.add_argument(
        "--review-days",
        type=int,
        default=int(os.getenv("YOUTRACK_REVIEW_DAYS", str(DEFAULT_REVIEW_DAYS))),
        help=f"How many recent days to include for review tasks. Default: {DEFAULT_REVIEW_DAYS}",
    )
    parser.add_argument(
        "--review-query",
        default=os.getenv("YOUTRACK_REVIEW_QUERY"),
        help="Full YouTrack search query for review tasks. Overrides --review-state and --review-days.",
    )
    parser.add_argument(
        "--state-field",
        default=os.getenv("YOUTRACK_STATE_FIELD", "State"),
        help="State custom field name. Default: State",
    )
    parser.add_argument(
        "--assignee-field",
        default=os.getenv("YOUTRACK_ASSIGNEE_FIELD", "Assignee"),
        help="Assignee custom field name. Default: Assignee",
    )
    parser.add_argument(
        "--priority-field",
        default=os.getenv("YOUTRACK_PRIORITY_FIELD", DEFAULT_PRIORITY_FIELD),
        help=f"Priority custom field name. Default: {DEFAULT_PRIORITY_FIELD}",
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
        "--separate-project",
        default=os.getenv("YOUTRACK_SEPARATE_PROJECT", DEFAULT_SEPARATE_PROJECT),
        help=(
            "Project key to send as a separate Telegram report. "
            f"Default: {DEFAULT_SEPARATE_PROJECT}. Use an empty value to disable."
        ),
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

    if args.review_days < 1:
        print("--review-days must be greater than 0.", file=sys.stderr)
        return 2

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

        testing_query = args.testing_query or build_state_query(args.testing_state)
        testing_issues = load_issues(base_url, token, testing_query, args.page_size)
        testing_changed_at = build_state_changed_at_by_issue(
            testing_issues,
            base_url,
            token,
            args.page_size,
            args.state_field,
            args.testing_state,
        )
        testing_tasks = build_priority_tasks(
            testing_issues,
            args.priority_field,
            base_url,
            testing_changed_at,
        )

        review_query = args.review_query or build_recent_state_query(
            args.review_state,
            args.review_days,
        )
        review_issues = load_issues(base_url, token, review_query, args.page_size)
        review_changed_at = build_state_changed_at_by_issue(
            review_issues,
            base_url,
            token,
            args.page_size,
            args.state_field,
            args.review_state,
        )
        review_tasks = build_priority_tasks(
            review_issues,
            args.priority_field,
            base_url,
            review_changed_at,
        )
        write_json(Path(args.output), activity)
        write_json(Path(args.testing_output), testing_tasks)
        write_json(Path(args.review_output), review_tasks)

        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if telegram_token and not args.no_telegram:
            telegram_reports = format_telegram_reports(
                activity,
                testing_tasks,
                review_tasks,
                args.review_days,
                args.separate_project,
            )
            for report in telegram_reports:
                send_telegram_report(
                    telegram_token,
                    args.telegram_chat_id,
                    report,
                )
        else:
            telegram_reports = format_telegram_reports(
                activity,
                testing_tasks,
                review_tasks,
                args.review_days,
                args.separate_project,
            )
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        print(f"HTTP error {error.code}: {details}", file=sys.stderr)
        return 1
    except URLError as error:
        print(f"Connection error: {error.reason}", file=sys.stderr)
        return 1
    except TimeoutError as error:
        print(f"Connection timeout: {error}", file=sys.stderr)
        return 1

    print(f"Written {len(activity)} users to {args.output}")
    print(f"Written {len(testing_tasks)} testing tasks to {args.testing_output}")
    print(f"Written {len(review_tasks)} review tasks to {args.review_output}")
    if os.getenv("TELEGRAM_BOT_TOKEN") and not args.no_telegram:
        print(
            f"Sent {len(telegram_reports)} Telegram report(s) to {args.telegram_chat_id}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
