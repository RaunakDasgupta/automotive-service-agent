#!/usr/bin/env python3
"""Twenty-sixth pass: the test suite stops depending on the project's database.

Run from the project root:   .venv/bin/python quality_pass26.py

WHAT WENT WRONG

On a freshly set-up instance, one test of eighty-one failed:

    assert call("get_ro_state", ro_number="RO-99-99999")["found"] is False
    E   KeyError: 'found'

The tool had behaved perfectly. `call()` caught the exception and returned

    {"error": "get_ro_state failed: OperationalError: no such table: ros"}

which names the problem exactly: the database was empty. Indexing ["found"] on
that threw the diagnosis away and replaced it with a KeyError pointing at the
error handling. Twenty minutes went into a five-second problem.

The database was empty because the release archive had been extracted a second
time over the tree, and its `data/generated/service.sqlite` is a deliberate
0-byte placeholder. Which is a fine thing for an archive to contain - and
irrelevant, because a test suite should not care.

1. THE SUITE GETS ITS OWN DATABASE.

   Eighty of the eighty-one tests use fixtures. One called a tool against
   whatever happened to be in the project, so the whole suite inherited that
   dependency. `tests/conftest.py` now points ASOIA_DB at a temporary file and
   generates forty repair orders into it - 0.04 s - before any test module
   imports `app.state.db`, which reads that variable once at import and caches a
   connection per thread. Module-level code, not a fixture, for that reason.

   Verified with the project's own data directory emptied: 81 passed, and zero
   files written into the project.

   ASOIA_TEST_DB=keep runs against the project's database instead.

   The first version of the conftest called `build_dataset` directly and every
   tool call then failed with "Cannot operate on a closed database" - because
   build_dataset closes the connection it used and dbm.connect() caches one per
   thread. That is precisely the bug `app/state/bootstrap.py` was written to
   handle in pass 25, and reaching past it walked straight back into it. It goes
   through `ensure_dataset` now, which is also what the UI and the API use.

2. THE TEST SAYS WHAT BROKE.

   Two assertions instead of one index, so an empty database reports itself as
   an empty database rather than as a KeyError in the test file.

3. AND, SINCE THE LINK IS ABOUT TO BE PUBLIC: GRADIO_AUTH.

   SHARE=1 publishes a gradio.live URL with no authentication, and the
   Technician Update tab WRITES to the event log. GRADIO_AUTH=user:pass now puts
   a login in front of it. Setting nothing changes nothing except a warning at
   startup - the default behaviour is untouched.
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
        sys.exit(f"FAIL: {label}: anchor found {n} times in {rel}, expected 1.\n"
                 "      NOTE: edits before this one HAVE been applied - this\n"
                 "      harness writes as it goes. Nothing is half-written.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


def write(rel, body, label):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        if p.read_text() == body:
            CHANGES.append(f"  skip  {label} (already present)")
        else:
            p.write_text(body)
            CHANGES.append(f"  ok    {label} (replaced)")
        return
    p.write_text(body)
    CHANGES.append(f"  ok    {label}")


# ==================== 1. the suite gets its own database

write('tests/conftest.py',
      '"""Give the test suite its own database, so it never depends on the project\'s.\n\nWHAT THIS FIXES\n\nEighty of the eighty-one tests use fixtures. One called a tool against whatever\nwas in `data/generated/service.sqlite`, so the suite quietly depended on somebody\nhaving generated a dataset first. On a fresh checkout - or after re-extracting\nthe release archive, whose `service.sqlite` is a deliberate 0-byte placeholder -\nthat one test failed like this:\n\n    assert call("get_ro_state", ro_number="RO-99-99999")["found"] is False\n    E   KeyError: \'found\'\n\nThe tool had done exactly the right thing. `call()` caught the exception and\nreturned `{"error": "get_ro_state failed: OperationalError: no such table: ros"}`,\nwhich says precisely what is wrong. Indexing `["found"]` threw that away and\nreplaced it with a KeyError pointing at the error handling instead of at the\nempty database. Twenty minutes went into a five-second problem.\n\nPass 25 made the UI and the API generate a dataset when there is none. pytest was\nthe one entry point left that could still meet an empty one.\n\nWHY A SEPARATE DATABASE\n\nRunning the tests should not write 4.5 MB into the project, and the result should\nnot depend on what happens to be in the project\'s database today. Forty repair\norders over seven days takes about 0.04 s and gives every tool a real schema with\nreal rows.\n\nThe environment variable has to be set before any test module imports\n`app.state.db`, because that module reads ASOIA_DB once at import and caches a\nconnection per thread. That is why this is module-level code in conftest rather\nthan a fixture.\n\nWHY IT GOES THROUGH ensure_dataset AND NOT build_dataset\n\nThe first version of this file called `build_dataset` directly and every tool\ncall then failed with:\n\n    ProgrammingError: Cannot operate on a closed database.\n\n`build_dataset` closes the connection it used, and `dbm.connect()` caches one per\nthread, so the cache is left holding a closed connection. That is exactly the bug\n`app/state/bootstrap.py` was written to handle in pass 25 - and calling the lower\nlevel function walked straight back into it. Going through `ensure_dataset` gets\nthe eviction, the read-back check and the empty-database reporting for free, and\nmeans the tests exercise the same bootstrap the app uses.\n\nASOIA_TEST_DB=keep runs against the project\'s own database instead, for when you\ndeliberately want to test against the data you are about to demo.\n"""\nfrom __future__ import annotations\nimport os\nimport pathlib\nimport sys\nimport tempfile\n\nROOT = pathlib.Path(__file__).resolve().parent.parent\nsys.path.insert(0, str(ROOT))\n\nif os.environ.get("ASOIA_TEST_DB", "").lower() != "keep":\n    os.environ["ASOIA_DB"] = os.path.join(\n        tempfile.mkdtemp(prefix="asoia-tests-"), "service.sqlite")\n    os.environ.setdefault("ASOIA_GEN_ROS", "40")\n    os.environ.setdefault("ASOIA_GEN_DAYS", "7")\n    # Imported only after ASOIA_DB is set: app.state.db reads it at import.\n    from app.state.bootstrap import ensure_dataset\n\n    _r = ensure_dataset(verbose=False)\n    if _r.get("status") not in ("generated", "present"):\n        raise RuntimeError(\n            f"the test database could not be prepared: {_r}. "\n            f"Run the suite with ASOIA_TEST_DB=keep to use the project\'s own.")\n',
      'tests/conftest.py  a temporary database, generated per run')


