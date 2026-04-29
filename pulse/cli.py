from typing import Annotated

import httpx
import typer

from . import __version__
from .cache import connect
from .config import ARENA_CATEGORIES, DB_PATH, DEFAULT_TTL_HOURS
from .digest import build_digest, mark_digest_run
from .explain import explain as explain_model_data
from .format import console, render_compare, render_digest, render_explain, render_picks
from .pick import parse_context, task_to_category, top_picks
from .reconcile import rebuild_aliases
from . import schedule as _schedule
from . import slack as _slack
from .sources import lmsys, openrouter
from .ui import (
    friendly_network_error,
    is_interactive,
    main_menu,
    print_logo,
    prompt_continue,
    prompt_for_model,
    prompt_for_models,
    prompt_for_pick_filters,
    prompt_for_category,
    prompt_select_pick,
    welcome_first_run,
)

app = typer.Typer(
    name="llmpulse",
    help="LLM Pulse — pick the right model for any task, track what's changed.",
    invoke_without_command=True,
    no_args_is_help=False,
    add_completion=False,
    rich_markup_mode="rich",
)


# ─── Default entry point: interactive menu when no subcommand given ──────────


@app.callback()
def _root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if not is_interactive():
        # Non-TTY (e.g. piped or in a script): fall back to help text.
        console.print(ctx.get_help())
        raise typer.Exit()

    # First-run welcome + auto-refresh if cache is empty.
    if not DB_PATH.exists():
        welcome_first_run()
        try:
            _ensure_data(force_refresh=True)
        except Exception as e:
            console.print(f"[red]✗[/] {friendly_network_error(e)}")
            raise typer.Exit(1)

    while True:
        cmd = main_menu()
        if cmd == "quit":
            console.print("\n  [dim]bye ◣[/]\n")
            raise typer.Exit()
        try:
            _dispatch_interactive(cmd)
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]✗[/] {friendly_network_error(e)}")
        if not prompt_continue("back to menu? [y/n]"):
            console.print("\n  [dim]bye ◣[/]\n")
            return
        console.print()


def _dispatch_interactive(cmd: str) -> None:
    """Run a command interactively, prompting for any missing inputs."""
    if cmd == "pick":
        cat = prompt_for_category()
        if cat is None:
            return
        f = prompt_for_pick_filters(category=cat)
        console.print(f"  [dim]Category: [cyan]{cat}[/][/]")
        active = _format_active_filters(f)
        if active:
            console.print(f"  [dim]Filters: {active}[/]")
        from .pick import parse_context as _pc
        with connect() as conn:
            picks = top_picks(
                conn, cat, limit=10,
                free_only=f.free,
                max_avg_price=f.max_price,
                min_context=_pc(f.min_context) if f.min_context else None,
                multimodal_only=f.multimodal,
            )
        from .format import render_picks as _render
        _render(picks, cat, filtered=bool(active))
        # Offer drill-down
        if picks:
            chosen = prompt_select_pick(picks)
            if chosen:
                explain(model=chosen)
    elif cmd == "explain":
        with connect() as conn:
            names = [
                r["model_name"]
                for r in conn.execute(
                    "SELECT DISTINCT model_name FROM arena_snapshots ORDER BY model_name"
                ).fetchall()
            ]
        m = prompt_for_model(names)
        if m:
            explain(model=m)
    elif cmd == "digest":
        digest(days=None)
    elif cmd == "compare":
        models = prompt_for_models()
        if not models:
            return
        if len(models) < 2:
            console.print("  [yellow]Need at least 2 models to compare.[/]")
            return
        compare(models=models)
    elif cmd == "list":
        list_models(category="text", limit=15)
    elif cmd == "refresh":
        refresh(force=True)
    elif cmd == "schedule":
        _interactive_schedule()
    elif cmd == "slack":
        _interactive_slack()
    elif cmd == "info":
        info()


