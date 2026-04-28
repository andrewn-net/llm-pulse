"""Manage `llmpulse`-tagged cron entries via the user's crontab."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

MARKER = "# llmpulse:"


@dataclass
class Job:
    name: str
    schedule: str  # 5-field cron expression
    command: str

    def human_schedule(self) -> str:
        m, h, dom, mon, dow = self.schedule.split()
        # Common patterns first
        if dom == "*" and mon == "*" and dow == "*":
            return f"daily at {int(h):02d}:{int(m):02d}"
        if dom == "*" and mon == "*" and dow != "*":
            days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            try:
                d = days[int(dow)]
            except (ValueError, IndexError):
                d = dow
            return f"weekly on {d} at {int(h):02d}:{int(m):02d}"
        if dom != "*" and mon == "*" and dow == "*":
            return f"monthly on day {dom} at {int(h):02d}:{int(m):02d}"
        return self.schedule


def crontab_available() -> bool:
    return shutil.which("crontab") is not None


def _read() -> str:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except FileNotFoundError:
        return ""
    # `crontab -l` exits 1 when no crontab exists — that's fine, just empty.
    return r.stdout if r.returncode == 0 else ""


def _write(content: str) -> None:
    if content and not content.endswith("\n"):
        content += "\n"
    subprocess.run(["crontab", "-"], input=content, text=True, check=True)


def list_jobs() -> list[Job]:
    content = _read()
    jobs: list[Job] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(MARKER) and i + 1 < len(lines):
            name = line[len(MARKER):].strip()
            cmd_line = lines[i + 1].strip()
            parts = cmd_line.split(None, 5)
            if len(parts) == 6:
                jobs.append(Job(name=name, schedule=" ".join(parts[:5]), command=parts[5]))
            i += 2
        else:
            i += 1
    return jobs


def _strip_named(content: str, name: str) -> str:
    """Remove the marker line plus the cron line that follows it."""
    out: list[str] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(MARKER) and line[len(MARKER):].strip() == name:
            i += 2  # skip marker + cron line
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def add_job(name: str, schedule: str, command: str) -> None:
    """Add or replace a job by name."""
    content = _strip_named(_read(), name)
    if content and not content.endswith("\n"):
        content += "\n"
    content += f"{MARKER}{name}\n{schedule} {command}\n"
    _write(content)


def remove_job(name: str) -> bool:
    content = _read()
    new_content = _strip_named(content, name)
    if new_content == content:
        return False
    _write(new_content)
    return True


# ─── Schedule helpers for the wizard ────────────────────────────────────────

DAYS_OF_WEEK = [
    ("Monday",    1), ("Tuesday",  2), ("Wednesday", 3), ("Thursday", 4),
    ("Friday",    5), ("Saturday", 6), ("Sunday",    0),
]


def cron_daily(hour: int, minute: int = 0) -> str:
    return f"{minute} {hour} * * *"


def cron_weekly(day_of_week: int, hour: int, minute: int = 0) -> str:
    return f"{minute} {hour} * * {day_of_week}"


def cron_monthly(day_of_month: int, hour: int, minute: int = 0) -> str:
    return f"{minute} {hour} {day_of_month} * *"


# ─── GitHub Actions workflow generation ─────────────────────────────────────

GHA_WORKFLOW_PATH = ".github/workflows/llmpulse-digest.yml"


def render_gha_workflow(cron_expr: str) -> str:
    """Render a GitHub Actions workflow YAML that runs `llmpulse digest --slack`."""
    return f"""name: LLM Pulse digest

on:
  schedule:
    - cron: "{cron_expr}"
  workflow_dispatch:

jobs:
  digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v3
        with:
          python-version: "3.12"

      # Persist the SQLite cache across runs so digests have a real baseline.
      - name: Restore llmpulse cache
        uses: actions/cache@v4
        with:
          path: ~/.local/share/llm-pulse
          key: llmpulse-cache

      - run: uv tool install --editable .

      - run: llmpulse refresh --force

      - run: llmpulse digest --slack
        env:
          LLMPULSE_SLACK_WEBHOOK: ${{{{ secrets.LLMPULSE_SLACK_WEBHOOK }}}}
"""
