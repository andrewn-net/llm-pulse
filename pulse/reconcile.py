"""Match arena.ai display names to OpenRouter model ids.

Arena uses lowercase-hyphenated names like "claude-opus-4-7-thinking".
OpenRouter uses provider-prefixed slugs like "anthropic/claude-opus-4.7"
sometimes with a ":thinking" or ":free" suffix.

Strategy: normalize both to a canonical token set (lowercase, drop
provider prefix, replace . with -, split on -), then score by how many
arena tokens are contained in the OR token set. Highest score wins,
ties broken by shorter OR id (prefer the canonical variant over a
specialized one).
"""

import sqlite3
from dataclasses import dataclass

from .cache import now_iso

# Tokens that are noise — they appear in many ids and shouldn't drive matching.
_STOPWORDS = {"instruct", "chat", "latest", "preview", "beta", "alpha", "v1", "v2", "v3"}


def _tokenize(s: str) -> set[str]:
    s = s.lower()
    if "/" in s:
        s = s.split("/", 1)[1]
    s = s.replace(".", "-").replace("_", "-").replace(":", "-")
    parts = [p for p in s.split("-") if p and p not in _STOPWORDS]
    return set(parts)


def score_match(arena_tokens: set[str], or_tokens: set[str]) -> int:
    if not arena_tokens:
        return 0
    overlap = len(arena_tokens & or_tokens)
    extra = len(or_tokens - arena_tokens)
    # Reward overlap heavily, lightly penalize extra tokens (prefer tighter match).
    return overlap * 10 - extra


@dataclass
class Match:
    arena_name: str
    openrouter_id: str
    score: int
    confidence: str  # "high", "medium", "low"


def reconcile(
    arena_names: list[str], openrouter_ids: list[str]
) -> list[Match]:
    or_tokenized = [(oid, _tokenize(oid)) for oid in openrouter_ids]
    out: list[Match] = []
    for name in arena_names:
        atoks = _tokenize(name)
        if not atoks:
            continue
        ranked = sorted(
            (
                (score_match(atoks, otoks), oid)
                for oid, otoks in or_tokenized
            ),
            key=lambda x: (-x[0], len(x[1])),
        )
        best_score, best_id = ranked[0]
        # Need at least 2 token overlap (e.g. "claude" + "opus") to count.
        overlap = len(atoks & dict(or_tokenized)[best_id])
        if overlap < 2:
            continue
        if overlap >= 3 and best_score >= 25:
            conf = "high"
        elif overlap >= 2 and best_score >= 15:
            conf = "medium"
        else:
            conf = "low"
        out.append(Match(name, best_id, best_score, conf))
    return out


def rebuild_aliases(conn: sqlite3.Connection) -> int:
    """Recompute the aliases table from the latest snapshots of each source."""
    arena_names = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT model_name FROM arena_snapshots "
            "WHERE snapshot_at = (SELECT MAX(snapshot_at) FROM arena_snapshots)"
        )
    ]
    or_ids = [
        r[0] for r in conn.execute(
            "SELECT model_id FROM openrouter_snapshots "
            "WHERE snapshot_at = (SELECT MAX(snapshot_at) FROM openrouter_snapshots)"
        )
    ]
    if not arena_names or not or_ids:
        return 0
    matches = reconcile(arena_names, or_ids)
    ts = now_iso()
    conn.execute("DELETE FROM aliases")
    conn.executemany(
        "INSERT INTO aliases (arena_name, openrouter_id, confidence, created_at) "
        "VALUES (?, ?, ?, ?)",
        [(m.arena_name, m.openrouter_id, m.confidence, ts) for m in matches],
    )
    return len(matches)
