from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import ARENA_CATEGORIES
from .digest import Digest
from .explain import Explanation, fmt_snapshot_date
from .pick import Pick, best_value

console = Console()


def _fmt_price(p: float | None) -> str:
    if p is None:
        return "—"
    if p == 0:
        return "free"
    return f"${p:.2f}"


def _fmt_ctx(c: int | None) -> str:
    if not c:
        return "—"
    if c >= 1000:
        return f"{c // 1000}k"
    return str(c)


def render_picks(picks: list[Pick], category: str, filtered: bool = False) -> None:
    if not picks:
        if filtered:
            console.print(
                f"  [yellow]No models in '{category}' match your filters.[/] "
                "[dim]Try loosening --max-price, --min-context, or removing --free.[/]"
            )
        else:
            console.print(
                f"  [yellow]No data for category '{category}'.[/] "
                "[dim]Run `llmpulse refresh --force`.[/]"
            )
        return

    table = Table(title=f"Top models — {category}", show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Model")
    table.add_column("Arena", justify="right")
    table.add_column("$/Mtok in", justify="right")
    table.add_column("$/Mtok out", justify="right")
    table.add_column("Ctx", justify="right")
    table.add_column("OpenRouter ID", style="dim")

    bv = best_value(picks)
    for p in picks:
        marker = "  ★" if bv and p.arena_name == bv.arena_name else ""
        table.add_row(
            str(p.rank),
            p.arena_name + marker,
            f"{p.rating:.0f}",
            _fmt_price(p.input_per_mtok_usd),
            _fmt_price(p.output_per_mtok_usd),
            _fmt_ctx(p.context_length),
            p.openrouter_id or "[dim]—[/]",
        )
    console.print(table)
    if bv:
        console.print(
            f"[green]★ best value: {bv.arena_name}[/]"
            f"[dim]  — highest arena rating per dollar[/]"
        )


def render_digest(d: Digest) -> None:
    console.print(f"[bold]Changes since[/] [cyan]{d.since}[/]\n")

    if d.arena_changes:
        # Group by category
        by_cat: dict[str, list] = {}
        for c in d.arena_changes:
            by_cat.setdefault(c.category, []).append(c)
        for cat, items in by_cat.items():
            console.print(f"[bold]Arena ({cat})[/]")
            for c in items[:8]:
                if c.delta_rank is None:
                    console.print(f"  [green]+ NEW[/] #{c.new_rank} [bold]{c.model_name}[/] ({c.new_rating:.0f})")
                else:
                    arrow = "↑" if c.delta_rating and c.delta_rating > 0 else "↓"
                    color = "green" if c.delta_rating and c.delta_rating > 0 else "red"
                    sign = "+" if (c.delta_rating or 0) > 0 else ""
                    console.print(
                        f"  [{color}]{arrow}[/] {c.model_name}  "
                        f"rating {sign}{c.delta_rating:.1f} → {c.new_rating:.0f}, "
                        f"rank #{c.new_rank}"
                    )
            console.print()
    else:
        console.print("[dim]Arena: no changes (or no baseline yet)[/]\n")

    if d.price_changes:
        console.print("[bold]Prices[/]")
        for p in d.price_changes[:10]:
            arrow = "↓" if p.pct < 0 else "↑"
            color = "green" if p.pct < 0 else "yellow"
            console.print(
                f"  [{color}]{arrow}[/] {p.model_id} {p.field}: "
                f"${p.old:.2f} → ${p.new:.2f} ({p.pct:+.0f}%)"
            )
        console.print()

    if d.new_or_models:
        console.print(f"[bold]New on OpenRouter[/] ({len(d.new_or_models)})")
        for m in d.new_or_models[:10]:
            console.print(f"  + {m.model_id}  [dim]{m.name}[/]")
        if len(d.new_or_models) > 10:
            console.print(f"  [dim]… and {len(d.new_or_models) - 10} more[/]")
        console.print()

    if not (d.arena_changes or d.price_changes or d.new_or_models):
        console.print("[dim]No changes detected since baseline.[/]")


def render_explain(e: Explanation) -> None:
    org = f" [dim]({e.organization})[/]" if e.organization else ""
    title = f"[bold #E83E8C]{e.arena_name}[/]{org}"
    body_lines = []
    if e.openrouter_id:
        conf = f" [dim](match: {e.confidence})[/]" if e.confidence else ""
        body_lines.append(f"[bold]OpenRouter ID:[/] [cyan]{e.openrouter_id}[/]{conf}")
    else:
        body_lines.append("[dim]Not available on OpenRouter — closed source or self-hosted.[/]")
    if e.modality:
        body_lines.append(f"[bold]Modality:[/]      {e.modality}")
    if e.context_length:
        body_lines.append(f"[bold]Context:[/]       {_fmt_ctx(e.context_length)}")
    if e.current_input_price is not None:
        body_lines.append(
            f"[bold]Price:[/]         "
            f"{_fmt_price(e.current_input_price)} input / "
            f"{_fmt_price(e.current_output_price)} output  [dim](per Mtok)[/]"
        )
    console.print(Panel("\n".join(body_lines), title=title, border_style="#7B2CBF", padding=(1, 2)))

    # Ranks across all categories
    if e.ranks:
        rt = Table(title="Where it ranks", show_header=True, header_style="bold #00F5D4")
        rt.add_column("Category")
        rt.add_column("Rank", justify="right")
        rt.add_column("Rating", justify="right")
        for r in e.ranks:
            label = ARENA_CATEGORIES.get(r.category, r.category)
            rt.add_row(label, f"#{r.rank}", f"{r.rating:.0f}")
        console.print(rt)

    # Price history
    if len(e.price_history) >= 2:
        ht = Table(title="Price history", show_header=True, header_style="bold #00F5D4")
        ht.add_column("Date")
        ht.add_column("Input", justify="right")
        ht.add_column("Output", justify="right")
        for h in e.price_history:
            ht.add_row(
                fmt_snapshot_date(h.snapshot_at),
                _fmt_price(h.input_per_mtok_usd),
                _fmt_price(h.output_per_mtok_usd),
            )
        console.print(ht)
    elif e.price_history:
        console.print(f"[dim]Price history: only one snapshot so far — check back in a few days.[/]")


def render_compare(rows: list[dict]) -> None:
    table = Table(title="Comparison")
    table.add_column("Field")
    for r in rows:
        table.add_column(r["arena_name"])
    fields = [
        ("Arena rating", lambda r: f"{r['rating']:.0f}" if r.get("rating") else "—"),
        ("Arena rank", lambda r: f"#{r['rank']}" if r.get("rank") else "—"),
        ("$/Mtok in",   lambda r: _fmt_price(r.get("input_per_mtok_usd"))),
        ("$/Mtok out",  lambda r: _fmt_price(r.get("output_per_mtok_usd"))),
        ("Context",     lambda r: _fmt_ctx(r.get("context_length"))),
        ("Modality",    lambda r: r.get("modality") or "—"),
        ("OpenRouter",  lambda r: r.get("openrouter_id") or "—"),
    ]
    for label, fn in fields:
        table.add_row(label, *(fn(r) for r in rows))
    console.print(table)
