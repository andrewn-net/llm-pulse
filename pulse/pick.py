import sqlite3
from dataclasses import dataclass

from .config import TASK_KEYWORDS


def task_to_category(task: str) -> str:
    """Map a free-text task description to an arena category slug."""
    t = task.lower()
    for cat, kws in TASK_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return cat
    return "text"


def parse_context(value: str | int) -> int:
    """Parse '200k', '1m', '128000' → tokens."""
    if isinstance(value, int):
        return value
    s = str(value).strip().lower().replace(",", "")
    if s.endswith("k"):
        return int(float(s[:-1]) * 1_000)
    if s.endswith("m"):
        return int(float(s[:-1]) * 1_000_000)
    return int(s)


@dataclass
class Pick:
    arena_name: str
    rank: int
    rating: float
    openrouter_id: str | None
    input_per_mtok_usd: float | None
    output_per_mtok_usd: float | None
    context_length: int | None
    modality: str | None = None

    @property
    def avg_price(self) -> float | None:
        if self.input_per_mtok_usd is None or self.output_per_mtok_usd is None:
            return None
        return (self.input_per_mtok_usd + self.output_per_mtok_usd) / 2

    @property
    def is_free(self) -> bool:
        if self.openrouter_id and self.openrouter_id.endswith(":free"):
            return True
        return self.input_per_mtok_usd == 0 and self.output_per_mtok_usd == 0

    @property
    def is_multimodal(self) -> bool:
        return bool(self.modality and "image" in self.modality)


def top_picks(
    conn: sqlite3.Connection,
    category: str,
    limit: int = 10,
    only_priced: bool = False,
    max_avg_price: float | None = None,
    min_context: int | None = None,
    free_only: bool = False,
    multimodal_only: bool = False,
) -> list[Pick]:
    rows = conn.execute(
        """
        SELECT a.model_name AS arena_name, a.rank AS rank, a.rating AS rating,
               al.openrouter_id AS or_id,
               o.input_per_mtok_usd  AS in_price,
               o.output_per_mtok_usd AS out_price,
               o.context_length      AS ctx,
               o.modality            AS modality
        FROM arena_snapshots a
        LEFT JOIN aliases al ON al.arena_name = a.model_name
        LEFT JOIN openrouter_snapshots o
               ON o.model_id = al.openrouter_id
              AND o.snapshot_at = (SELECT MAX(snapshot_at) FROM openrouter_snapshots)
        WHERE a.category = ?
          AND a.snapshot_at = (
            SELECT MAX(snapshot_at) FROM arena_snapshots WHERE category = ?
          )
        ORDER BY a.rank
        """,
        (category, category),
    ).fetchall()

    # When the user asks for free, the alias may point at the paid base
    # (e.g. meta-llama/llama-3.3-70b-instruct) when a :free sibling exists
    # (meta-llama/llama-3.3-70b-instruct:free). Pull the :free variants
    # so we can swap in their id + price.
    free_variants: dict[str, dict] = {}
    if free_only:
        free_rows = conn.execute(
            """
            SELECT model_id, input_per_mtok_usd, output_per_mtok_usd,
                   context_length, modality
            FROM openrouter_snapshots
            WHERE model_id LIKE '%:free'
              AND snapshot_at = (SELECT MAX(snapshot_at) FROM openrouter_snapshots)
            """
        ).fetchall()
        free_variants = {r["model_id"]: dict(r) for r in free_rows}

    out: list[Pick] = []
    for r in rows:
        or_id = r["or_id"]
        in_price = r["in_price"]
        out_price = r["out_price"]
        ctx = r["ctx"]
        modality = r["modality"]

        if free_only and or_id:
            # Already a free model? Keep it.
            if not (or_id.endswith(":free") or (in_price == 0 and out_price == 0)):
                # Try the :free sibling.
                sibling = free_variants.get(f"{or_id}:free")
                if sibling:
                    or_id = sibling["model_id"]
                    in_price = sibling["input_per_mtok_usd"]
                    out_price = sibling["output_per_mtok_usd"]
                    ctx = sibling["context_length"] or ctx
                    modality = sibling["modality"] or modality
                else:
                    continue  # No free variant — drop it.

        p = Pick(
            arena_name=r["arena_name"],
            rank=r["rank"],
            rating=r["rating"],
            openrouter_id=or_id,
            input_per_mtok_usd=in_price,
            output_per_mtok_usd=out_price,
            context_length=ctx,
            modality=modality,
        )
        if only_priced and p.input_per_mtok_usd is None:
            continue
        if free_only and not p.is_free:
            continue
        if multimodal_only and not p.is_multimodal:
            continue
        if max_avg_price is not None and (p.avg_price is None or p.avg_price > max_avg_price):
            continue
        if min_context is not None and (p.context_length is None or p.context_length < min_context):
            continue
        out.append(p)
        if len(out) >= limit:
            break
    return out


def best_value(picks: list[Pick]) -> Pick | None:
    """Highest rating-per-dollar among priced picks."""
    priced = [p for p in picks if p.avg_price and p.avg_price > 0]
    if not priced:
        return None
    return max(priced, key=lambda p: p.rating / p.avg_price)
