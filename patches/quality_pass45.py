#!/usr/bin/env python
"""Pass 45 - observability that nobody starts, on ports anybody can reach.

Two defects, both found by running the thing rather than reading it.

`scripts/start_observability.sh` has existed for many passes and `stack.sh`
never mentioned it, so Prometheus and Grafana had never once been created on
this box - `docker ps -a` had no record of either. The metrics exporter was
working the whole time on :9400; what was missing was anything scraping it. So
the shadow-rail counters, which are the evidence the guardrail promotion
decision waits on, were in-process only and died with every restart.

And when started, both bound every interface: Prometheus on `*:9090`, Grafana
on `*:3000` with `GF_AUTH_ANONYMOUS_ORG_ROLE=Admin` and the login form
disabled. An anonymous-admin dashboard on all interfaces is a worse exposure
than the store UIs pass 42 was careful to bind to loopback, and the script's own
closing advice already assumed a port-forward ("Do not publish 3000") - it just
never enforced it.

This binds both to 127.0.0.1 and starts them with the stack.

Idempotent. Re-running changes nothing and says so.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if not (ROOT / "scripts").is_dir():
    ROOT = ROOT.parent


def note(s: str) -> None:
    print("  " + s)


def patch_observability() -> None:
    rel = "scripts/start_observability.sh"
    p = ROOT / rel
    txt = p.read_text()
    orig = txt

    # Prometheus: bind loopback.
    a = '--web.listen-address=":$PROM_PORT"'
    b = '--web.listen-address="127.0.0.1:$PROM_PORT"'
    if a in txt:
        if txt.count(a) != 1:
            raise RuntimeError(f"pass 45 refused: {txt.count(a)} prometheus bind lines")
        txt = txt.replace(a, b)

    # Grafana: bind loopback. GF_SERVER_HTTP_ADDR is the knob; the port alone
    # leaves it on 0.0.0.0.
    a2 = '-e GF_SERVER_HTTP_PORT="$GRAF_PORT" \\'
    b2 = ('-e GF_SERVER_HTTP_PORT="$GRAF_PORT" -e GF_SERVER_HTTP_ADDR=127.0.0.1 \\')
    if a2 in txt:
        if txt.count(a2) != 1:
            raise RuntimeError(f"pass 45 refused: {txt.count(a2)} grafana port lines")
        txt = txt.replace(a2, b2)

    # A named volume. The image declares VOLUME /prometheus, so docker was
    # handing each container a fresh ANONYMOUS volume: recreating the container
    # orphaned the old TSDB and started with no history. Retention across
    # restarts is the entire reason this pass exists, so name it.
    a3 = '-v "$ROOT/configs/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \\'
    b3 = (a3 + "\n      -v asoia-prom-data:/prometheus \\")
    if "asoia-prom-data" not in txt:
        if txt.count(a3) != 1:
            raise RuntimeError(
                f"pass 45 refused: {txt.count(a3)} prometheus config mounts")
        txt = txt.replace(a3, b3)

    # Say why, next to the thing it explains.
    anchor = "PROM_PORT=\"${PROM_PORT:-9090}\""
    if anchor in txt and "anonymous admin" not in txt:
        why = (
            "# Both bind 127.0.0.1, not every interface. Grafana runs with\n"
            "# anonymous admin and no login form - deliberately, because it is meant\n"
            "# to be reached over an ssh port-forward - and an anonymous admin\n"
            "# dashboard listening on 0.0.0.0 is exactly the exposure the store UIs\n"
            "# in scripts/stores.sh are bound away from. Reach these the same way:\n"
            "#   ssh -N -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 capstone-poc\n"
        )
        txt = txt.replace(anchor, why + anchor, 1)

    if txt == orig:
        note(f"{rel}: already loopback-bound, skipped")
    else:
        p.write_text(txt)
        note(f"{rel}: prometheus + grafana bound to 127.0.0.1")


def wire_stack() -> None:
    rel = "scripts/stack.sh"
    p = ROOT / rel
    txt = p.read_text()
    if "start_observability.sh" in txt:
        note(f"{rel}: already starts observability, skipped")
        return
    orig = txt

    for verb, call in (
        ("up", 'bash scripts/start_observability.sh up >/dev/null 2>&1 && '
               'echo "  ==  observability: prometheus :9090, grafana :3000 (loopback)"'),
        ("down", 'bash scripts/start_observability.sh down >/dev/null 2>&1'),
    ):
        pat = r"^([ \t]*)" + verb + r"\)"
        m = list(re.finditer(pat, txt, re.M))
        if len(m) != 1:
            raise RuntimeError(
                f"pass 45 refused: expected 1 '{verb})' arm, found {len(m)}")
        end = txt.find(";;", m[0].end())
        if end < 0:
            raise RuntimeError(f"pass 45 refused: no ';;' after '{verb})'")
        body = txt[m[0].end():end]
        if "\n" in body:
            raise RuntimeError(
                f"pass 45 refused: the '{verb})' arm is no longer a one-liner; "
                "re-check where the call belongs")
        sep = "" if body.rstrip().endswith(";") else "; "
        txt = txt[:end] + sep + call + " " + txt[end:]

    assert txt != orig
    p.write_text(txt)
    note(f"{rel}: observability starts with `up`, stops with `down`")


def readme_row() -> None:
    rel = "patches/README.md"
    p = ROOT / rel
    txt = p.read_text()
    if "quality_pass45.py" in txt:
        note(f"{rel}: row already present, skipped")
        return
    m = re.search(r"^\| `quality_pass44\.py`.*$", txt, re.M)
    if not m:
        note(f"{rel}: no row 44 to insert after, skipped")
        return
    row = ("| `quality_pass45.py` | Prometheus and Grafana had never been created "
           "on this box - stack.sh never mentioned the script that starts them, so "
           "the shadow-rail counters were in-process only and died on every "
           "restart; and when started they bound every interface, Grafana with "
           "anonymous admin |")
    p.write_text(txt[:m.end()] + "\n" + row + txt[m.end():])
    note(f"{rel}: row added after quality_pass44.py")


def checks() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    def ck(n: str, ok: bool, d: str = "") -> None:
        out.append((n, bool(ok), d))

    obs = ROOT / "scripts/start_observability.sh"
    body = obs.read_text()
    r = subprocess.run(["bash", "-n", str(obs)], capture_output=True, text=True)
    ck("start_observability.sh parses", r.returncode == 0, r.stderr.strip()[:140])
    ck("prometheus binds loopback", '--web.listen-address="127.0.0.1:' in body)
    ck("grafana binds loopback", "GF_SERVER_HTTP_ADDR=127.0.0.1" in body)
    # Bind positions, not a word search: the file legitimately discusses ports.
    binds = re.findall(r'(?:--web\.listen-address=|GF_SERVER_HTTP_ADDR=)"?([0-9.]+)', body)
    ck("every bind position is loopback",
       bool(binds) and all(b == "127.0.0.1" for b in binds), f"found {binds}")
    ck("prometheus keeps a named volume", "asoia-prom-data:/prometheus" in body,
       "an anonymous volume is discarded when the container is recreated")

    st = ROOT / "scripts/stack.sh"
    t = st.read_text()
    ck("stack.sh starts observability", "start_observability.sh up" in t)
    ck("stack.sh stops observability", "start_observability.sh down" in t)
    r = subprocess.run(["bash", "-n", str(st)], capture_output=True, text=True)
    ck("stack.sh still parses", r.returncode == 0, r.stderr.strip()[:200])
    # Pass 42's wiring must survive this one.
    ck("pass 42 store wiring intact",
       "stores_admin_up" in t and "stores_report" in t and "stores_main" in t)

    txt = (ROOT / "patches/README.md").read_text()
    rows = re.findall(r"^\| `([^`]+\.py)`", txt, re.M)
    files = sorted(x.name for x in (ROOT / "patches").glob("quality_pass*.py"))
    ck("README has a row 45", "quality_pass45.py" in rows)
    ck("README rows match script files", sorted(rows) == files,
       f"{len(rows)} rows vs {len(files)} files")
    return out


def main() -> int:
    print("pass 45: start observability with the stack, on loopback\n")
    patch_observability()
    wire_stack()
    readme_row()
    print("\nchecks")
    bad = 0
    for n, ok, d in checks():
        print(f"  [{'ok' if ok else 'FAIL'}] {n}" + (f"  -- {d}" if d and not ok else ""))
        bad += 0 if ok else 1
    print()
    if bad:
        print(f"{bad} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
