"""Load .env the way scripts/stack.sh does, so a script measures the live system.

The application does not read .env. stack.sh does:

    [ -f .env ] && { set -a; . ./.env; set +a; }

so the API and the UI get ASOIA_MILVUS_URI and NIM_MODE, and a script run straight
from the prompt does not. That is not a missing convenience, it is a wrong answer.
With ASOIA_MILVUS_URI unset the retrieval backend falls back to EMBEDDED Milvus
Lite at data/generated/milvus.db, so

    .venv/bin/python scripts/evaluate.py --with-llm

measured a different, stale vector store - a collection still carrying 2048-dim
vectors from the hosted embedder that was retired in pass 28 - and reported its
failure as the system's recall. Nothing errored. The command in the README, run
exactly as written, answered a question about something else.

Variables already in the environment win, so NIM_MODE=hosted .venv/bin/python ...
still overrides, and nothing here is ever printed: .env holds the API key.
"""
from __future__ import annotations
import os
import pathlib


def load(path: str = ".env") -> list[str]:
    """-> the NAMES taken from the file. Never the values."""
    p = pathlib.Path(path)
    if not p.exists():
        return []
    took = []
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k and k not in os.environ:
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            os.environ[k] = v
            took.append(k)
    return took


load()
