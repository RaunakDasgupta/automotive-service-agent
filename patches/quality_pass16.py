#!/usr/bin/env python3
"""Sixteenth pass: the deployment fixes, which until now existed only by hand.

Run from the project root:   python3 quality_pass16.py

Four defects in scripts/start_nims.sh stopped the stack dead on a fresh L40S, and
they were fixed interactively on the instance with sed. That means they live in one
shell history and on one disk: clone this repository and the NIMs will not come up.
This pass puts them in the code, where they belong.

1. THE RERANKER IMAGE TAG DOES NOT EXIST. `nv-rerankqa-mistral-4b-v3:latest`
   fails with `manifest unknown` - that repository publishes only versioned tags.
   NVIDIA's own deployment docs pin 1.0.0; 1.0.2 is current. The LLM and embedding
   repositories DO publish `latest`, which is why exactly one of three pulls
   failed and the cause was not obvious.

2. THE MODEL CACHE IS NOT WRITABLE BY THE CONTAINER. The script creates
   $HOME/.cache/nim owned by the host user at mode 755, but a NIM container runs
   internally as a different uid, so it lands on "other" permissions and dies with
   `PermissionError: /opt/nim/.cache/local_cache`. Fixed by running as the invoking
   user, as NVIDIA's quickstart does, and making the cache group/other writable.

3. EVERY CONTAINER FIGHTS ITSELF OVER A PORT. The script picked host ports
   8000/8001/8002 and forced each container's INTERNAL http port to match with
   NIM_HTTP_API_PORT. But a NIM already uses the standard Triton triple
   internally - 8000 http, 8001 grpc, 8002 metrics - so the embedding container's
   http server took 8001 and Triton's own grpc service could not bind it:
   `failed to start GRPC service: Socket '0.0.0.0:8001' already in use`. The LLM
   survived only because 8000 is the default. Containers have separate network
   namespaces, so all three can use 8000 internally and be mapped to distinct
   host ports.

4. NVIDIA_API_KEY WAS REQUIRED BY SUBCOMMANDS THAT DO NOT NEED IT. The guard
   runs before the dispatch, so `logs`, `stop` and `health` all failed in a fresh
   shell with `line 12: NVIDIA_API_KEY: parameter null or not set`. The script now
   sources .env itself.

And two more found while writing this up:

5. THE VRAM CAP APPLIES TO THE WRONG BACKEND. `NIM_GPU_MEMORY_UTILIZATION` is a
   vLLM setting, and the container selected a TRT-LLM FP8 profile on the L40S, for
   which the equivalent is `NIM_KVCACHE_PERCENT`. The cap that the comment block
   carefully explains was therefore silently doing nothing. Both are now set; each
   backend ignores the one that is not its own.

6. `_post` RETRIED AN HTTP 400 FOUR TIMES AND THREW AWAY THE BODY. A 400 is a
   malformed request - retrying cannot fix it, and the response body is the only
   thing that says what was wrong. A payload bug cost four round trips and
   surfaced as a bare status code.
"""
import sys, pathlib, ast, re

ROOT = pathlib.Path(".")
CHANGES = []


