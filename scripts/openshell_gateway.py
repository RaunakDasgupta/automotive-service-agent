#!/usr/bin/env python
"""Point this box at a NemoClaw / OpenShell sandbox gateway.

`openshell.SandboxClient.from_active_cluster()` reads a kubectl-shaped tree,
and nothing in the Python package writes it - that is the Rust CLI's job:

    $XDG_CONFIG_HOME/openshell/active_gateway            the gateway's name
    .../openshell/gateways/<name>/metadata.json          endpoint + auth mode
    .../gateways/<name>/mtls/{ca.crt,tls.crt,tls.key}    optional, mTLS
    .../gateways/<name>/oidc_token.json                  the CLI's browser login

The Rust CLI is not installed here, and a browser OIDC login cannot be driven
from a headless GPU box in any case. So this writes the tree directly, and
prefers OAuth client credentials: it is the only mode in that list which renews
itself without a human at a browser, which is what an unattended service needs.

The secret is NOT written here and never printed. `ClientCredentialsAuth` takes
a callable, so the secret is read from the environment at call time and lives in
.env beside the NVIDIA key, rather than in a config file under ~/.config that is
one `cat` away from a screen share.

Verbs:
    write   create or replace the gateway entry (no secret touches disk)
    check   resolve it, build a client, call health(), and say exactly which of
            the four facts is missing or wrong
    show    print the entry, with any secret-shaped value redacted
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, ".")
try:
    import scripts._env as _env
    _env.load()
except Exception:
    pass

# NOT FOR A BREV LAUNCHABLE.
#
# `write` hand-registers a gateway. On a NemoClaw launchable that is the
# wrong thing to do: NemoClaw owns gateway registration and Brev
# supervises the declared gateway, and the launchable instructions say
# explicitly not to start, stop, replace or register it directly. There,
# onboard with /usr/local/bin/brev-quickstart and let it register the
# gateway; this script's `check` and `show` verbs are still the quickest
# way to see whether a client can reach it.
#
# `write` remains correct for a gateway you run yourself.
SECRET_ENV = "OPENSHELL_CLIENT_SECRET"
_REDACT = ("secret", "token", "password", "key")


def config_home() -> pathlib.Path:
    """Mirror openshell.sandbox._xdg_config_home exactly."""
    configured = os.environ.get("XDG_CONFIG_HOME")
    return pathlib.Path(configured) if configured else pathlib.Path.home() / ".config"


def gateway_dir(name: str) -> pathlib.Path:
    return config_home() / "openshell" / "gateways" / name


def active_file() -> pathlib.Path:
    return config_home() / "openshell" / "active_gateway"


def resolve_name(explicit: str | None = None) -> str | None:
    """Mirror openshell.sandbox._resolve_active_cluster, without raising."""
    if explicit:
        return explicit
    if os.environ.get("OPENSHELL_GATEWAY"):
        return os.environ["OPENSHELL_GATEWAY"]
    try:
        v = active_file().read_text(encoding="utf-8").strip()
        return v or None
    except FileNotFoundError:
        return None


def _redacted(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        out[k] = "<redacted>" if any(s in k.lower() for s in _REDACT) else v
    return out


def cmd_write(a: argparse.Namespace) -> int:
    d = gateway_dir(a.name)
    d.mkdir(parents=True, exist_ok=True)
    # 0700: the tree can hold oidc_token.json and mTLS keys. Even when this
    # script writes neither, the CLI may later, and a world-readable directory
    # is not something to leave behind for it.
    for p in (d, d.parent, d.parent.parent):
        try:
            p.chmod(0o700)
        except OSError:
            pass

    meta: dict = {"gateway_endpoint": a.endpoint, "auth_mode": a.auth_mode}
    if a.auth_mode == "oidc":
        # from_active_cluster fills omitted ClientCredentialsAuth fields from
        # these, so a missing one surfaces as an auth error at first call
        # rather than here. Write only what was given; `check` reports the gaps.
        for key, val in (("oidc_issuer", a.oidc_issuer),
                         ("oidc_client_id", a.client_id),
                         ("oidc_audience", a.audience)):
            if val:
                meta[key] = val
        if a.scopes:
            meta["oidc_scopes"] = [s for s in a.scopes.split(",") if s]

    path = d / "metadata.json"
    if path.exists() and json.loads(path.read_text()) == meta:
        print(f"  {path}: already current, unchanged")
    else:
        path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        path.chmod(0o600)
        print(f"  {path}: written")

    af = active_file()
    if not af.exists() or af.read_text(encoding="utf-8").strip() != a.name:
        af.parent.mkdir(parents=True, exist_ok=True)
        af.write_text(a.name + "\n", encoding="utf-8")
        print(f"  {af}: active gateway -> {a.name}")
    else:
        print(f"  {af}: already {a.name}")

    print("\n  NOTE: on a Brev launchable, NemoClaw owns gateway "
          "registration - use brev-quickstart there, not this verb.")
    print("\n  no secret was written. Put it in .env as:")
    print(f"    {SECRET_ENV}=<the client secret>")
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    name = resolve_name(a.name)
    if not name:
        print("  no active gateway (no OPENSHELL_GATEWAY and no active_gateway file)")
        return 1
    p = gateway_dir(name) / "metadata.json"
    print(f"  active gateway: {name}")
    print(f"  metadata      : {p}")
    try:
        print(json.dumps(_redacted(json.loads(p.read_text())), indent=2, sort_keys=True))
    except FileNotFoundError:
        print("  metadata.json is absent - run `write` first")
        return 1
    for extra in ("oidc_token.json", "mtls/ca.crt", "mtls/tls.crt", "mtls/tls.key"):
        q = gateway_dir(name) / extra
        print(f"  {extra:<18} {'present' if q.exists() else '-'}")
    print(f"  {SECRET_ENV:<18} "
          f"{'set in the environment' if os.environ.get(SECRET_ENV) else 'NOT set'}")
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    """Four facts have to line up. Report each one separately.

    A single "it does not work" is useless here: the endpoint, the auth mode,
    the IdP coordinates and the secret fail in different places and are fixed by
    different people.
    """
    rows: list[tuple[str, bool, str]] = []

    name = resolve_name(a.name)
    rows.append(("an active gateway is selected", bool(name), name or
                 "set OPENSHELL_GATEWAY or run `write`"))
    if not name:
        return _report(rows)

    meta_path = gateway_dir(name) / "metadata.json"
    try:
        meta = json.loads(meta_path.read_text())
        rows.append(("metadata.json is readable JSON", True, str(meta_path)))
    except Exception as e:
        rows.append(("metadata.json is readable JSON", False,
                     f"{type(e).__name__}: {meta_path}"))
        return _report(rows)

    ep = meta.get("gateway_endpoint", "")
    rows.append(("gateway_endpoint is present", bool(ep), ep or "missing"))
    mode = meta.get("auth_mode", "")
    rows.append(("auth_mode is present", bool(mode), mode or "missing"))

    cc = None
    if mode == "oidc":
        secret = os.environ.get(SECRET_ENV)
        rows.append((f"{SECRET_ENV} is in the environment", bool(secret),
                     "set" if secret else f"add {SECRET_ENV} to .env"))
        for k in ("oidc_issuer", "oidc_client_id"):
            rows.append((f"{k} is in metadata", bool(meta.get(k)),
                         meta.get(k) or "missing - the console shows it"))
        if secret:
            try:
                from openshell import ClientCredentialsAuth
                cc = ClientCredentialsAuth(client_secret=lambda: os.environ[SECRET_ENV])
                rows.append(("client-credentials provider builds", True, ""))
            except Exception as e:
                rows.append(("client-credentials provider builds", False,
                             f"{type(e).__name__}: {e}"))

    try:
        from openshell import SandboxClient
    except Exception as e:
        rows.append(("openshell imports", False, f"{type(e).__name__}: {e}"))
        return _report(rows)
    rows.append(("openshell imports", True, ""))

    try:
        client = SandboxClient.from_active_cluster(
            cluster=name, client_credentials=cc, timeout=float(a.timeout))
        rows.append(("client constructs from this config", True, ""))
    except Exception as e:
        rows.append(("client constructs from this config", False,
                     f"{type(e).__name__}: {e}"))
        return _report(rows)

    try:
        h = client.health()
        rows.append(("gateway answers health()", True, str(h)[:70]))
    except Exception as e:
        # The useful distinction: a config fault was caught above, so anything
        # here is the network or the gateway itself.
        rows.append(("gateway answers health()", False,
                     f"{type(e).__name__}: {str(e)[:110]}"))
    finally:
        try:
            client.close()
        except Exception:
            pass
    return _report(rows)


def _report(rows: list[tuple[str, bool, str]]) -> int:
    bad = 0
    for name, ok, detail in rows:
        print(f"  [{'ok' if ok else '--'}] {name}" + (f"  {detail}" if detail else ""))
        bad += 0 if ok else 1
    print()
    print("all four facts line up" if not bad else f"{bad} thing(s) still needed")
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("write", help="create or replace the gateway entry")
    w.add_argument("--name", required=True)
    w.add_argument("--endpoint", required=True,
                   help="e.g. https://nemoclaw-xxxx.gobrev.dev:443")
    w.add_argument("--auth-mode", default="oidc", choices=["oidc", "none"])
    w.add_argument("--oidc-issuer"), w.add_argument("--client-id")
    w.add_argument("--audience"), w.add_argument("--scopes")
    w.set_defaults(fn=cmd_write)

    c = sub.add_parser("check", help="resolve, connect, and report each fact")
    c.add_argument("--name"), c.add_argument("--timeout", default="10")
    c.set_defaults(fn=cmd_check)

    s = sub.add_parser("show", help="print the entry, secrets redacted")
    s.add_argument("--name")
    s.set_defaults(fn=cmd_show)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
