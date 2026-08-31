"""Secure HTTP entry point for running StatusCat on Vercel."""

from __future__ import annotations

import contextlib
import hmac
import io
import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import youtrack_activity  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._run_if_authorized()

    def do_POST(self) -> None:
        self._run_if_authorized()

    def _run_if_authorized(self) -> None:
        expected_secret = os.getenv("CRON_SECRET", "")
        authorization = self.headers.get("Authorization", "")
        provided_secret = self.headers.get("X-Cron-Secret", "")
        authorized = expected_secret and (
            hmac.compare_digest(provided_secret, expected_secret)
            or hmac.compare_digest(authorization, f"Bearer {expected_secret}")
        )
        if not authorized:
            self._respond(401, {"ok": False, "error": "Unauthorized"})
            return

        with tempfile.TemporaryDirectory() as output_directory:
            output_path = Path(output_directory)
            argv = [
                "--output", str(output_path / "activity.json"),
                "--testing-output", str(output_path / "testing.json"),
                "--review-output", str(output_path / "review.json"),
            ]
            logs = io.StringIO()
            with contextlib.redirect_stdout(logs), contextlib.redirect_stderr(logs):
                exit_code = _run(argv)

        status = 200 if exit_code == 0 else 502
        self._respond(status, {"ok": exit_code == 0, "exit_code": exit_code, "log": logs.getvalue()})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _respond(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _run(argv: list[str]) -> int:
    original_argv = sys.argv
    try:
        sys.argv = ["youtrack_activity.py", *argv]
        return youtrack_activity.main()
    finally:
        sys.argv = original_argv
