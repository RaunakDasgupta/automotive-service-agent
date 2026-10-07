#!/usr/bin/env python
"""Build the vector index, against the store and the embedder .env actually names.

    .venv/bin/python scripts/build_index.py            # build
    .venv/bin/python scripts/build_index.py --check     # say what it WOULD use

WHY THIS EXISTS AND IS NOT A ONE-LINER

Five places in this repo used to print

    .venv/bin/python -c 'from app.retrieval.index import build; print(build())'

and every one of them was wrong in the same silent way. The application does not
read .env - stack.sh does, which is the whole subject of scripts/_env.py - so
that command runs with ASOIA_MILVUS_URI unset and NIM_MODE unset. Measured, on a
box where .env says standalone Milvus and local NIMs:

    store     falls back to EMBEDDED Milvus Lite at data/generated/milvus.db,
              the decoy that scripts/store_report.py exists to warn about, while
              the API keeps serving from the standalone Milvus that still holds
              the old index
    embedder  NIM_MODE unset -> "auto" -> probes, and before the containers
              finish their TRT builds that means HOSTED, 2048-dimensional,
              instead of the local 1024 you set NIM_MODE=local to get

Both failures produce a build that reports success. The second is worse than it
looks: app/review/store.py prints that command in the staleness error, so the
dimension guard would correctly detect a mismatched index and then hand you a
command that rebuilt a DIFFERENT store at the wrong width. Fixing the five
strings would not have helped - the next person to need the index writes the
one-liner again, because it is the obvious thing to write.

So the env load lives in a file that always does it, and the five call sites
point here. --check prints the pair before committing minutes to embedding,
because "did NIM_MODE take effect" is the question you actually have after
editing .env, and the old answer was to build and find out.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")
import _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py


def _target() -> tuple[str, str, str, str]:
    """-> (store_uri, store_kind, embed_model, embed_mode).

    Imported inside the function, after _env, deliberately: app/retrieval has
    module-level constants read from os.environ at import time, so loading .env
    after importing it would be too late for exactly the variables that matter.
    """
    from app.nim.client import resolve
    from app.retrieval.backend import backend

    _base, model, mode = resolve("embed")       # (base_url, model_id, mode)
    b = backend()
    return b.uri, b.mode, model, mode


def main(argv: list[str]) -> int:
    import json

    try:
        uri, how, model, mode = _target()
    except Exception as e:
        print(f"cannot resolve the target: {type(e).__name__}: {e}")
        return 1

    print(f"  store     {uri or '(unset)'}   ({how})")
    print(f"  embedder  {model}   ({mode})")
    if how == "embedded":
        print("  note      that is the EMBEDDED Milvus Lite file, not a server.")
        print("            If .env sets ASOIA_MILVUS_URI, this process did not "
              "read it.")

    if "--check" in argv:
        from app.retrieval.index import index_meta
        have = index_meta()
        if have:
            print(f"  on disk   {have.get('embed_model')}  "
                  f"{have.get('dim')}-dimensional, {have.get('rows')} rows")
            if have.get("embed_model") != model:
                print("  MISMATCH  the index on disk was built with a different "
                      "embedder; building now would be the right move.")
        else:
            print("  on disk   nothing recorded - no index, or one built before "
                  "this was tracked")
        return 0

    from app.retrieval.index import build, index_meta

    print("  building ...")
    out = build()
    if out.get("error"):
        print(f"  FAILED    {out['error']}")
        return 1
    print("  " + json.dumps(out, sort_keys=True))
    print("  recorded  " + json.dumps(index_meta(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
