"""Scrape arena.ai (LMSYS Chatbot Arena) leaderboard.

The page is server-rendered Next.js. The leaderboard rows are inside
self.__next_f.push([1, "<json string>"]) chunks. After unescaping the JS
string, each chunk contains JSON objects shaped like:

    {"rank":1, "rankUpper":1, "rankLower":6,
     "modelDisplayName":"claude-opus-4-7-thinking",
     "rating":1503.08, "ratingUpper":1511.08, "ratingLower":1495.0, ...}

We extract them with regex rather than parsing the full streaming format —
the structure is shallow and predictable, and the file is small.
"""

import re
import sqlite3
from dataclasses import dataclass

import httpx

from ..cache import is_fresh, mark_fetched, now_iso
from ..config import ARENA_CATEGORIES

URL_TEMPLATE = "https://arena.ai/leaderboard/{category}"

_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.DOTALL)
_ENTRY_RE = re.compile(
    r'"rank":(?P<rank>\d+),'
    r'"rankUpper":\d+,"rankLower":\d+'
    r'(?:,"[a-zA-Z]+":[^,}]+)*?,'  # tolerate extra fields like rankStyleControl
    r'"modelDisplayName":"(?P<name>[^"]+)",'
    r'"rating":(?P<rating>[\d.]+),'
    r'"ratingUpper":(?P<upper>[\d.]+),'
    r'"ratingLower":(?P<lower>[\d.]+)'
)


@dataclass(frozen=True)
class ArenaEntry:
    category: str
    rank: int
    model_name: str
    rating: float
    rating_lower: float
    rating_upper: float


def _decode_chunks(html: str) -> str:
    parts: list[str] = []
    for raw in _CHUNK_RE.findall(html):
        try:
            parts.append(raw.encode("utf-8").decode("unicode_escape"))
        except UnicodeDecodeError:
            continue
    return "\n".join(parts)


def parse_html(html: str, category: str) -> list[ArenaEntry]:
    decoded = _decode_chunks(html)
    seen: dict[str, ArenaEntry] = {}
    for m in _ENTRY_RE.finditer(decoded):
        name = m.group("name")
        if name in seen:
            continue
        seen[name] = ArenaEntry(
            category=category,
            rank=int(m.group("rank")),
            model_name=name,
            rating=float(m.group("rating")),
            rating_lower=float(m.group("lower")),
            rating_upper=float(m.group("upper")),
        )
    return sorted(seen.values(), key=lambda e: e.rank)


def fetch_category(category: str) -> list[ArenaEntry]:
    url = URL_TEMPLATE.format(category=category)
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        r = client.get(url, headers={"User-Agent": "Mozilla/5.0 llm-pulse/0.1"})
        r.raise_for_status()
        return parse_html(r.text, category)


def fetch_all() -> list[ArenaEntry]:
    out: list[ArenaEntry] = []
    for cat in ARENA_CATEGORIES:
        out.extend(fetch_category(cat))
    return out


def store(conn: sqlite3.Connection, entries: list[ArenaEntry]) -> str:
    snap = now_iso()
    conn.executemany(
        """INSERT OR REPLACE INTO arena_snapshots
           (snapshot_at, category, rank, model_name, rating, rating_lower, rating_upper)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (snap, e.category, e.rank, e.model_name, e.rating, e.rating_lower, e.rating_upper)
            for e in entries
        ],
    )
    mark_fetched(conn, "arena")
    return snap


def refresh(conn: sqlite3.Connection, ttl_hours: float, force: bool = False) -> int:
    if not force and is_fresh(conn, "arena", ttl_hours):
        return 0
    entries = fetch_all()
    if not entries:
        raise RuntimeError(
            "Arena fetch returned 0 entries — page format may have changed."
        )
    store(conn, entries)
    return len(entries)
