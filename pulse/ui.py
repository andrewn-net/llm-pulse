"""Retro UI: synthwave logo, interactive menu, friendly prompts."""

from __future__ import annotations

import sys
from dataclasses import dataclass

import questionary
from questionary import Style
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from .format import console

# Synthwave color palette for questionary prompts (matches the logo).
QSTYLE = Style([
    ("qmark",       "fg:#00F5D4 bold"),
    ("question",    "fg:#FFFFFF bold"),
    ("answer",      "fg:#FFB75E bold"),
    ("pointer",     "fg:#E83E8C bold"),
    ("highlighted", "fg:#FFFFFF bg:#9B1B6E bold"),
    ("selected",    "fg:#00F5D4 bold"),
    ("text",        "fg:#DDDDDD"),
    ("instruction", "fg:#888888 italic"),
    # Autocomplete dropdown — prompt_toolkit classes
    ("completion-menu",                    "fg:#DDDDDD bg:#1E1E2E"),
    ("completion-menu.completion",         "fg:#DDDDDD bg:#1E1E2E"),
    ("completion-menu.completion.current", "fg:#FFFFFF bg:#9B1B6E bold"),
    ("scrollbar.background",               "bg:#2A2A3E"),
    ("scrollbar.button",                   "bg:#E83E8C"),
])

LOGO = r"""
██╗     ██╗     ███╗   ███╗  ██████╗ ██╗   ██╗██╗     ███████╗███████╗
██║     ██║     ████╗ ████║  ██╔══██╗██║   ██║██║     ██╔════╝██╔════╝
██║     ██║     ██╔████╔██║  ██████╔╝██║   ██║██║     ███████╗█████╗
██║     ██║     ██║╚██╔╝██║  ██╔═══╝ ██║   ██║██║     ╚════██║██╔══╝
███████╗███████╗██║ ╚═╝ ██║  ██║     ╚██████╔╝███████╗███████║███████╗
╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝      ╚═════╝ ╚══════╝╚══════╝╚══════╝
""".strip("\n")

# Synthwave sunset: deep purple → magenta → hot pink → coral → orange → gold.
SYNTHWAVE = ["#7B2CBF", "#B5179E", "#E83E8C", "#FF4D6D", "#FF7B54", "#FFB75E"]