# ==================== 2. the test says what broke
edit('tests/test_agent.py',
     '    def test_unknown_ro_is_a_message_not_a_crash(self):\n        assert call("get_ro_state", ro_number="RO-99-99999")["found"] is False',
     '    def test_unknown_ro_is_a_message_not_a_crash(self):\n        r = call("get_ro_state", ro_number="RO-99-99999")\n        # A healthy "no such repair order" carries BOTH found=False and a\n        # human-readable `error`, so the presence of `error` proves nothing. What\n        # separates the two cases is `found`: a real answer has it, and a result\n        # that call() built from a caught exception does not.\n        #\n        # This was one line - an index into ["found"] - so an empty database\n        # raised KeyError at the test and threw away the diagnosis the tool had\n        # already produced: "no such table: ros".\n        assert "found" in r, f"the tool raised instead of reporting: {r.get(\'error\')}"\n        assert r["found"] is False, r',
     'test_agent.py  report an empty database as one',
     skip_if='the tool raised instead of reporting')


# ==================== 3. a login for the public link
edit('app/ui/gradio_app.py',
     'if __name__ == "__main__":\n    build().launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)), share=os.environ.get("SHARE", "0") == "1",\n                   theme=gr.themes.Soft())',
     'if __name__ == "__main__":\n    # SHARE=1 publishes a gradio.live URL with no authentication. Anyone who has\n    # it can use every tab - including Technician Update, which WRITES to the\n    # event log - and every model call runs on this box\'s NVIDIA key. The URL is\n    # a random subdomain, not a credential.\n    #\n    # GRADIO_AUTH=user:pass puts a login in front of it. Without that variable\n    # nothing changes except the warning below, which exists because "I\'ll add\n    # auth before I share it" is a decision nobody remembers making.\n    _auth = os.environ.get("GRADIO_AUTH", "").strip()\n    _share = os.environ.get("SHARE", "0") == "1"\n    if _share and ":" not in _auth:\n        print("[ui] SHARE=1 with no GRADIO_AUTH: the public link is open to "\n              "anyone who has it, and the update tab writes to the event log. "\n              "Set GRADIO_AUTH=user:pass to require a login.")\n    build().launch(server_name="0.0.0.0",\n                   server_port=int(os.environ.get("PORT", 7860)),\n                   share=_share,\n                   auth=tuple(_auth.split(":", 1)) if ":" in _auth else None,\n                   theme=gr.themes.Soft())',
     'gradio_app.py  GRADIO_AUTH gates the share link',
     skip_if='GRADIO_AUTH')


