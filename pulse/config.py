from pathlib import Path
from platformdirs import user_data_dir

APP_NAME = "llm-pulse"

DATA_DIR = Path(user_data_dir(APP_NAME))
DB_PATH = DATA_DIR / "cache.db"

# How long cached source data is considered fresh. Override per-command with --refresh.
DEFAULT_TTL_HOURS = 6

# Arena categories we track. Each maps to a URL slug at arena.ai/leaderboard/<slug>.
ARENA_CATEGORIES = {
    "text": "Overall (general chat & reasoning)",
    "code": "Coding & engineering",
    "vision": "Image understanding",
    "document": "Long-form document analysis",
    "search": "Web search & retrieval",
}

# Free-text task keywords → arena category. Order matters: first match wins.
TASK_KEYWORDS = {
    "code": [
        "code", "coding", "programming", "debug", "refactor", "review",
        "python", "typescript", "javascript", "rust", "go", "java", "sql",
        "function", "script", "compile", "bug", "lint",
    ],
    "vision": [
        "image", "vision", "ocr", "screenshot", "diagram", "photo",
        "visual", "picture", "chart",
    ],
    "document": [
        "pdf", "document", "doc ", "paper", "report", "contract",
        "long ", "summarize", "summarise", "extract from", "analyze a",
        "long-form", "manuscript", "transcript", "ebook",
    ],
    "search": [
        "search", "research", "web", "browse", "lookup", "look up",
        "find information", "fact-check", "fact check", "google", "current",
    ],
    # "text" is the fallback for general chat, writing, reasoning, etc.
}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