def _interactive_schedule() -> None:
    import questionary
    from .ui import QSTYLE
    has_cron = _schedule.crontab_available()
    choices = [questionary.Choice("Add a new job", value="add")]
    if has_cron:
        choices += [
            questionary.Choice("List existing jobs (crontab)", value="list"),
            questionary.Choice("Remove a job (crontab)",       value="remove"),
        ]
    choices.append(questionary.Choice("← Back to menu", value=None))
    action = questionary.select(
        "Schedule:",
        choices=choices,
        style=QSTYLE,
        qmark="◆",
    ).ask()
    if action is None:
        return
    if action == "list":
        schedule_list()
    elif action == "add":
        schedule_add()
    elif action == "remove":
        jobs = _schedule.list_jobs()
        if not jobs:
            console.print("  [dim]No jobs to remove.[/]")
            return
        name = questionary.select(
            "Which job?",
            choices=[questionary.Choice(f"{j.name}  ({j.human_schedule()})", value=j.name) for j in jobs]
                    + [questionary.Choice("← Cancel", value=None)],
            style=QSTYLE,
            qmark="◆",
        ).ask()
        if name:
            schedule_remove(name)


def _interactive_slack() -> None:
    import questionary
    from .ui import QSTYLE
    with connect() as conn:
        configured = bool(_slack.get_webhook(conn))
    choices = []
    if configured:
        choices += [
            questionary.Choice("Send test message",     value="test"),
            questionary.Choice("Show webhook (masked)", value="show"),
            questionary.Choice("Replace webhook URL",   value="setup"),
            questionary.Choice("Remove webhook",        value="clear"),
        ]
    else:
        choices.append(questionary.Choice("Configure webhook URL", value="setup"))
    choices.append(questionary.Choice("← Back to menu", value=None))
    action = questionary.select(
        "Slack:",
        choices=choices,
        style=QSTYLE,
        qmark="◆",
    ).ask()
    if action is None:
        return
    if action == "setup":
        slack_setup(url=None)
    elif action == "test":
        slack_test()
    elif action == "show":
        slack_show()
    elif action == "clear":
        slack_clear()


# ─── Internal helper ──────────────────────────────────────────────────────────


def _format_active_filters(f) -> str:
    parts = []
    if getattr(f, "free", False):
        parts.append("free only")
    mp = getattr(f, "max_price", None)
    if mp is not None:
        parts.append(f"≤ ${mp:.2f}/Mtok avg")
    mc = getattr(f, "min_context", None)
    if mc:
        parts.append(f"≥ {mc} context")
    if getattr(f, "multimodal", False):
        parts.append("multimodal")
    return ", ".join(parts)


def _ensure_data(force_refresh: bool = False, ttl: float = DEFAULT_TTL_HOURS) -> None:
    """Refresh sources if stale, then rebuild aliases."""
    with connect() as conn:
        try:
            with console.status("Refreshing data...", spinner="dots"):
                n_or = openrouter.refresh(conn, ttl, force=force_refresh)
                n_ar = lmsys.refresh(conn, ttl, force=force_refresh)
        except (httpx.HTTPError, OSError) as e:
            raise RuntimeError(friendly_network_error(e)) from e
        if n_or or n_ar:
            n_alias = rebuild_aliases(conn)
            parts = []
            if n_or:
                parts.append(f"OpenRouter: {n_or} models")
            if n_ar:
                parts.append(f"Arena: {n_ar} entries")
            parts.append(f"aliases: {n_alias}")
            console.print(f"  [dim]✓ Refreshed — {', '.join(parts)}[/]")


# ─── Subcommands ──────────────────────────────────────────────────────────────


@app.command()
def refresh(
    force: Annotated[bool, typer.Option("--force", "-f", help="Re-fetch even if cache is fresh")] = False,
) -> None:
    """Fetch latest data from all sources."""
    _ensure_data(force_refresh=force, ttl=0 if force else DEFAULT_TTL_HOURS)


