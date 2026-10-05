#!/usr/bin/env python
"""Pass 43 - the store UIs' dependency was installed but never declared.

Pass 42 provisioned sqlite-web by running pip against the venv. That works on
this box and is invisible on a fresh one: `pip install -e '.[nvidia,flywheel]'`
reproduces the whole stack except the two admin UIs, and the first symptom is
`scripts/stack.sh stores up` quietly reporting the UI as not installed.

So sqlite-web is now declared, as its own extra:

    admin = ["sqlite-web>=0.8"]

It is an extra and not a base dependency for the same reason `up` does not
download: nothing the agent does needs it, and a box that never opens the admin
UIs should not carry a Flask app and peewee.

Attu has no pip half - it is a container image, pinned in scripts/stores.sh to
Milvus's minor version - so the extra covers only half of `stores provision`.
That asymmetry is in the comment, because an extra named `admin` that installs
one of two UIs is otherwise a trap.

WHY provision STILL INSTALLS BY NAME

The obvious follow-through is to have `stores_provision` install `.[admin]` so
the constraint lives in exactly one place. It does not, deliberately: this
project is installed editable, and `pip install -e '.[admin]'` re-resolves every
base dependency on a box that is currently serving a demo. Trading a working
stack for tidiness is a bad trade.

The cost is that `>=0.8` now appears twice, so this pass adds the check that
keeps them honest: every requirement in the `admin` extra must appear verbatim
in the command that installs it. Parsed with tomllib, not grepped - pass 38
failed a substring assertion against its own explanatory comment, and this file
has more prose than code.

Idempotent. Re-running changes nothing and says so.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # python < 3.11
    # The extras must be PARSED, not grepped - pass 38 failed a substring
    # assertion against its own comment - and this box's system python3 is
    # 3.10, which has no tomllib. The project venv is 3.11, so re-exec there
    # rather than failing in front of whoever typed the obvious command.
    _VENV = Path(__file__).resolve().parent.parent / ".venv/bin/python"
    if _VENV.exists() and os.environ.get("_P43_REEXEC") != "1":
        os.environ["_P43_REEXEC"] = "1"
        os.execv(str(_VENV), [str(_VENV), str(Path(__file__).resolve()),
                              *sys.argv[1:]])
    raise SystemExit(
        "pass 43 needs python >= 3.11 for tomllib, and no usable .venv was "
        "found next to it. Run it as: .venv/bin/python patches/quality_pass43.py")

ROOT = Path(__file__).resolve().parent
if not (ROOT / "scripts").is_dir():
    ROOT = ROOT.parent

EXTRA = "admin"
REQS = ["sqlite-web>=0.8"]


def note(s: str) -> None:
    print("  " + s)


def edit_pyproject() -> None:
    rel = "pyproject.toml"
    p = ROOT / rel
    txt = p.read_text()
    if re.search(r"^admin\s*=", txt, re.M):
        note(f"{rel}: the admin extra is already declared, skipped")
        return
    anchor = 'voice = ["nvidia-riva-client>=2.16"]'
    if txt.count(anchor) != 1:
        raise RuntimeError(
            f"pass 43 refused: expected exactly 1 '{anchor}' in {rel}, "
            f"found {txt.count(anchor)}. Extras present: "
            + ", ".join(sorted(tomllib.loads(txt)
                               .get("project", {})
                               .get("optional-dependencies", {}))))
    block = (
        "\n# The store admin UIs (scripts/stores.sh). sqlite-web is the only pip\n"
        "# half of `stores provision`: Attu is a container image, pinned there to\n"
        "# Milvus's minor version. Separate from everything else because nothing\n"
        "# the agent does needs it - `up` starts a UI only if it is already\n"
        "# installed - and a box that never opens the UIs should not carry a\n"
        "# Flask app and peewee.\n"
        f'{EXTRA} = [{", ".join(chr(34) + r + chr(34) for r in REQS)}]'
    )
    i = txt.index(anchor) + len(anchor)
    p.write_text(txt[:i] + block + txt[i:])
    note(f"{rel}: {EXTRA} extra declared")


def edit_stores() -> None:
    rel = "scripts/stores.sh"
    p = ROOT / rel
    txt = p.read_text()
    orig = txt
    pairs = [
        ('uv pip install sqlite-web', 'uv pip install "sqlite-web>=0.8"'),
        ('.venv/bin/pip install sqlite-web',
         '.venv/bin/pip install "sqlite-web>=0.8"'),
        ('echo "  no uv and no .venv/bin/pip - install sqlite-web yourself"',
         'echo "  no uv and no .venv/bin/pip - install it yourself:"\n'
         '    echo "    pip install -e \\".[admin]\\""'),
    ]
    done = 0
    for a, b in pairs:
        if b.split("\n")[0] in txt and a not in txt:
            continue
        if txt.count(a) != 1:
            raise RuntimeError(
                f"pass 43 refused: expected exactly 1 occurrence of {a!r} in "
                f"{rel}, found {txt.count(a)}")
        txt = txt.replace(a, b)
        done += 1
    if txt == orig:
        note(f"{rel}: already carries the constraint, skipped")
        return
    p.write_text(txt)
    note(f"{rel}: {done} install line(s) now carry the declared constraint")


def readme_row() -> None:
    rel = "patches/README.md"
    p = ROOT / rel
    txt = p.read_text()
    if "quality_pass43.py" in txt:
        note(f"{rel}: row already present, skipped")
        return
    m = re.search(r"^\| `quality_pass42\.py`.*$", txt, re.M)
    if not m:
        note(f"{rel}: no row 42 to insert after, skipped")
        return
    row = ("| `quality_pass43.py` | pass 42 installed sqlite-web without "
           "declaring it, so a fresh box reproduced the stack minus both store "
           "UIs; declared as an `admin` extra, with a check that the constraint "
           "and the command that installs it cannot drift apart |")
    p.write_text(txt[:m.end()] + "\n" + row + txt[m.end():])
    note(f"{rel}: row added after quality_pass42.py")


def checks() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, detail: str = "") -> None:
        out.append((name, bool(ok), detail))

    try:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        ck("pyproject.toml is valid TOML", True)
    except Exception as e:
        ck("pyproject.toml is valid TOML", False, str(e))
        return out

    extras = data.get("project", {}).get("optional-dependencies", {})
    ck(f"{EXTRA} extra declared", EXTRA in extras,
       "extras: " + ", ".join(sorted(extras)))
    ck(f"{EXTRA} extra holds exactly {REQS}", extras.get(EXTRA) == REQS,
       repr(extras.get(EXTRA)))
    # The extras that already existed must still be there: an edit to this file
    # that drops `nvidia` or `flywheel` breaks a fresh install silently.
    for e in ("dev", "nvidia", "flywheel", "voice"):
        ck(f"{e} extra still present", e in extras)

    shb = (ROOT / "scripts/stores.sh").read_text()
    # The drift guard this pass exists to add.
    for r in extras.get(EXTRA, []):
        ck(f"stores.sh installs {r!r} verbatim", r in shb,
           "constraint in pyproject does not match the install command")

    r = subprocess.run(["bash", "-n", str(ROOT / "scripts/stores.sh")],
                       capture_output=True, text=True)
    ck("stores.sh parses", r.returncode == 0, r.stderr.strip()[:160])

    # What is actually installed must satisfy what is declared, or the
    # declaration is fiction.
    py = ROOT / ".venv/bin/python"
    if py.exists():
        r = subprocess.run(
            [str(py), "-c",
             "import importlib.metadata as m; print(m.version('sqlite-web'))"],
            capture_output=True, text=True)
        got = r.stdout.strip()
        # Read the constraint from the FILE, not from REQS. Using the pass's own
        # constant made this check report ok against a pyproject that had
        # drifted to >=9.9 - sound only because the check above catches that,
        # and a check should test what its label says it tests.
        declared = (extras.get(EXTRA) or REQS)[0]
        want = declared.split(">=")[1]
        def tup(v: str) -> tuple:
            return tuple(int(x) for x in re.findall(r"\d+", v))
        ck(f"installed sqlite-web satisfies {declared}",
           bool(got) and tup(got) >= tup(want),
           f"installed {got or 'nothing'}")

    txt = (ROOT / "patches/README.md").read_text()
    rows = re.findall(r"^\| `([^`]+\.py)`", txt, re.M)
    files = sorted(x.name for x in (ROOT / "patches").glob("quality_pass*.py"))
    ck("README has a row 43", "quality_pass43.py" in rows)
    ck("README rows match script files", sorted(rows) == files,
       f"{len(rows)} rows vs {len(files)} files")
    return out


def main() -> int:
    print("pass 43: declare the store UIs' dependency\n")
    edit_pyproject()
    edit_stores()
    readme_row()
    print("\nchecks")
    bad = 0
    for name, ok, detail in checks():
        print(f"  [{'ok' if ok else 'FAIL'}] {name}"
              + (f"  -- {detail}" if detail and not ok else ""))
        bad += 0 if ok else 1
    print()
    if bad:
        print(f"{bad} check(s) failed")
        return 1
    print("all checks passed")
    print("\na fresh box now gets the UIs with:")
    print("  pip install -e \".[nvidia,flywheel,admin]\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
