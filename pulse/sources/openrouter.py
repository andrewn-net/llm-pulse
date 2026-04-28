import sqlite3
from dataclasses import dataclass

import httpx

from ..cache import is_fresh, mark_fetched, now_iso

URL = "https://openrouter.ai/api/v1/models"


@dataclass(frozen=True)
class ORModel:
    model_id: str
    name: str
    context_length: int | None
    input_per_mtok_usd: float | None
    output_per_mtok_usd: float | None
    modality: str | None


def _to_per_mtok(per_token: str | None) -> float | None:
    if per_token is None or per_token == "":
        return None
    return float(per_token) * 1_000_000


def fetch() -> list[ORModel]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        r = client.get(URL, headers={"User-Agent": "llm-pulse/0.1"})
        r.raise_for_status()
        payload = r.json()

    out: list[ORModel] = []
    for m in payload.get("data", []):
        pricing = m.get("pricing") or {}
        arch = m.get("architecture") or {}
        out.append(
            ORModel(
                model_id=m["id"],
                name=m.get("name", m["id"]),
                context_length=m.get("context_length"),
                input_per_mtok_usd=_to_per_mtok(pricing.get("prompt")),
                output_per_mtok_usd=_to_per_mtok(pricing.get("completion")),
                modality=arch.get("modality"),
            )
        )
    return out


def store(conn: sqlite3.Connection, models: list[ORModel]) -> str:
    snap = now_iso()
    conn.executemany(
        """INSERT OR REPLACE INTO openrouter_snapshots
           (snapshot_at, model_id, name, context_length,
            input_per_mtok_usd, output_per_mtok_usd, modality)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                snap,
                m.model_id,
                m.name,
                m.context_length,
                m.input_per_mtok_usd,
                m.output_per_mtok_usd,
                m.modality,
            )
            for m in models
        ],
    )
    mark_fetched(conn, "openrouter")
    return snap


def refresh(conn: sqlite3.Connection, ttl_hours: float, force: bool = False) -> int:
    """Fetch + store if stale. Returns number of models written, or 0 if skipped."""
    if not force and is_fresh(conn, "openrouter", ttl_hours):
        return 0
    models = fetch()
    store(conn, models)
    return len(models)