@app.command()
def pick(
    task: Annotated[str | None, typer.Argument(help="Free-text task description, e.g. 'code review for python'")] = None,
    category: Annotated[str | None, typer.Option("--category", "-c", help=f"Force category: {', '.join(ARENA_CATEGORIES)}")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 10,
    priced_only: Annotated[bool, typer.Option("--priced", help="Only show models available on OpenRouter")] = False,
    free: Annotated[bool, typer.Option("--free", help="Only free models ($0/$0 or :free variants)")] = False,
    max_price: Annotated[float | None, typer.Option("--max-price", help="Max average $/Mtok ((input+output)/2)")] = None,
    min_context: Annotated[str | None, typer.Option("--min-context", help="Min context window, e.g. '200k', '1m'")] = None,
    multimodal: Annotated[bool, typer.Option("--multimodal", help="Only models that accept images")] = False,
    slack: Annotated[bool, typer.Option("--slack", help="Also post the picks to your Slack webhook")] = False,
) -> None:
    """Recommend models for a task."""
    _ensure_data()
    if category:
        if category not in ARENA_CATEGORIES:
            raise typer.BadParameter(f"unknown category. choices: {', '.join(ARENA_CATEGORIES)}")
        cat = category
    elif task:
        cat = task_to_category(task)
        console.print(f"  [dim]Task '{task}' → category: [cyan]{cat}[/][/]")
    else:
        cat = "text"

    min_ctx = parse_context(min_context) if min_context else None
    active_filters = []
    if free:
        active_filters.append("free only")
    if max_price is not None:
        active_filters.append(f"≤ ${max_price:.2f}/Mtok avg")
    if min_ctx:
        active_filters.append(f"≥ {min_context} context")
    if multimodal:
        active_filters.append("multimodal")
    if priced_only:
        active_filters.append("priced only")
    if active_filters:
        console.print(f"  [dim]Filters: {', '.join(active_filters)}[/]")

    with connect() as conn:
        picks = top_picks(
            conn, cat, limit=limit,
            only_priced=priced_only,
            max_avg_price=max_price,
            min_context=min_ctx,
            free_only=free,
            multimodal_only=multimodal,
        )
        if slack:
            _post_to_slack(conn, _slack.format_picks(picks, cat))
    render_picks(picks, cat, filtered=bool(active_filters))

    # Hint about filters for non-interactive users who didn't use any.
    if picks and not active_filters and is_interactive():
        console.print(
            "\n  [dim]Tip: filter with[/] [cyan]--free[/][dim],[/] "
            "[cyan]--max-price 3[/][dim],[/] [cyan]--min-context 200k[/][dim], or[/] "
            "[cyan]--multimodal[/][dim]. Run `llmpulse` (no args) for an interactive picker.[/]"
        )


@app.command()
def explain(
    model: Annotated[str, typer.Argument(help="Model name or substring, e.g. 'claude-opus-4-7'")],
) -> None:
    """Deep dive on one model: ranks across all categories + price history."""
    _ensure_data()
    with connect() as conn:
        e = explain_model_data(conn, model)
    if e is None:
        console.print(f"  [yellow]No model matching '{model}'. Try `llmpulse list` to see names.[/]")
        raise typer.Exit(1)
    render_explain(e)


@app.command()
def digest(
    days: Annotated[int | None, typer.Option("--days", "-d", help="Look back N days (default: since last digest run, or 7)")] = None,
    slack: Annotated[bool, typer.Option("--slack", help="Also post the digest to your Slack webhook")] = False,
) -> None:
    """Show what's changed since last run."""
    _ensure_data()
    with connect() as conn:
        d = build_digest(conn, since_days=days)
        render_digest(d)
        mark_digest_run(conn)
        if slack:
            text, blocks = _slack.format_digest(d)
            _post_to_slack(conn, text, blocks)


@app.command()
def compare(
    models: Annotated[list[str], typer.Argument(help="Two or more arena model names or substrings")],
) -> None:
    """Side-by-side comparison of two or more models."""
    if len(models) < 2:
        raise typer.BadParameter("need at least two models")
    _ensure_data()
    with connect() as conn:
        rows = []
        for query in models:
            row = conn.execute(
                """
                SELECT a.model_name AS arena_name, a.rating AS rating, a.rank AS rank,
                       al.openrouter_id AS openrouter_id,
                       o.input_per_mtok_usd AS input_per_mtok_usd,
                       o.output_per_mtok_usd AS output_per_mtok_usd,
                       o.context_length AS context_length,
                       o.modality AS modality
                FROM arena_snapshots a
                LEFT JOIN aliases al ON al.arena_name = a.model_name
                LEFT JOIN openrouter_snapshots o
                       ON o.model_id = al.openrouter_id
                      AND o.snapshot_at = (SELECT MAX(snapshot_at) FROM openrouter_snapshots)
                WHERE a.category = 'text'
                  AND a.snapshot_at = (SELECT MAX(snapshot_at) FROM arena_snapshots WHERE category = 'text')
                  AND a.model_name LIKE ?
                ORDER BY a.rank
                LIMIT 1
                """,
                (f"%{query}%",),
            ).fetchone()
            if not row:
                console.print(f"  [yellow]no match for '{query}' — try `llmpulse list` to see names[/]")
                continue
            rows.append(dict(row))
    if rows:
        render_compare(rows)


@app.command(name="list")
def list_models(
    category: Annotated[str, typer.Option("--category", "-c")] = "text",
    limit: Annotated[int, typer.Option("--limit", "-n")] = 25,
    slack: Annotated[bool, typer.Option("--slack", help="Also post the leaderboard to your Slack webhook")] = False,
) -> None:
    """List the latest arena leaderboard for a category."""
    _ensure_data()
    with connect() as conn:
        picks = top_picks(conn, category, limit=limit)
        if slack:
            _post_to_slack(conn, _slack.format_picks(picks, category))
    render_picks(picks, category)


@app.command()
def info() -> None:
    """Show cache location, freshness, and version."""
    print_logo(compact=True)
    console.print(f"  [bold]LLM Pulse[/] v{__version__}")
    console.print(f"  cache: [cyan]{DB_PATH}[/]")
    with connect() as conn:
        for source in ("openrouter", "arena"):
            row = conn.execute(
                "SELECT fetched_at FROM source_fetches WHERE source = ?", (source,)
            ).fetchone()
            console.print(f"    {source}: {row['fetched_at'] if row else '[dim]never[/]'}")
        n_aliases = conn.execute("SELECT COUNT(*) AS n FROM aliases").fetchone()["n"]
        console.print(f"    aliases: {n_aliases}")


# ─── Slack webhook ────────────────────────────────────────────────────────────


def _post_to_slack(conn, text: str, blocks: list | None = None) -> None:
    url = _slack.get_webhook(conn)
    if not url:
        console.print(
            "  [yellow]No Slack webhook configured.[/] "
            "[dim]Run `llmpulse slack setup` first.[/]"
        )
        return
    try:
        _slack.post(url, text, blocks)
        console.print("  [green]✓ posted to Slack[/]")
    except Exception as e:
        console.print(f"  [red]✗ Slack post failed:[/] {e}")


slack_app = typer.Typer(help="Manage the Slack webhook for posting digests/picks.")
app.add_typer(slack_app, name="slack")


@slack_app.command("setup")
def slack_setup(
    url: Annotated[str | None, typer.Argument(help="Slack incoming webhook URL")] = None,
) -> None:
    """Save your Slack incoming-webhook URL."""
    if not url:
        from rich.prompt import Prompt
        from rich.panel import Panel
        console.print(
            Panel(
                "[bold]How to create a Slack webhook[/]\n\n"
                "[bold]Option A — Incoming Webhook (recommended, simplest)[/]\n"
                "  1. Go to [cyan]https://api.slack.com/messaging/webhooks[/]\n"
                "  2. Click [bold]Create your Slack app[/] → From scratch\n"
                "  3. Enable [bold]Incoming Webhooks[/] and add one to a channel\n"
                "  4. Copy the URL — it starts with [dim]https://hooks.slack.com/[/]\n\n"
                "[bold]Option B — Workflow Builder webhook[/]\n"
                "  1. In Slack: [bold]Automations → Workflow Builder → New Workflow[/]\n"
                "  2. Add a [bold]Webhook[/] trigger\n"
                "  3. [bold red]Name the variable exactly:[/] [bold]text[/]  ← important\n"
                "  4. Add a [bold]Send a message[/] step using that variable\n"
                "  5. Copy the webhook URL\n\n"
                "[dim]Ctrl+C to cancel[/]",
                border_style="#7B2CBF",
                padding=(1, 2),
            )
        )
        try:
            url = Prompt.ask("  [bold #00F5D4]webhook URL[/]")
        except (KeyboardInterrupt, EOFError):
            console.print("  [dim]cancelled[/]")
            return
    if not url or not url.strip():
        return
    if not url.startswith("https://hooks.slack.com/"):
        console.print(
            "  [yellow]⚠ That doesn't look like a Slack webhook URL.[/]\n"
            "  [dim]If using Workflow Builder, make sure the variable is named [bold]text[/].[/]"
        )
    with connect() as conn:
        _slack.save_webhook(conn, url)
    console.print("  [green]✓ webhook saved[/]")


@slack_app.command("test")
def slack_test() -> None:
    """Send a full mock digest to verify your webhook and layout."""
    from .digest import ArenaChange, Digest, NewModel, PriceChange
    with connect() as conn:
        url = _slack.get_webhook(conn)
    if not url:
        console.print("  [yellow]No webhook configured.[/] Run `llmpulse slack setup` first.")
        raise typer.Exit(1)

    mock = Digest(
        since="2026-04-21T09:00:00+00:00",
        arena_changes=[
            ArenaChange("text", "claude-opus-4-7",          delta_rank=-2,  delta_rating=+18.3, new_rank=1,  new_rating=1387.0),
            ArenaChange("text", "gpt-4.1",                  delta_rank=+1,  delta_rating=-6.1,  new_rank=3,  new_rating=1351.0),
            ArenaChange("text", "gemini-2.5-pro",           delta_rank=None, delta_rating=None, new_rank=4,  new_rating=1340.0),
            ArenaChange("code", "claude-opus-4-7",          delta_rank=-1,  delta_rating=+12.0, new_rank=1,  new_rating=1401.0),
            ArenaChange("code", "deepseek-v3",              delta_rank=+2,  delta_rating=-9.4,  new_rank=5,  new_rating=1298.0),
        ],
        new_arena_models=[],
        price_changes=[
            PriceChange("openai/gpt-4.1",           "input",  old=2.00, new=1.50, pct=-25.0),
            PriceChange("openai/gpt-4.1",           "output", old=8.00, new=6.00, pct=-25.0),
            PriceChange("mistralai/mistral-large-2", "input",  old=3.00, new=3.60, pct=+20.0),
        ],
        new_or_models=[
            NewModel("google/gemini-2.5-flash-preview", "Gemini 2.5 Flash Preview"),
            NewModel("meta-llama/llama-4-maverick",      "Llama 4 Maverick"),
            NewModel("qwen/qwen3-235b-a22b",             "Qwen3 235B A22B"),
        ],
    )

    try:
        text, blocks = _slack.format_digest(mock, prefix="🧪 TEST MESSAGE")
        _slack.post(url, text, blocks)
        console.print("  [green]✓ mock digest sent — check your Slack channel[/]")
    except Exception as e:
        console.print(f"  [red]✗ failed:[/] {e}")
        raise typer.Exit(1)


@slack_app.command("clear")
def slack_clear() -> None:
    """Forget the saved webhook URL."""
    with connect() as conn:
        _slack.clear_webhook(conn)
    console.print("  [green]✓ webhook removed[/]")


@slack_app.command("show")
def slack_show() -> None:
    """Show whether a webhook is configured (URL is masked)."""
    with connect() as conn:
        url = _slack.get_webhook(conn)
    if not url:
        console.print("  [dim]No webhook configured.[/]")
        return
    masked = url[:32] + "…" + url[-6:] if len(url) > 40 else url
    console.print(f"  webhook: [cyan]{masked}[/]")


# ─── Schedule (cron) ──────────────────────────────────────────────────────────


schedule_app = typer.Typer(help="Schedule recurring LLM Pulse runs via cron.")
app.add_typer(schedule_app, name="schedule")


@schedule_app.command("list")
def schedule_list() -> None:
    """List all LLM Pulse cron jobs."""
    if not _schedule.crontab_available():
        console.print("  [yellow]`crontab` not found on this system.[/]")
        raise typer.Exit(1)
    jobs = _schedule.list_jobs()
    if not jobs:
        console.print(
            "  [dim]No scheduled jobs.[/] "
            "Run [cyan]llmpulse schedule add[/] to create one."
        )
        return
    from rich.table import Table
    t = Table(title="Scheduled LLM Pulse jobs")
    t.add_column("Name")
    t.add_column("When")
    t.add_column("Cron", style="dim")
    t.add_column("Command", style="dim")
    for j in jobs:
        t.add_row(j.name, j.human_schedule(), j.schedule, j.command)
    console.print(t)


@schedule_app.command("remove")
def schedule_remove(
    name: Annotated[str, typer.Argument(help="Job name (see `llmpulse schedule list`)")],
) -> None:
    """Remove a scheduled job by name."""
    if not _schedule.crontab_available():
        console.print("  [yellow]`crontab` not found on this system.[/]")
        raise typer.Exit(1)
    if _schedule.remove_job(name):
        console.print(f"  [green]✓ removed `{name}`[/]")
    else:
        console.print(f"  [yellow]No job named `{name}`.[/]")
        raise typer.Exit(1)


@schedule_app.command("add")
def schedule_add() -> None:
    """Interactively create a recurring LLM Pulse job."""
    from .ui import schedule_wizard
    spec = schedule_wizard()
    if spec is None:
        return

    if spec[0] == "cron":
        if not _schedule.crontab_available():
            console.print("  [yellow]`crontab` not found on this system — pick GitHub Actions instead.[/]")
            raise typer.Exit(1)
        _, name, cron_expr, command = spec
        _schedule.add_job(name, cron_expr, command)
        console.print(
            f"  [green]✓ scheduled `{name}`[/] [dim]→ {cron_expr}  {command}[/]"
        )
        return

    if spec[0] == "gha":
        from pathlib import Path
        _, cron_expr = spec

        # Check if we're in a git repo (workflow file only works if pushed to GitHub)
        if not Path(".git").exists():
            console.print(
                "  [yellow]⚠ You're not in a Git repository.[/]\n\n"
                "  GitHub Actions requires the workflow file to be pushed to GitHub.\n"
                "  Steps:\n"
                "  1. `cd` into your Git repo (or create one: `git init`)\n"
                "  2. Run `llmpulse schedule add` again\n"
                "  3. The workflow will be created in `.github/workflows/`"
            )
            raise typer.Exit(1)

        path = Path(_schedule.GHA_WORKFLOW_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_schedule.render_gha_workflow(cron_expr))
        console.print(f"  [green]✓ wrote workflow:[/] [cyan]{path}[/] [dim]→ {cron_expr}[/]")
        console.print(
            "\n  [bold]Next steps:[/]\n"
            "  1. Ensure this repo is on GitHub (Settings → Collaborators).\n"
            "  2. Add the webhook URL as a repo secret named "
            "[cyan]LLMPULSE_SLACK_WEBHOOK[/] (Settings → Secrets → Actions).\n"
            "  3. Commit and push the workflow file: `git add .github/ && git commit -m '...' && git push`.\n"
            "  4. Trigger it once from the [cyan]Actions[/] tab to test "
            "([dim]Run workflow[/] button)."
        )


if __name__ == "__main__":
    app()
