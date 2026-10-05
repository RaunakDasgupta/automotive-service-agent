#!/usr/bin/env python3
"""Twenty-ninth pass: the Vector store tab crashed on a key I renamed.

Run from the project root:   .venv/bin/python quality_pass29.py

Pass 27 put Milvus and LanceDB behind one interface, and the shared vocabulary
is Milvus's: `index_stats()` returns `collection` where it used to return
`table`. One line in the UI still read `s['table']`, so opening Data & Retrieval
-> Vector store raised

    KeyError: 'table'

and took the tab down. The store was fine; 1,949 chunks were sitting in Milvus
being searched correctly at the time.

That is the whole lesson: changing a dict's shape is an API change, and the
compiler does not help. The fix reads every field with `.get`, names the backend
and mode - which the old panel could not, because there was only ever one store
- and surfaces the staleness summary that pass 27 added underneath.
"""
import sys, pathlib, ast

ROOT = pathlib.Path(".")
CHANGES = []


def edit(rel, old, new, label, skip_if=None):
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"FAIL: {rel} not found - run from the project root")
    s = p.read_text()
    if skip_if and skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    n = s.count(old)
    if n != 1:
        sys.exit(f"FAIL: {label}: anchor found {n} times in {rel}, expected 1.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")



edit('app/ui/gradio_app.py',
     '    return (f"### Vector index\\n\\n"\n            f"| | |\\n|---|---|\\n"\n            f"| Location | `{s[\'uri\']}` / `{s[\'table\']}` |\\n"\n            f"| Chunks | {s.get(\'rows\')} |\\n"\n            f"| Dimensions | {s.get(\'dim\')} |\\n"\n            f"| Built | {s.get(\'built_at\', \'—\')} |\\n"\n            f"| Size | {size} |\\n"\n            f"| Health | {health} |{warn}")',
     '    # `collection`, not `table`: pass 27 put Milvus and LanceDB behind one\n    # interface and the shared vocabulary is Milvus\'s. This line still said\n    # `s[\'table\']` after that change and took the whole Vector store tab down\n    # with a KeyError - the cost of changing a dict\'s shape without grepping for\n    # who reads it. `.get` everywhere below for the same reason.\n    st = s.get("staleness") or {}\n    if st.get("ok") is False:\n        warn += ("\\n\\n**The index does not match the database.** "\n                 + "; ".join(st.get("reasons", []))\n                 + f"\\n\\n```\\n{st.get(\'fix\', \'\')}\\n```")\n    return (f"### Vector index\\n\\n"\n            f"| | |\\n|---|---|\\n"\n            f"| Store | **{s.get(\'backend\', \'?\')}** ({s.get(\'mode\', \'?\')}) |\\n"\n            f"| Location | `{s.get(\'uri\', \'?\')}` / `{s.get(\'collection\', \'?\')}` |\\n"\n            f"| Chunks | {s.get(\'rows\')} |\\n"\n            f"| Dimensions | {s.get(\'dim\')} |\\n"\n            f"| Built | {s.get(\'built_at\', \'—\')} |\\n"\n            f"| Size | {size} |\\n"\n            f"| Health | {health} |\\n"\n            f"| Matches the database | "\n            f"{\'yes\' if st.get(\'ok\') else (\'no\' if st.get(\'ok\') is False else \'—\')} |"\n            f"{warn}")',
     'gradio_app.py  the index panel reads the new stats shape',
     skip_if='| Store | **')


# ==================== verify
print("Quality pass 29:")
for c in CHANGES:
    print(c)
g = (ROOT / "app/ui/gradio_app.py").read_text()
ast.parse(g)
print("\ngradio_app.py parses cleanly.")

sys.path.insert(0, ".")
bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}" + (f"  ({detail})" if detail else ""))


print()
# The interpolation, not the bare string: the comment above the fix quotes
# `s['table']` while explaining it, so asserting on the substring alone fails
# against correct code. Second time a check in this project has been wrong
# rather than the code - see pass 24's endpoint count.
chk("the renamed key is no longer interpolated", "{s['table']}" not in g)
chk("every field is read defensively",
    "s.get('collection'" in g or 's.get("collection"' in g)
chk("the panel names the backend", "s.get('backend'" in g)
chk("and reports whether the index matches the database",
    "Matches the database" in g)

# render it for real - this is what crashed
try:
    import app.ui.gradio_app as G
    md = G.ui_review_index()
    chk("the panel renders", isinstance(md, str) and len(md) > 40,
        md.split(chr(10))[0])
    print()
    for line in md.splitlines()[:12]:
        print("    " + line)
except Exception as e:
    chk("the panel renders", False, f"{type(e).__name__}: {e}")

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
sys.exit(1 if bad else 0)