def edit(rel, old, new, label, skip_if=None, skip_if_re=None):
    """Apply one edit. `skip_if_re` exists because these fixes were first made by
    hand in a shell, where `-u $(id -u)` and `-u "$(id -u)"` are equally likely -
    a literal skip test misses one of them and reports a change that never
    happened."""
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"FAIL: {rel} not found - run from the project root")
    s = p.read_text()
    if skip_if_re and re.search(skip_if_re, s):
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    if skip_if and skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    n = s.count(old)
    if n != 1:
        sys.exit(f"FAIL: {label}: anchor found {n} times in {rel}, expected 1.\n"
                 "      Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


# ============================================== 1. source .env, then need the key
edit("scripts/start_nims.sh",
     '''set -uo pipefail

: "${NVIDIA_API_KEY:?Set NVIDIA_API_KEY (see .env). Never commit it.}"''',
     '''set -uo pipefail

# Source .env first. Without this, `logs`, `stop` and `health` all died on the
# guard below in any shell that had not exported the key by hand - subcommands
# that never touch the network.
[ -f .env ] && { set -a; . ./.env; set +a; }

: "${NVIDIA_API_KEY:?Set NVIDIA_API_KEY (see .env). Never commit it.}"''',
     "start_nims.sh  source .env before requiring the key",
     skip_if="set -a; . ./.env; set +a")


# ============================================== 2. a tag that exists
edit("scripts/start_nims.sh",
     '''RRK_IMG="nvcr.io/nim/nvidia/nv-rerankqa-mistral-4b-v3:latest"''',
     '''# NOT :latest - that repository publishes only versioned tags and `docker pull`
# fails with `manifest unknown`. NVIDIA's deployment docs pin 1.0.0; 1.0.2 is
# current. The llm and embedding repositories do publish :latest, which is why
# only one of the three pulls failed.
RRK_IMG="nvcr.io/nim/nvidia/nv-rerankqa-mistral-4b-v3:1.0.2"''',
     "start_nims.sh  pin the reranker to a tag that exists",
     skip_if="nv-rerankqa-mistral-4b-v3:1.0.2")


# ============================================== 3. writable cache
edit("scripts/start_nims.sh",
     '''mkdir -p "$CACHE"''',
     '''mkdir -p "$CACHE"
# A NIM container runs internally as a different uid to the host user, so a cache
# directory at the default 755 leaves it on "other" permissions and it dies with
# `PermissionError: /opt/nim/.cache/local_cache`. Containers are also run as the
# invoking user below, as NVIDIA's quickstart does.
chmod -R a+rwX "$CACHE" 2>/dev/null || true''',
     "start_nims.sh  make the model cache writable",
     skip_if="chmod -R a+rwX")


# ============================================== 4. stop the port collision
# Two separate edits. They were one, with a skip test that only checked the port
# mapping - so a tree already fixed by hand for the port collision skipped the
# whole thing and silently never got `-u`. A skip test has to cover everything
# its edit does, or it reports success for half a change.
edit("scripts/start_nims.sh",
     '''  docker run -d --name "$name" --gpus all --shm-size=16GB --restart unless-stopped \\
''',
     '''  # The container must write to the mounted cache as the host user: a NIM runs
  # internally as a different uid, so without this it cannot create
  # /opt/nim/.cache/local_cache. NVIDIA's quickstart does the same.
  docker run -d --name "$name" --gpus all --shm-size=16GB --restart unless-stopped \\
    -u "$(id -u):$(id -g)" \\
''',
     "start_nims.sh  run containers as the invoking user",
     skip_if_re=r'-u\s+"?\$\(id -u\)')

edit("scripts/start_nims.sh",
     '''    -e NGC_API_KEY="$NGC_API_KEY" -e NIM_HTTP_API_PORT="$port" \\
    "$@" -v "$CACHE:/opt/nim/.cache" -p "$port:$port" "$image" >/dev/null''',
     '''    -e NGC_API_KEY="$NGC_API_KEY" \\
    "$@" -v "$CACHE:/opt/nim/.cache" -p "$port:8000" "$image" >/dev/null
  # Leave the container's INTERNAL ports alone. A NIM uses the standard Triton
  # triple - 8000 http, 8001 grpc, 8002 metrics - so forcing its http server onto
  # 8001 made Triton's own grpc service fail to bind: `Socket '0.0.0.0:8001'
  # already in use`. Separate network namespaces mean all three containers can
  # use 8000 internally.''',
     "start_nims.sh  stop forcing the internal http port",
     skip_if='-p "$port:8000"')


# ============================================== 5. cap the right backend
edit("scripts/start_nims.sh",
     '''  run_one nim-llm    "$LLM_IMG" $LLM_PORT \\
      -e NIM_GPU_MEMORY_UTILIZATION="$LLM_GPU_FRAC" \\
      -e NIM_MAX_MODEL_LEN="$LLM_MAX_LEN"''',
     '''  # Both memory caps, because which one applies depends on the profile the
  # container selects: NIM_GPU_MEMORY_UTILIZATION is vLLM, NIM_KVCACHE_PERCENT is
  # TRT-LLM. On an L40S this image picks a TRT-LLM FP8 profile, so the vLLM
  # setting on its own was silently doing nothing at all. Each backend ignores
  # the variable that is not its own.
  run_one nim-llm    "$LLM_IMG" $LLM_PORT \\
      -e NIM_GPU_MEMORY_UTILIZATION="$LLM_GPU_FRAC" \\
      -e NIM_KVCACHE_PERCENT="$LLM_GPU_FRAC" \\
      -e NIM_MAX_MODEL_LEN="$LLM_MAX_LEN"''',
     "start_nims.sh  cap VRAM on whichever backend is chosen",
     skip_if="NIM_KVCACHE_PERCENT")


# ============================================== 6. do not retry a 400
edit("app/nim/client.py",
     '''        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{url} failed after {retries} attempts: {last}")''',
     '''        except httpx.HTTPStatusError as e:
            # The body is the only thing that says what was wrong with the
            # request, and it was being discarded in favour of a bare status code.
            last = RuntimeError(f"HTTP {e.response.status_code}: "
                                f"{e.response.text[:500]}")
            if e.response.status_code == 400:
                raise last          # a malformed payload: retrying cannot help
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{url} failed after {retries} attempts: {last}")''',
     "client.py  surface the body, never retry a 400",
     skip_if="a malformed payload: retrying cannot help")


# ============================================== verify
print("Quality pass 16:")
for c in CHANGES:
    print(c)
ast.parse((ROOT / "app/nim/client.py").read_text())
print("\nclient.py parses cleanly.")

sh = (ROOT / "scripts/start_nims.sh").read_text()
bad = 0
CHECKS = [
    (".env sourced above the key guard",
     sh.index("set -a; . ./.env") < sh.index('"${NVIDIA_API_KEY:?')),
    ("reranker pinned to a real tag", ":1.0.2" in sh and
     "nv-rerankqa-mistral-4b-v3:latest" not in sh.replace("# ", "")),
    # Tolerant of quoting: the hand-edited instance had it unquoted, and a
    # literal test reported a missing fix that was present all along.
    ("containers run as the invoking user",
     bool(re.search(r'-u\s+"?\$\(id -u\)', sh))),
    ("internal http port no longer forced", "-e NIM_HTTP_API_PORT" not in sh),
    ("host port maps to container 8000", '-p "$port:8000"' in sh),
    ("cache made writable", "chmod -R a+rwX" in sh),
    ("both VRAM caps set", "NIM_KVCACHE_PERCENT" in sh
     and "NIM_GPU_MEMORY_UTILIZATION" in sh),
]
print("\nstart_nims.sh:")
for name, ok in CHECKS:
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}")

import shutil
if shutil.which("bash"):
    import subprocess
    r = subprocess.run(["bash", "-n", "scripts/start_nims.sh"],
                       capture_output=True, text=True)
    ok = r.returncode == 0
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} bash -n parses the script"
          + ("" if ok else f"\n           {r.stderr.strip()}"))

cl = (ROOT / "app/nim/client.py").read_text()
print("\nclient.py:")
for name, ok in [("a 400 is raised, not retried",
                  "if e.response.status_code == 400:" in cl),
                 ("the response body is kept", "e.response.text[:500]" in cl)]:
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}")

print(f"\n{bad} check(s) unexpected" if bad
      else "\nAll pass-16 checks behaved as expected.")
print("\nThese are the fixes that were previously only on the instance. A clone of "
      "this repository can now bring the stack up:")
print("  bash scripts/start_nims.sh pull && bash scripts/start_nims.sh run")
