import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .cache import get_meta, now_iso, set_meta, snapshot_at_or_before


@dataclass
class ArenaChange:
    category: str
    model_name: str
    delta_rank: int | None  # None if model is new
    delta_rating: float | None
    new_rank: int
    new_rating: float


@dataclass
class PriceChange:
    model_id: str
    field: str  # "input" or "output"
    old: float
    new: float
    pct: float


@dataclass
class NewModel:
    model_id: str
    name: str


@dataclass
class Digest:
    since: str  # ISO timestamp of comparison baseline
    arena_changes: list[ArenaChange]
    new_arena_models: list[tuple[str, str]]  # (category, name)
    price_changes: list[PriceChange]
    new_or_models: list[NewModel]


def _baseline_snapshot(
    conn: sqlite3.Connection, table: str, since_iso: str | None
) -> str | None:
    if since_iso:
        when = datetime.fromisoformat(since_iso)
    else:
        when = datetime.now(timezone.utc) - timedelta(days=7)
    return snapshot_at_or_before(conn, table, when)


def _arena_diff(
    conn: sqlite3.Connection, baseline_snap: str, latest_snap: str
) -> tuple[list[ArenaChange], list[tuple[str, str]]]:
    old_rows = conn.execute(
        "SELECT category, model_name, rank, rating FROM arena_snapshots WHERE snapshot_at = ?",
        (baseline_snap,),
    ).fetchall()
    new_rows = conn.execute(
        "SELECT category, model_name, rank, rating FROM arena_snapshots WHERE snapshot_at = ?",
        (latest_snap,),
    ).fetchall()
    old = {(r["category"], r["model_name"]): (r["rank"], r["rating"]) for r in old_rows}
    new = {(r["category"], r["model_name"]): (r["rank"], r["rating"]) for r in new_rows}

    changes: list[ArenaChange] = []
    new_models: list[tuple[str, str]] = []
    for key, (rank, rating) in new.items():
        cat, name = key
        if key not in old:
            new_models.append(key)
            changes.append(ArenaChange(cat, name, None, None, rank, rating))
        else:
            old_rank, old_rating = old[key]
            drank = rank - old_rank
            drating = rating - old_rating
            if drank != 0 or abs(drating) >= 1.0:
                changes.append(ArenaChange(cat, name, drank, drating, rank, rating))
    # Sort: top of each category first, biggest movers up top
    changes.sort(key=lambda c: (c.category, -abs(c.delta_rating or 0)))
    return changes, new_models


def _or_diff(
    conn: sqlite3.Connection, baseline_snap: str, latest_snap: str
) -> tuple[list[PriceChange], list[NewModel]]:
    old_rows = conn.execute(
        "SELECT model_id, name, input_per_mtok_usd, output_per_mtok_usd "
        "FROM openrouter_snapshots WHERE snapshot_at = ?",
        (baseline_snap,),
    ).fetchall()
    new_rows = conn.execute(
        "SELECT model_id, name, input_per_mtok_usd, output_per_mtok_usd "
        "FROM openrouter_snapshots WHERE snapshot_at = ?",
        (latest_snap,),
    ).fetchall()
    old = {r["model_id"]: r for r in old_rows}
    price_changes: list[PriceChange] = []
    new_models: list[NewModel] = []
    for r in new_rows:
        if r["model_id"] not in old:
            new_models.append(NewModel(r["model_id"], r["name"]))
            continue
        prev = old[r["model_id"]]
        for field, old_key, new_val in [
            ("input", "input_per_mtok_usd", r["input_per_mtok_usd"]),
            ("output", "output_per_mtok_usd", r["output_per_mtok_usd"]),
        ]:
            old_val = prev[old_key]
            if old_val is None or new_val is None or old_val == 0:
                continue
            if abs(new_val - old_val) / old_val < 0.05:  # ignore <5% noise
                continue
            price_changes.append(
                PriceChange(
                    model_id=r["model_id"],
                    field=field,
                    old=old_val,
                    new=new_val,
                    pct=(new_val - old_val) / old_val * 100,
                )
            )
    price_changes.sort(key=lambda p: -abs(p.pct))
    return price_changes, new_models


def build_digest(conn: sqlite3.Connection, since_days: int | None = None) -> Digest:
    last_run = get_meta(conn, "last_digest_at")
    if since_days is not None:
        since_iso = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat(
            timespec="seconds"
        )
    else:
        since_iso = last_run

    arena_latest = conn.execute(
        "SELECT MAX(snapshot_at) AS s FROM arena_snapshots"
    ).fetchone()["s"]
    or_latest = conn.execute(
        "SELECT MAX(snapshot_at) AS s FROM openrouter_snapshots"
    ).fetchone()["s"]

    arena_baseline = _baseline_snapshot(conn, "arena_snapshots", since_iso)
    or_baseline = _baseline_snapshot(conn, "openrouter_snapshots", since_iso)

    arena_changes: list[ArenaChange] = []
    new_arena_models: list[tuple[str, str]] = []
    if arena_baseline and arena_latest and arena_baseline != arena_latest:
        arena_changes, new_arena_models = _arena_diff(conn, arena_baseline, arena_latest)

    price_changes: list[PriceChange] = []
    new_or_models: list[NewModel] = []
    if or_baseline and or_latest and or_baseline != or_latest:
        price_changes, new_or_models = _or_diff(conn, or_baseline, or_latest)

    return Digest(
        since=since_iso or "(no prior snapshot)",
        arena_changes=arena_changes,
        new_arena_models=new_arena_models,
        price_changes=price_changes,
        new_or_models=new_or_models,
    )


def mark_digest_run(conn: sqlite3.Connection) -> None:
    set_meta(conn, "last_digest_at", now_iso())
