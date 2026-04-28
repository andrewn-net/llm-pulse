"""Slack incoming-webhook integration: store URL, format messages, send."""

from __future__ import annotations

import sqlite3

import httpx

from .cache import get_meta, set_meta
from .digest import Digest
from .pick import Pick

WEBHOOK_KEY = "slack_webhook_url"


def get_webhook(conn: sqlite3.Connection) -> str | None:
    import os
    return os.environ.get("LLMPULSE_SLACK_WEBHOOK") or get_meta(conn, WEBHOOK_KEY)


def save_webhook(conn: sqlite3.Connection, url: str) -> None:
    set_meta(conn, WEBHOOK_KEY, url.strip())


def clear_webhook(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM meta WHERE key = ?", (WEBHOOK_KEY,))


def post(url: str, text: str, blocks: list | None = None) -> None:
    """POST to a Slack incoming webhook. Payload field is always 'text'."""
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    r = httpx.post(url, json=payload, timeout=10.0)
    r.raise_for_status()


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


def _human_date(iso: str) -> str:
    """'2026-04-27T22:05:00+00:00' → 'Apr 27, 2026'"""
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(iso).astimezone(timezone.utc)
        return dt.strftime("%b %-d, %Y")
    except Exception:
        return iso


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _divider() -> dict:
    return {"type": "divider"}


def _build_plain(d: Digest, since: str, prefix: str = "") -> str:
    """Plain-text body — no mrkdwn markers, works in both Workflow Builder and notifications."""
    has_changes = bool(d.arena_changes or d.price_changes or d.new_or_models)
    lines = []
    if prefix:
        lines += [prefix, ""]
    lines += [f"🔍 LLM Pulse Digest — {since}", ""]

    if not has_changes:
        lines.append("✅ All quiet — no rank changes, price moves, or new models since last run.")
        return "\n".join(lines)

    if d.arena_changes:
        by_cat: dict[str, list] = {}
        for c in d.arena_changes:
            by_cat.setdefault(c.category, []).append(c)
        for cat, items in by_cat.items():
            lines.append(f"── Arena: {cat} ──")
            for c in items[:8]:
                if c.delta_rank is None:
                    lines.append(f"  ✨ NEW  #{c.new_rank}  {c.model_name}  ({c.new_rating:.0f})")
                else:
                    arrow = "↑" if (c.delta_rating or 0) > 0 else "↓"
                    sign  = "+" if (c.delta_rating or 0) > 0 else ""
                    lines.append(
                        f"  {arrow} {c.model_name}  {sign}{c.delta_rating:.1f} pts → "
                        f"{c.new_rating:.0f},  rank #{c.new_rank}"
                    )
            lines.append("")

    if d.price_changes:
        lines.append("── Prices ──")
        for p in d.price_changes[:10]:
            arrow = "↓" if p.pct < 0 else "↑"
            lines.append(f"  {arrow} {p.model_id} {p.field}:  ${p.old:.2f} → ${p.new:.2f}  ({p.pct:+.0f}%)")
        lines.append("")

    if d.new_or_models:
        lines.append(f"── New on OpenRouter ({len(d.new_or_models)}) ──")
        for m in d.new_or_models[:10]:
            lines.append(f"  + {m.model_id} — {m.name}")
        if len(d.new_or_models) > 10:
            lines.append(f"  …and {len(d.new_or_models) - 10} more")

    return "\n".join(lines).rstrip()


def format_digest(d: Digest, prefix: str = "") -> tuple[str, list]:
    """Return (plain_text, blocks).
    - plain_text: clean readable text for Workflow Builder webhooks & notifications
    - blocks: Block Kit layout for Incoming Webhooks (ignored by Workflow Builder)
    """
    since = _human_date(d.since)
    text = _build_plain(d, since, prefix=prefix)

    # Block Kit — only rendered by Incoming Webhooks
    blocks: list = [
        {"type": "header", "text": {"type": "plain_text", "text": "🔍 LLM Pulse Digest", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Since *{since}*"}]},
        _divider(),
    ]

    if not (d.arena_changes or d.price_changes or d.new_or_models):
        blocks.append(_section("✅ *All quiet* — no rank changes, price moves, or new models since last run."))
        return text, blocks

    if d.arena_changes:
        by_cat: dict[str, list] = {}
        for c in d.arena_changes:
            by_cat.setdefault(c.category, []).append(c)
        for cat, items in by_cat.items():
            cat_lines = [f"*Arena — {cat}*"]
            for c in items[:8]:
                if c.delta_rank is None:
                    cat_lines.append(f"✨ NEW  #{c.new_rank}  *{c.model_name}*  ({c.new_rating:.0f})")
                else:
                    arrow = "↑" if (c.delta_rating or 0) > 0 else "↓"
                    sign  = "+" if (c.delta_rating or 0) > 0 else ""
                    cat_lines.append(
                        f"{arrow} {c.model_name}  {sign}{c.delta_rating:.1f} pts → "
                        f"{c.new_rating:.0f},  rank #{c.new_rank}"
                    )
            blocks.append(_section("\n".join(cat_lines)))
            blocks.append(_divider())

    if d.price_changes:
        price_lines = ["*Price changes*"]
        for p in d.price_changes[:10]:
            arrow = "↓" if p.pct < 0 else "↑"
            price_lines.append(f"{arrow} `{p.model_id}` {p.field}:  ${p.old:.2f} → ${p.new:.2f}  ({p.pct:+.0f}%)")
        blocks.append(_section("\n".join(price_lines)))
        blocks.append(_divider())

    if d.new_or_models:
        new_lines = [f"*New on OpenRouter*  ({len(d.new_or_models)})"]
        for m in d.new_or_models[:10]:
            new_lines.append(f"+ `{m.model_id}` — {m.name}")
        if len(d.new_or_models) > 10:
            new_lines.append(f"_…and {len(d.new_or_models) - 10} more_")
        blocks.append(_section("\n".join(new_lines)))

    return text, blocks


def format_picks(picks: list[Pick], category: str) -> str:
    if not picks:
        return f"*LLM Pulse picks ({category})* — no models matched."
    lines = [f"*LLM Pulse picks — {category}*", ""]
    for p in picks:
        price = (
            "free"
            if (p.input_per_mtok_usd == 0 and p.output_per_mtok_usd == 0)
            else f"{_fmt_price(p.input_per_mtok_usd)}/{_fmt_price(p.output_per_mtok_usd)}"
        )
        ctx = _fmt_ctx(p.context_length)
        lines.append(
            f"• #{p.rank}  *{p.arena_name}*  · rating {p.rating:.0f}  · {price}  · ctx {ctx}"
        )
    return "\n".join(lines)
