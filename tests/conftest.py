"""Give the test suite its own database, so it never depends on the project's.

WHAT THIS FIXES

Eighty of the eighty-one tests use fixtures. One called a tool against whatever
was in `data/generated/service.sqlite`, so the suite quietly depended on somebody
having generated a dataset first. On a fresh checkout - or after re-extracting
the release archive, whose `service.sqlite` is a deliberate 0-byte placeholder -
that one test failed like this:

    assert call("get_ro_state", ro_number="RO-99-99999")["found"] is False
    E   KeyError: 'found'

The tool had done exactly the right thing. `call()` caught the exception and
returned `{"error": "get_ro_state failed: OperationalError: no such table: ros"}`,
which says precisely what is wrong. Indexing `["found"]` threw that away and
replaced it with a KeyError pointing at the error handling instead of at the
empty database. Twenty minutes went into a five-second problem.

Pass 25 made the UI and the API generate a dataset when there is none. pytest was
the one entry point left that could still meet an empty one.

WHY A SEPARATE DATABASE

Running the tests should not write 4.5 MB into the project, and the result should
not depend on what happens to be in the project's database today. Forty repair
orders over seven days takes about 0.04 s and gives every tool a real schema with
real rows.

The environment variable has to be set before any test module imports
`app.state.db`, because that module reads ASOIA_DB once at import and caches a
connection per thread. That is why this is module-level code in conftest rather
than a fixture.

WHY IT GOES THROUGH ensure_dataset AND NOT build_dataset

The first version of this file called `build_dataset` directly and every tool
call then failed with:

    ProgrammingError: Cannot operate on a closed database.

`build_dataset` closes the connection it used, and `dbm.connect()` caches one per
thread, so the cache is left holding a closed connection. That is exactly the bug
`app/state/bootstrap.py` was written to handle in pass 25 - and calling the lower
level function walked straight back into it. Going through `ensure_dataset` gets
the eviction, the read-back check and the empty-database reporting for free, and
means the tests exercise the same bootstrap the app uses.

ASOIA_TEST_DB=keep runs against the project's own database instead, for when you
deliberately want to test against the data you are about to demo.
"""
from __future__ import annotations
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if os.environ.get("ASOIA_TEST_DB", "").lower() != "keep":
    os.environ["ASOIA_DB"] = os.path.join(
        tempfile.mkdtemp(prefix="asoia-tests-"), "service.sqlite")
    os.environ.setdefault("ASOIA_GEN_ROS", "40")
    os.environ.setdefault("ASOIA_GEN_DAYS", "7")
    # Imported only after ASOIA_DB is set: app.state.db reads it at import.
    from app.state.bootstrap import ensure_dataset

    _r = ensure_dataset(verbose=False)
    if _r.get("status") not in ("generated", "present"):
        raise RuntimeError(
            f"the test database could not be prepared: {_r}. "
            f"Run the suite with ASOIA_TEST_DB=keep to use the project's own.")