TAGLINE = "▼  take the pulse of the LLM landscape  ▼"
HORIZON = "═" * 70


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def print_logo(compact: bool = False) -> None:
    """Print the retro logo. Skipped automatically when output is piped."""
    if not sys.stdout.isatty():
        return
    if compact:
        console.print(f"[bold #E83E8C]▶[/] [bold #FFB75E]llmpulse[/]   [dim]{TAGLINE}[/]")
        return
    console.print()
    for line, color in zip(LOGO.splitlines(), SYNTHWAVE):
        console.print(f"  [bold {color}]{line}[/]")
    # Horizon line + tagline below — synthwave grid feel.
    horizon_text = Text()
    for i, ch in enumerate(HORIZON):
        # Fade purple → cyan across the line.
        color = SYNTHWAVE[min(i * len(SYNTHWAVE) // len(HORIZON), len(SYNTHWAVE) - 1)]
        horizon_text.append(ch, style=color)
    console.print("  ", horizon_text)
    console.print(f"  [bold #00F5D4]{TAGLINE}[/]")
    console.print()


# ─── Interactive main menu ───────────────────────────────────────────────────

MENU_ITEMS = [
    ("1", "Pick a model for a task", "pick"),
    ("2", "Explain one model in depth", "explain"),
    ("3", "See what's changed recently", "digest"),
    ("4", "Compare models side-by-side", "compare"),
    ("5", "Browse the leaderboard", "list"),
    ("6", "Refresh data from the internet", "refresh"),
    ("7", "Schedule recurring runs (cron)", "schedule"),
    ("8", "Slack webhook setup", "slack"),
    ("i", "Show cache info", "info"),
    ("q", "Quit", "quit"),
]


def main_menu() -> str:
    """Show interactive menu, return the chosen command name."""
    print_logo()
    choices = [
        questionary.Choice(label, value=cmd)
        for _, label, cmd in MENU_ITEMS
    ]
    cmd = questionary.select(
        "What would you like to do?",
        choices=choices,
        style=QSTYLE,
        qmark="▶",
        instruction="(↑/↓ to move, Enter to select)",
    ).ask()
    if cmd is None:
        return "quit"
    return cmd


# ─── Interactive prompts inside commands ─────────────────────────────────────

EXAMPLE_TASKS = [
    "code review for python",
    "summarize a long PDF",
    "extract text from a screenshot",
    "creative writing",
    "general chat",
]


def prompt_for_task() -> str | None:
    _OTHER = "Other (type your own)..."
    _BACK  = "← Back to menu"
    choice = questionary.select(
        "What do you want to do?",
        choices=EXAMPLE_TASKS + [_OTHER, _BACK],
        style=QSTYLE,
        qmark="◆",
        instruction="(↑/↓ to move, Enter to select)",
    ).ask()
    if choice is None or choice == _BACK:
        return None
    if choice == _OTHER:
        try:
            return Prompt.ask("  [bold #00F5D4]task[/]", default="general chat")
        except (KeyboardInterrupt, EOFError):
            return None
    return choice


def prompt_for_model(model_names: list[str] | None = None) -> str:
    if model_names:
        return questionary.autocomplete(
            "Which model? (type to filter)",
            choices=model_names,
            style=QSTYLE,
            qmark="◆",
            validate=lambda v: bool(v.strip()) or "Please enter a model name",
        ).ask() or ""
    return Prompt.ask("  [bold #00F5D4]model[/]")


def prompt_for_models() -> list[str]:
    console.print()
    console.print(
        "  [bold]Which models to compare?[/] "
        "[dim](type 2+ names separated by spaces — Ctrl+C to cancel)[/]"
    )
    try:
        raw = Prompt.ask("  [bold #00F5D4]models[/]")
        return [m.strip() for m in raw.split() if m.strip()]
    except (KeyboardInterrupt, EOFError):
        return []


@dataclass
class PickFilters:
    free: bool = False
    max_price: float | None = None
    min_context: str | None = None
    multimodal: bool = False


def prompt_for_pick_filters(category: str = "text") -> PickFilters:
    """Step the user through the filter options with arrow-key prompts."""
    console.print()
    console.print("  [dim]Add filters? (use arrow keys, or press Enter for default)[/]\n")

    filters = PickFilters()

    filters.free = questionary.confirm(
        "Only show FREE models?",
        default=False,
        style=QSTYLE,
        qmark="◆",
    ).ask() or False

    if not filters.free:
        # Use "" as sentinel for "no limit" — questionary returns label strings for None values.
        budget = questionary.select(
            "Budget per million tokens?",
            choices=[
                questionary.Choice("No limit",              value=""),
                questionary.Choice("≤ $1   (very cheap)",   value=1.0),
                questionary.Choice("≤ $3   (cheap)",        value=3.0),
                questionary.Choice("≤ $10  (mid-range)",    value=10.0),
                questionary.Choice("≤ $30  (premium)",      value=30.0),
            ],
            style=QSTYLE,
            qmark="◆",
        ).ask()
        filters.max_price = float(budget) if budget else None

    ctx = questionary.select(
        "Minimum context window?",
        choices=[
            questionary.Choice("No minimum",                value=""),
            questionary.Choice("≥ 32k    (chats)",          value="32k"),
            questionary.Choice("≥ 128k   (long convos)",    value="128k"),
            questionary.Choice("≥ 200k   (whole codebases)", value="200k"),
            questionary.Choice("≥ 1M     (entire books)",   value="1m"),
        ],
        style=QSTYLE,
        qmark="◆",
    ).ask()
    filters.min_context = ctx or None

    # Vision tasks already imply multimodal — no need to ask.
    if category != "vision":
        filters.multimodal = questionary.confirm(
            "Need image/screenshot support?",
            default=False,
            style=QSTYLE,
            qmark="◆",
        ).ask() or False

    return filters


def prompt_select_pick(picks: list, prompt: str = "Select a model for details (or skip):") -> str | None:
    """Arrow-key picker over the pick results. Returns arena_name or None to skip."""
    if not picks:
        return None
    choices = [questionary.Choice("(skip — back to menu)", value=None)]
    for p in picks:
        # Compose a one-line summary
        price = "free" if (p.input_per_mtok_usd == 0 and p.output_per_mtok_usd == 0) else (
            f"${p.input_per_mtok_usd:.2f}/${p.output_per_mtok_usd:.2f}"
            if p.input_per_mtok_usd is not None else "—"
        )
        ctx = f"{p.context_length // 1000}k" if p.context_length else "—"
        label = f"#{p.rank:>2}  {p.arena_name:<40s} {p.rating:>5.0f}   {price:<18s}  {ctx}"
        choices.append(questionary.Choice(label, value=p.arena_name))

    return questionary.select(
        prompt,
        choices=choices,
        style=QSTYLE,
        qmark="◆",
        instruction="(↑/↓ to move, Enter to select)",
    ).ask()


def prompt_continue(label: str) -> bool:
    return Prompt.ask(
        f"  [dim]{label}[/]",
        choices=["y", "n"],
        default="n",
        show_choices=True,
    ) == "y"


# ─── First-run welcome ────────────────────────────────────────────────────────

def welcome_first_run() -> None:
    print_logo()
    console.print(
        Panel.fit(
            "[bold]Welcome to LLM Pulse![/]\n\n"
            "LLM Pulse keeps track of which AI models are best for which tasks,\n"
            "and what they cost. First, let's pull fresh data from the\n"
            "[cyan]LMSYS Chatbot Arena[/] and [cyan]OpenRouter[/] (takes ~5 seconds).",
            border_style="#E83E8C",
            padding=(1, 2),
        )
    )
    console.print()


# ─── Schedule wizard ──────────────────────────────────────────────────────────

_BACK   = "__back__"
_CANCEL = "__cancel__"


def schedule_wizard() -> tuple[str, str, str] | None:
    """Walk the user through creating a cron job. Returns (name, cron_expr, command).
    Every step has a ← Back option so mistakes are never permanent."""
    import shutil
    from .schedule import DAYS_OF_WEEK, cron_daily, cron_monthly, cron_weekly

    bin_path = shutil.which("llmpulse") or "llmpulse"
    console.print()

    def _sel(question, choices_map: list[tuple[str, object]], allow_back=True):
        """Show a select with optional ← Back / ← Cancel. Returns value, _BACK, or None."""
        extra = []
        if allow_back:
            extra.append(questionary.Choice("← Back", value=_BACK))
        extra.append(questionary.Choice("✕ Cancel", value=_CANCEL))
        choices = [questionary.Choice(label, value=val) for label, val in choices_map] + extra
        result = questionary.select(question, choices=choices, style=QSTYLE, qmark="◆").ask()
        if result is None or result == _CANCEL:
            return None
        return result

    # ── state ──────────────────────────────────────────────────────────────────
    freq: str | None = None
    hour: int | None = None
    day:  str | None = None
    dom:  int | None = None
    cron_expr: str | None = None
    name: str | None = None

    what = "digest"  # only option
    step = "freq"

    while True:
        # ── frequency ──────────────────────────────────────────────────────────
        if step == "freq":
            v = _sel("How often?", [
                ("Daily",                "daily"),
                ("Weekly",               "weekly"),
                ("Monthly",              "monthly"),
                ("Custom cron expression", "custom"),
            ])
            if v is None:
                return None
            if v == _BACK:
                step = "cat" if what in ("pick", "list") else "what"
                continue
            freq = v
            step = "custom" if freq == "custom" else "hour"

        # ── custom cron text entry ─────────────────────────────────────────────
        elif step == "custom":
            console.print(
                "  [dim]Format: minute hour day-of-month month day-of-week[/]\n"
                "  [dim]Examples: [cyan]0 9 * * 1[/] (Mon 9am)  "
                "[cyan]30 17 * * 5[/] (Fri 5:30pm)  "
                "[cyan]0 8 * * *[/] (daily 8am)[/]\n"
                "  [dim]Ctrl+C to go back[/]"
            )
            try:
                raw = Prompt.ask("  [bold #00F5D4]cron expression[/]").strip()
            except (KeyboardInterrupt, EOFError):
                step = "freq"
                continue
            if len(raw.split()) != 5:
                console.print("  [red]✗ Need exactly 5 fields — try again.[/]")
                continue
            cron_expr = raw
            step = "name"

        # ── hour picker ────────────────────────────────────────────────────────
        elif step == "hour":
            v = _sel("What hour? (24h)", [(f"{h:02d}:00", h) for h in range(24)])
            if v is None:
                return None
            if v == _BACK:
                step = "freq"
                continue
            hour = v
            step = "day" if freq == "weekly" else ("dom" if freq == "monthly" else "name")

        # ── day of week (weekly only) ──────────────────────────────────────────
        elif step == "day":
            v = _sel("Which day?", list(DAYS_OF_WEEK))
            if v is None:
                return None
            if v == _BACK:
                step = "hour"
                continue
            day = v
            step = "name"

        # ── day of month (monthly only) ────────────────────────────────────────
        elif step == "dom":
            v = _sel("Which day of the month?", [(f"day {d}", d) for d in range(1, 29)])
            if v is None:
                return None
            if v == _BACK:
                step = "hour"
                continue
            dom = v
            step = "name"

        # ── name ───────────────────────────────────────────────────────────────
        elif step == "name":
            default_name = f"{what}-{freq}"
            console.print("  [dim]Ctrl+C to go back[/]")
            try:
                raw = Prompt.ask(
                    "  [bold #00F5D4]job name[/] [dim](used to remove this job later)[/]",
                    default=default_name,
                ).strip()
            except (KeyboardInterrupt, EOFError):
                # back to the last timed step
                if freq == "custom":
                    step = "custom"
                elif freq == "weekly":
                    step = "day"
                elif freq == "monthly":
                    step = "dom"
                else:
                    step = "hour"
                continue
            if not raw:
                console.print("  [red]✗ Name required.[/]")
                continue
            name = raw
            break  # ✓ done

    # ── build final values ─────────────────────────────────────────────────────
    if freq == "daily":
        cron_expr = cron_daily(hour)
    elif freq == "weekly":
        cron_expr = cron_weekly(day, hour)
    elif freq == "monthly":
        cron_expr = cron_monthly(dom, hour)
    # custom: cron_expr already set above

    cmd = f"{bin_path} digest --slack"
    return name, cron_expr, cmd


# ─── Friendly error wrapper ──────────────────────────────────────────────────

def friendly_network_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "name or service not known" in msg or "nodename nor servname" in msg or "getaddrinfo" in msg:
        return "Couldn't reach the internet. Check your wifi/connection and try again."
    if "timeout" in msg or "timed out" in msg:
        return "The request timed out. The server might be slow — try `llmpulse refresh --force` in a moment."
    if "503" in msg or "502" in msg or "504" in msg:
        return "The data source is temporarily down. Try again in a few minutes."
    return f"Network error: {exc}"