# ==================== verify
print("Quality pass 26:")
for c in CHANGES:
    print(c)
for f in ("tests/conftest.py", "tests/test_agent.py", "app/ui/gradio_app.py"):
    ast.parse((ROOT / f).read_text())
print("\nconftest.py, test_agent.py and gradio_app.py parse cleanly.")

import os, subprocess, sqlite3, tempfile, shutil
bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}" + (f"  ({detail})" if detail else ""))


PY = sys.executable

# ---- the suite must pass with the project's database absent
print("\nthe suite, with no project database:")
live = ROOT / "data/generated/service.sqlite"
backup = None
if live.exists() and live.stat().st_size > 0:
    backup = str(live) + ".pass26-backup"
    shutil.move(str(live), backup)
    print(f"  note    moved your database aside for the check ({backup})")
try:
    before = sorted(p.name for p in (ROOT / "data/generated").glob("*")) \
        if (ROOT / "data/generated").is_dir() else []
    r = subprocess.run([PY, "-m", "pytest", "tests/", "-q"],
                       capture_output=True, text=True, timeout=600)
    tail = (r.stdout or r.stderr).strip().splitlines()[-1:] or [""]
    chk("81 tests pass without a project database", r.returncode == 0, tail[0])
    after = sorted(p.name for p in (ROOT / "data/generated").glob("*")) \
        if (ROOT / "data/generated").is_dir() else []
    chk("the run writes nothing into the project", before == after,
        f"{before} -> {after}")
finally:
    if backup:
        shutil.move(backup, str(live))
        print("  note    your database has been put back")

# ---- and with it present
print("\nthe suite, with the project database present:")
r = subprocess.run([PY, "-m", "pytest", "tests/", "-q"],
                   capture_output=True, text=True, timeout=600)
chk("still passes", r.returncode == 0,
    ((r.stdout or r.stderr).strip().splitlines() or [""])[-1])

# ---- ASOIA_TEST_DB=keep uses the project's own
env = dict(os.environ, ASOIA_TEST_DB="keep")
r = subprocess.run([PY, "-c",
                    "import sys; sys.path.insert(0, 'tests'); import conftest, os;"
                    " print(os.environ.get('ASOIA_DB', 'UNSET'))"],
                   capture_output=True, text=True, env=env, timeout=120)
chk("ASOIA_TEST_DB=keep leaves ASOIA_DB alone",
    "UNSET" in r.stdout or "asoia-tests-" not in r.stdout, r.stdout.strip()[:60])

# ---- the conftest must not reintroduce the closed-connection bug
c = (ROOT / "tests/conftest.py").read_text()
chk("the conftest goes through ensure_dataset, not build_dataset",
    "ensure_dataset" in c and "build_dataset" not in c.split('"""')[-1])

# ---- the test reports rather than KeyErrors
t = (ROOT / "tests/test_agent.py").read_text()
chk("an empty database would now be reported, not KeyError'd",
    "the tool raised instead of reporting" in t)

# ---- the share link can be gated
g = (ROOT / "app/ui/gradio_app.py").read_text()
for name, ok in [("GRADIO_AUTH reaches launch()", "auth=tuple(" in g),
                 ("an ungated share warns", "[ui] SHARE=1 with no GRADIO_AUTH" in g),
                 ("PORT still honoured", 'os.environ.get("PORT", 7860)' in g),
                 ("SHARE still honoured", '"SHARE", "0"' in g),
                 ("still binds 0.0.0.0", 'server_name="0.0.0.0"' in g)]:
    chk(name, ok)

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
    .venv/bin/python -m pytest tests/ -q        81, on its own database now

A public link, with a login:

    SHARE=1 GRADIO_AUTH=demo:pick-a-password .venv/bin/python -m app.ui.gradio_app
""")
sys.exit(1 if bad else 0)
