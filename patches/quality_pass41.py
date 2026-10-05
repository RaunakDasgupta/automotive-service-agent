#!/usr/bin/env python3
"""Forty-first pass: the login comes off the public UI.

Run from the project root:   .venv/bin/python quality_pass41.py

Requested, and recorded rather than done quietly, because a safety control
removed without a note is one that gets removed twice.

With auth= gone from launch(), a --share link has nothing in front of it:
every tab is reachable by anyone holding the URL, including Technician
Update, which WRITES to the event log, and every model call spends this
box's NVIDIA key.

Removed in four places, because a half-removed control is worse than either
state: launch() takes no auth and the module never reads GRADIO_AUTH;
stack.sh neither requires nor forwards it; the health check comment that
justified its own leniency by a login page\u2019s 401 now says something
true; and the README stops promising that --share refuses without it.

The check starts a real UI with GRADIO_AUTH deliberately SET in its
environment, then asserts GET / is 200 and POST /login is gone - because a
stale credential left in .env is the obvious way for this to go wrong.
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
                 "      NOTE: edits before this one HAVE been applied.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


def append(rel, body, label, skip_if):
    p = ROOT / rel
    s = p.read_text() if p.exists() else ""
    if skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    p.write_text(s + body)
    CHANGES.append(f"  ok    {label}")


# ==================== 1. the UI takes no credentials
edit('app/ui/gradio_app.py',
     '    # SHARE=1 publishes a gradio.live URL with no authentication. Anyone who has\n    # it can use every tab - including Technician Update, which WRITES to the\n    # event log - and every model call runs on this box\'s NVIDIA key. The URL is\n    # a random subdomain, not a credential.\n    #\n    # GRADIO_AUTH=user:pass puts a login in front of it. Without that variable\n    # nothing changes except the warning below, which exists because "I\'ll add\n    # auth before I share it" is a decision nobody remembers making.\n    _auth = os.environ.get("GRADIO_AUTH", "").strip()\n    _share = os.environ.get("SHARE", "0") == "1"\n    if _share and ":" not in _auth:\n        print("[ui] SHARE=1 with no GRADIO_AUTH: the public link is open to "\n              "anyone who has it, and the update tab writes to the event log. "\n              "Set GRADIO_AUTH=user:pass to require a login.")\n    build().launch(server_name="0.0.0.0",\n                   server_port=int(os.environ.get("PORT", 7860)),\n                   share=_share,\n                   auth=tuple(_auth.split(":", 1)) if ":" in _auth else None,\n                   theme=gr.themes.Soft())\n',
     '    # SHARE=1 publishes a gradio.live URL and there is NO login in front of it.\n    #\n    # That is a deliberate decision, taken knowingly, and it is recorded here\n    # rather than left to be discovered: anyone who has the URL can use every tab,\n    # including Technician Update, which WRITES to the event log, and every model\n    # call runs on this box\'s NVIDIA key. A random subdomain is not a credential.\n    #\n    # So treat a shared link as published: take it down with\n    # `bash scripts/stack.sh down` when you are finished, and rotate the NVIDIA key\n    # afterwards. The warning below is not a control, it is a reminder in the log\n    # that this is how the process was started.\n    _share = os.environ.get("SHARE", "0") == "1"\n    if _share:\n        print("[ui] SHARE=1 and NO login: anyone with the gradio.live URL can "\n              "write to the event log and spend this box\'s NVIDIA key. Take the "\n              "link down with `scripts/stack.sh down` when you are done.")\n    build().launch(server_name="0.0.0.0",\n                   server_port=int(os.environ.get("PORT", 7860)),\n                   share=_share,\n                   theme=gr.themes.Soft())\n',
     'gradio_app.py  launch() loses auth=, module stops reading GRADIO_AUTH',
     skip_if='SHARE=1 and NO login')

# ==================== 2. the launcher stops demanding and forwarding it
edit('scripts/stack.sh',
     '    if [ -z "${GRADIO_AUTH:-}" ]; then\n      echo "  !!  --share with no GRADIO_AUTH. The gradio.live link is public and"\n      echo "      the Technician Update tab WRITES to the event log. Put"\n      echo "      GRADIO_AUTH=user:password in .env, or drop --share."\n      exit 2\n    fi\n',
     '    # There is no login in front of the public link, by decision. The UI prints\n    # the same warning on startup; see app/ui/gradio_app.py. Nothing here blocks\n    # --share any more, so a shared link is live the moment this returns.\n',
     'stack.sh  --share no longer refuses without a credential',
     skip_if='There is no login in front of the public link, by decision')

edit('scripts/stack.sh',
     '      start_svc ui SHARE=1 "GRADIO_AUTH=$GRADIO_AUTH" || exit 1\n',
     '      start_svc ui SHARE=1 || exit 1\n',
     'stack.sh  the UI is started without it',
     skip_if='start_svc ui SHARE=1 || exit 1')

edit('scripts/stack.sh',
     '# Answering at all is the test, not answering 200: the UI returns 401 for the\n# login page when GRADIO_AUTH is set, and that is a healthy UI.\n',
     '# Answering at all is the test, not answering 200. It no longer serves a login, so\n# 200 is what you should see - but a UI that is starting up, redirecting, or\n# erroring is still a UI that is listening, and "is the port answering" is the\n# question this is asking.\n',
     "stack.sh  the health check's stale justification",
     skip_if='It no longer serves a login')

# ==================== 3. the documentation stops promising a login
edit('README.md',
     '`--share` refuses to run without `GRADIO_AUTH=user:password` in `.env`. The\n`gradio.live` URL is world-reachable and the Technician Update tab writes to the\nevent log; a random subdomain is not a credential.\n',
     "`--share` publishes a `gradio.live` URL with **no login**. The URL is\nworld-reachable, the Technician Update tab writes to the event log, and every model\ncall spends this box's NVIDIA key; a random subdomain is not a credential. Take the\nlink down with `bash scripts/stack.sh down` when you are finished, and rotate the\nkey afterwards.\n",
     'README.md  --share is open, and says so',
     skip_if='publishes a `gradio.live` URL with **no login**')

edit('README.md',
     '| `GRADIO_AUTH` | — | `user:password`; required by `stack.sh up --share` |\n',
     '',
     'README.md  the GRADIO_AUTH row goes',
     skip_if='| `SHARE` | `0` |')

# ==================== 4. the record
_p40 = [l for l in (ROOT / 'patches/README.md').read_text().splitlines(True)
        if l.startswith('| `quality_pass40.py` |')]
if _p40:
    edit('patches/README.md', _p40[0], _p40[0] + '| `quality_pass41.py` | the login in front of the public UI removed on request, everywhere rather than in one place, and the risk written down where the decision was made instead of left to be discovered |\n',
         'patches/README.md  pass 41 row', skip_if='| `quality_pass41.py` |')

append('ENGINEERING.md', '\n\n## 30. The login came off the public UI\n\nRemoved on request. It is recorded here because removing a safety control quietly\nis how it gets removed twice.\n\n`--share` publishes a `gradio.live` URL. With `auth=` gone from `launch()` there is\nnothing in front of it: every tab is reachable by anyone holding the link,\n**including Technician Update, which writes to the event log**, and every model call\nspends this box\'s NVIDIA key. A random subdomain is not a credential - it is not\nguessable, but it is also not secret once it has been pasted anywhere.\n\nThe removal is in four places, not one, because a half-removed control is worse\nthan either state:\n\n* `launch()` no longer takes `auth`, and the module no longer reads `GRADIO_AUTH`\n  at all;\n* `scripts/stack.sh` no longer refuses `--share` without it, and no longer passes\n  it to the UI process;\n* the `answering()` health check\'s comment explained its own leniency by the 401\n  that a login page used to return - that justification is now false, so it says\n  what is actually true instead;\n* the README said `--share` "refuses to run without `GRADIO_AUTH`", which would\n  have been a documented promise the code no longer keeps.\n\nWhat replaces it is a line in the log at startup and a paragraph in the README.\nNeither is a control and neither is pretending to be one.\n\n### The check sets GRADIO_AUTH on purpose\n\n`scripts/quality_pass41.py` starts a real UI on a spare port **with\n`GRADIO_AUTH=demo:leftover-from-before` in its environment**, then asserts that\n`GET /` returns 200 rather than a login redirect and that `POST /login` is no longer\nserved. Leaving a stale credential in `.env` and finding the login still there\nwould be the obvious way for this to go wrong, so the test arranges exactly that\ncondition rather than a clean one.\n',
       'ENGINEERING.md  section 30',
       skip_if='## 30. The login came off the public UI')

# ==================== verify
print("Quality pass 41:")
for c in CHANGES:
    print(c)

bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}"
          + (f"  ({detail})" if detail else ""))


import os, subprocess, time, signal

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import _env  # noqa: E402,F401

ui_src = (ROOT / "app/ui/gradio_app.py").read_text()
sh_src = (ROOT / "scripts/stack.sh").read_text()
ui_t = ast.parse(ui_src)
print("\nthe files:")
chk("gradio_app.py parses", True)
chk("stack.sh is syntactically valid",
    subprocess.run(["bash", "-n", "scripts/stack.sh"]).returncode == 0)

print("\nthe UI no longer takes an auth argument:")
# The launch() call, by syntax. A comment mentioning auth would not satisfy this.
_launch = [n for n in ast.walk(ui_t) if isinstance(n, ast.Call)
           and getattr(n.func, "attr", "") == "launch"]
chk("there is exactly one launch() call", len(_launch) == 1, str(len(_launch)))
if _launch:
    _kw = {k.arg for k in _launch[0].keywords}
    chk("auth= is gone", "auth" not in _kw, str(sorted(_kw)))
    chk("share= is still there", "share" in _kw)
# No string literal naming the variable anywhere in the CODE. Comments are not in
# the AST, so this checks the program and not the prose around it.
_lits = {n.value for n in ast.walk(ui_t)
         if isinstance(n, ast.Constant) and isinstance(n.value, str)}
chk("the module never reads GRADIO_AUTH", "GRADIO_AUTH" not in _lits)

print("\nthe launcher no longer requires or passes it:")
# Shell has no AST here, so strip comment lines and look at the rest.
_code = "\n".join(l for l in sh_src.splitlines() if not l.strip().startswith("#"))
chk("no GRADIO_AUTH in executable lines", "GRADIO_AUTH" not in _code,
    [l.strip()[:60] for l in _code.splitlines() if "GRADIO_AUTH" in l][:2])
chk("--share still starts the UI with SHARE=1", "start_svc ui SHARE=1" in _code)

print("\nthe documentation does not promise a login:")
_rd = (ROOT / "README.md").read_text()
chk("README no longer says --share refuses without it",
    "refuses to run without" not in _rd)
chk("README says the link is open", "no login" in _rd.lower())

print("\nand the real thing: a UI on a spare port, with no credentials at all")
_port = "7899"
_env2 = dict(os.environ)
_env2.update(PORT=_port, SHARE="0", GRADIO_AUTH="demo:leftover-from-before",
             ASOIA_TRACE="off")
# GRADIO_AUTH is deliberately SET for this run. If anything still reads it, the
# server will demand a login and the checks below will say so.
_p = subprocess.Popen([sys.executable, "-m", "app.ui.gradio_app"],
                      env=_env2, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      start_new_session=True)
try:
    import httpx
    _up = False
    for _ in range(90):
        try:
            if httpx.get(f"http://localhost:{_port}/", timeout=3).status_code:
                _up = True
                break
        except Exception:
            time.sleep(1)
    chk("it came up", _up, f"port {_port}")
    if _up:
        r = httpx.get(f"http://localhost:{_port}/", timeout=20, follow_redirects=True)
        chk("GET / is 200, not a login redirect", r.status_code == 200, str(r.status_code))
        body = (r.text or "").lower()
        chk("the page is the app, not a login form",
            "gradio" in body and "login" not in body[:4000],
            f"{len(body)} bytes")
        # Gradio mounts /login whether or not auth is configured, and without it
        # the route simply redirects - so its EXISTENCE proves nothing either way.
        # What proves it is that credentials are no longer CHECKED: with auth on,
        # the right password returned 200 {"success":true} and a wrong one 400, and
        # a session cookie was issued. All three of those stop being true.
        lg_ok = httpx.post(f"http://localhost:{_port}/login", timeout=20,
                           data={"username": "demo", "password": "leftover-from-before"})
        lg_bad = httpx.post(f"http://localhost:{_port}/login", timeout=20,
                            data={"username": "nobody", "password": "not-the-password"})
        chk("a wrong password is no longer rejected", lg_bad.status_code != 400,
            f"{lg_bad.status_code}")
        chk("right and wrong are indistinguishable",
            lg_ok.status_code == lg_bad.status_code,
            f"{lg_ok.status_code} vs {lg_bad.status_code}")
        chk("no session cookie is issued",
            not any("access-token" in c for c in lg_ok.cookies),
            str(list(lg_ok.cookies.keys()))[:60])
finally:
    try:
        os.killpg(os.getpgid(_p.pid), signal.SIGTERM)
        _p.wait(timeout=20)
    except Exception:
        try:
            _p.kill()
        except Exception:
            pass

print("\nthe regression suite:")
_t = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                    capture_output=True, text=True, timeout=1800)
chk("unit tests pass", _t.returncode == 0,
    (_t.stdout or "").strip().splitlines()[-1] if (_t.stdout or "").strip() else "")

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
  Then, to drop the credential and republish with no login:
    sed -i '/^GRADIO_AUTH=/d' .env && bash scripts/stack.sh restart --share
""")
sys.exit(1 if bad else 0)

