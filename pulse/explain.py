"""Build a deep-view summary for a single model."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime


@dataclass
class CategoryRank:
    category: str
    rank: int
    rating: float


@dataclass
class PriceSnapshot:
    snapshot_at: str
    input_per_mtok_usd: float | None
    output_per_mtok_usd: float | None


@dataclass
class Explanation:
    arena_name: str
    openrouter_id: str | None
    confidence: str | None
    organization: str | None
    context_length: int | None
    modality: str | None
    current_input_price: float | None
    current_output_price: float | None
    ranks: list[CategoryRank]
    price_history: list[PriceSnapshot]


def _organization_from_or_id(or_id: str | None) -> str | None:
    if not or_id or "/" not in or_id:
        return None
    return or_id.split("/", 1)[0]


def find_arena_name(conn: sqlite3.Connection, query: str) -> str | None:
    """Resolve a substring to an exact arena model name (best Arena rank wins)."""
    row = conn.execute(
        """
        SELECT model_name FROM arena_snapshots
        WHERE snapshot_at = (SELECT MAX(snapshot_at) FROM arena_snapshots)
          AND model_name LIKE ?
        ORDER BY rank
        LIMIT 1
        """,
        (f"%{query}%",),
    ).fetchone()
    return row["model_name"] if row else None


def explain(conn: sqlite3.Connection, query: str) -> Explanation | None:
    name = find_arena_name(conn, query)
    if not name:
        return None

    alias = conn.execute(
        "SELECT openrouter_id, confidence FROM aliases WHERE arena_name = ?",
        (name,),
    ).fetchone()
    or_id = alias["openrouter_id"] if alias else None
    confidence = alias["confidence"] if alias else None

    or_row = None
    if or_id:
        or_row = conn.execute(
            """
            SELECT context_length, modality, input_per_mtok_usd, output_per_mtok_usd
            FROM openrouter_snapshots
            WHERE model_id = ?
              AND snapshot_at = (SELECT MAX(snapshot_at) FROM openrouter_snapshots)
            """,
            (or_id,),
        ).fetchone()

    rank_rows = conn.execute(
        """
        SELECT a.category AS category, a.rank AS rank, a.rating AS rating
        FROM arena_snapshots a
        WHERE a.model_name = ?
          AND a.snapshot_at = (
            SELECT MAX(snapshot_at) FROM arena_snapshots
            WHERE category = a.category
          )
        ORDER BY a.rating DESC
        """,
        (name,),
    ).fetchall()
    ranks = [CategoryRank(r["category"], r["rank"], r["rating"]) for r in rank_rows]

    price_history: list[PriceSnapshot] = []
    if or_id:
        hist_rows = conn.execute(
            """
            SELECT snapshot_at, input_per_mtok_usd, output_per_mtok_usd
            FROM openrouter_snapshots
            WHERE model_id = ?
            ORDER BY snapshot_at DESC
            LIMIT 10
            """,
            (or_id,),
        ).fetchall()
        price_history = [
            PriceSnapshot(r["snapshot_at"], r["input_per_mtok_usd"], r["output_per_mtok_usd"])
            for r in hist_rows
        ]

    return Explanation(
        arena_name=name,
        openrouter_id=or_id,
        confidence=confidence,
        organization=_organization_from_or_id(or_id),
        context_length=or_row["context_length"] if or_row else None,
        modality=or_row["modality"] if or_row else None,
        current_input_price=or_row["input_per_mtok_usd"] if or_row else None,
        current_output_price=or_row["output_per_mtok_usd"] if or_row else None,
        ranks=ranks,
        price_history=price_history,
    )


def fmt_snapshot_date(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d")
