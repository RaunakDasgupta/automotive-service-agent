#!/usr/bin/env python3
"""Thirty-second pass: a fallback that changed the shape of its result, and a
record that had fallen ten passes behind.

Run from the project root:   .venv/bin/python quality_pass32.py

1. retrieval_trace() returned different keys depending on how well it went.

   There is no hosted reranking model. With NIM_MODE=hosted the second retrieval
   stage fails on every query:

       HTTP 404: 404 page not found  (nv-rerankqa-mistral-4b-v3/reranking)

   `search()` handles that correctly - it flags rerank_error and returns the
   vector order. `retrieval_trace()` did not. Three exit paths, and only the
   healthy one set `citations`, `promoted` and `dropped`, so a degraded trace
   handed back a dict its own consumers could not read and
   scripts/test_review.py --live died on

       KeyError: 'citations'

   The reranker being unavailable is a service condition. It arrived as a
   traceback in a checker two modules away. Every exit now goes through
   `_trace_out`, so a degraded result is the same SHAPE as a healthy one: the
   passages that stood carry vector_rank and moved: 0, and the difference lives
   in `rerank_applied` and `rerank_error` rather than in which keys exist.

   The test asserts that shape explicitly - it cannot KeyError again - and
   reports a missing reranker as a note rather than a failure.

   The reranker itself is one variable: NIM_MODE_RERANK=local routes only that
   service to the container from scripts/start_nims.sh and leaves the hosted
   embedder, and the 2048-dimensional index built with it, alone. Measured with
   it on: rerank_ms 440, five promoted, four dropped, and a passage that ranked
   11th by vector similarity came back 2nd.

2. ENGINEERING.md was ten passes behind.

   It documented through pass 21 and said nothing about ASR, the review layer,
   the clock, the test database, Milvus, the edit endpoints or the launcher.
   Sections 15 to 21 cover passes 22 to 32.

3. patches/README.md stopped at pass 21.

   Eleven rows, and prose for the ones that went wrong in an instructive way.

   It also records a hole: quality_pass24.py is on neither machine. The review
   layer it built is applied and working; the script was never moved here and
   cannot be recovered. Section 16 of ENGINEERING.md is now the only account of
   what it found.
"""
import sys, pathlib, os, ast, subprocess

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
                 "      harness writes as it goes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


def append(rel, body, label, skip_if):
    """Add to the end of a document. Idempotent on a marker, never on position."""
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"FAIL: {rel} not found - run from the project root")
    s = p.read_text()
    if skip_if in s:
        CHANGES.append(f"  skip  {label} (already present)")
        return
    if not s.endswith("\n"):
        s += "\n"          # the .env lesson: never concatenate onto a last line
    p.write_text(s + body)
    CHANGES.append(f"  ok    {label}")


# ==================== 1. one shape for every exit
edit('app/review/store.py',
     'def retrieval_trace(query: str, retrieve_n: int = RETRIEVE_N,\n',
     'def _trace_out(out: dict, retrieved: list[dict], reranked: list[dict],\n               rerank_n: int, applied: bool) -> dict:\n    """The single exit from retrieval_trace, so every path returns one shape.\n\n    It had three returns and only the healthy one set `citations`, `promoted` and\n    `dropped`. So the moment the hosted reranker answered\n\n        HTTP 404: 404 page not found\n\n    - which it does permanently, because there is no hosted reranking model in\n    the catalogue - the degraded return handed back a dict its own consumers\n    could not read, and scripts/test_review.py died on\n\n        KeyError: \'citations\'\n\n    A fallback that changes the SHAPE of the result turns a degraded service into\n    a crash somewhere else entirely, which is the worst way to learn about it. The\n    difference between working and degraded belongs in a flag - `rerank_applied`,\n    plus `rerank_error` when there is one - never in which keys exist.\n    """\n    out["reranked"] = reranked\n    out["rerank_applied"] = applied\n    kept = {r["update_id"] for r in reranked}\n    out["promoted"] = [r for r in reranked if r.get("moved", 0) > 0]\n    out["dropped"] = [r for r in retrieved[:rerank_n] if r["update_id"] not in kept]\n    out["citations"] = [r["update_id"] for r in reranked]\n    return out\n\n\ndef retrieval_trace(query: str, retrieve_n: int = RETRIEVE_N,\n',
     'store.py  _trace_out, the single exit',
     skip_if='def _trace_out(')

edit('app/review/store.py',
     '    if not retrieved or rerank_n <= 0:\n        out["reranked"] = []\n        return out\n\n    t2 = time.perf_counter()\n    try:\n        ranked = nim_rerank(query, [r["text"] for r in retrieved], top_n=rerank_n)\n    except Exception as e:\n        out["rerank_error"] = f"{type(e).__name__}: {e}"\n        out["reranked"] = retrieved[:rerank_n]\n        return out\n    out["rerank_ms"] = round((time.perf_counter() - t2) * 1000, 1)\n\n    reranked = []\n    for new_rank, r in enumerate(ranked, 1):\n        src = dict(retrieved[r["index"]])\n        src["rerank_score"] = r["score"]\n        src["vector_rank"] = src.pop("rank")\n        src["rank"] = new_rank\n        src["moved"] = src["vector_rank"] - new_rank      # positive = promoted\n        reranked.append(src)\n    out["reranked"] = reranked\n\n    kept = {r["update_id"] for r in reranked}\n    out["promoted"] = [r for r in reranked if r["moved"] > 0]\n    out["dropped"] = [r for r in retrieved[:rerank_n] if r["update_id"] not in kept]\n    out["citations"] = [r["update_id"] for r in reranked]\n    return out\n',
     '    if not retrieved or rerank_n <= 0:\n        return _trace_out(out, retrieved, [], rerank_n, applied=False)\n\n    t2 = time.perf_counter()\n    try:\n        ranked = nim_rerank(query, [r["text"] for r in retrieved], top_n=rerank_n)\n    except Exception as e:\n        out["rerank_error"] = f"{type(e).__name__}: {e}"\n        # The vector order becomes the final order. Each passage is given the same\n        # keys a reranked one carries, with the truth in the numbers: it came from\n        # rank N and it moved nowhere.\n        stood = []\n        for r in retrieved[:rerank_n]:\n            d = dict(r)\n            d["vector_rank"] = d["rank"]\n            d["moved"] = 0\n            stood.append(d)\n        return _trace_out(out, retrieved, stood, rerank_n, applied=False)\n    out["rerank_ms"] = round((time.perf_counter() - t2) * 1000, 1)\n\n    reranked = []\n    for new_rank, r in enumerate(ranked, 1):\n        src = dict(retrieved[r["index"]])\n        src["rerank_score"] = r["score"]\n        src["vector_rank"] = src.pop("rank")\n        src["rank"] = new_rank\n        src["moved"] = src["vector_rank"] - new_rank      # positive = promoted\n        reranked.append(src)\n    return _trace_out(out, retrieved, reranked, rerank_n, applied=True)\n',
     'store.py  route all three paths through it',
     skip_if='_trace_out(out, retrieved')


# ==================== 2. the checker reports it instead of crashing
edit('scripts/test_review.py',
     '            check("every kept passage knows where it came from",\n                  all("vector_rank" in r and "moved" in r for r in t["reranked"]))\n',
     '            missing = [k for k in ("citations", "promoted", "dropped",\n                                   "reranked", "rerank_applied") if k not in t]\n            check("a degraded trace has the same shape as a healthy one",\n                  not missing, str(missing) or\n                  "a fallback must not change which keys exist")\n            if t.get("rerank_applied"):\n                check("the reranker reordered the vector results",\n                      any(r["moved"] != 0 for r in t["reranked"]),\n                      f"{len(t.get(\'promoted\', []))} promoted, "\n                      f"{len(t.get(\'dropped\', []))} dropped")\n            else:\n                note(f"the second stage did not run: {t.get(\'rerank_error\')}")\n                note("the vector order stands. There is no hosted reranking "\n                     "model - run the container (scripts/start_nims.sh run) and "\n                     "set NIM_MODE_RERANK=local, which leaves the hosted "\n                     "embedder and the 2048-dim index alone.")\n            check("every kept passage knows where it came from",\n                  all("vector_rank" in r and "moved" in r for r in t["reranked"]),\n                  "required on the degraded path too")\n',
     'test_review.py  assert the shape, note the degradation',
     skip_if='a degraded trace has the same shape')

edit('scripts/test_review.py',
     '            check("the trace cites exactly what search_updates cites",\n                  t["citations"] == theirs["citations"],\n                  f"{len(t[\'citations\'])} vs {len(theirs[\'citations\'])}")\n            if t["citations"] != theirs["citations"]:\n                print(f"           trace:  {t[\'citations\']}")\n                print(f"           search: {theirs[\'citations\']}")\n',
     '            # .get() and not [], because this comparison is the LAST thing that\n            # should fail here: a missing key is already reported above as the\n            # shape problem it is, rather than raised as a traceback over it.\n            mine, hers = t.get("citations", []), theirs.get("citations", [])\n            check("the trace cites exactly what search_updates cites",\n                  mine == hers, f"{len(mine)} vs {len(hers)}")\n            if mine != hers:\n                print(f"           trace:  {mine}")\n                print(f"           search: {hers}")\n',
     'test_review.py  compare citations without raising over them',
     skip_if='t.get("citations", [])')


# ==================== 3. the per-service override, documented
edit('.env.example',
     'NIM_MODE=hosted\n',
     'NIM_MODE=hosted\n\n# Per-service override, and the one you probably want. There is NO hosted\n# reranking model: with NIM_MODE=hosted the second retrieval stage fails\n#   HTTP 404: 404 page not found\n# on every single query and the vector order stands unchanged. This routes only\n# the reranker to the local container, leaving the hosted embedder - and the\n# 2048-dimensional index built with it - untouched. Needs the container:\n#   bash scripts/start_nims.sh run\n# NIM_MODE_RERANK=local\n',
     '.env.example  there is no hosted reranker',
     skip_if='NIM_MODE_RERANK')

edit('README.md',
     '| `NIM_MODE` | `auto` | `hosted` skips the local probe, `local` requires the containers; changing it changes the embedder, so rebuild the index |\n',
     '| `NIM_MODE` | `auto` | `hosted` skips the local probe, `local` requires the containers; changing it changes the embedder, so rebuild the index |\n| `NIM_MODE_{LLM,EMBED,RERANK}` | `NIM_MODE` | per-service override; `NIM_MODE_RERANK=local` is the useful one — there is no hosted reranking model |\n',
     'README.md  the per-service override',
     skip_if='NIM_MODE_{LLM,EMBED,RERANK}')


# ==================== 3b. status must not guess where the models run
edit('scripts/stack.sh',
     '# The local NIMs can be running while the app ignores them completely. That is\n# ~41GB of VRAM doing nothing, and it is invisible unless something says so.\nnim_advice() {\n  local running\n  running="$(docker ps --filter \'name=nim-\' --format \'{{.Names}}\' 2>/dev/null | wc -l | tr -d \' \')"\n  [ "${running:-0}" -gt 0 ] || return 0\n  case "${NIM_MODE:-auto}" in\n    hosted)\n      echo "  note  $running local NIM container(s) are up, but NIM_MODE=hosted -"\n      echo "        the app is calling build.nvidia.com and not using them."\n      echo "        Free the VRAM with: bash scripts/start_nims.sh stop" ;;\n    *) echo "  note  $running local NIM container(s) up, NIM_MODE=${NIM_MODE:-auto}" ;;\n  esac\n}\n',
     '# Where each service ACTUALLY resolves. Ask the client; do not infer it from\n# NIM_MODE. That inference was right for about a day and then stopped being the\n# whole answer: with NIM_MODE=hosted and NIM_MODE_RERANK=local, "the app is not\n# using them" was false about the reranker, which is the only service that has no\n# hosted model at all. resolve() is the code that decides, so it is the only\n# honest source for a status line.\nrouting() {\n  [ -x "$PY" ] || return 0\n  "$PYABS" - <<\'PYEOF\' 2>/dev/null\nfrom app.nim.client import resolve\nfor s in ("llm", "embed", "rerank"):\n    _base, model, mode = resolve(s)\n    print(f"  {s:9s} {mode:7s} {model}")\nPYEOF\n}\n\n# The local NIMs can be running while nothing routes to them. That is ~41GB of\n# VRAM doing nothing, and it is invisible unless something says so.\nnim_advice() {\n  local running used\n  running="$(docker ps --filter \'name=nim-\' --format \'{{.Names}}\' 2>/dev/null | wc -l | tr -d \' \')"\n  [ "${running:-0}" -gt 0 ] || return 0\n  used="$(routing | grep -cw local)"\n  if [ "${used:-0}" = 0 ]; then\n    echo "  note  $running local NIM container(s) up and NOTHING routes to them."\n    echo "        Free the VRAM with: bash scripts/start_nims.sh stop"\n  else\n    echo "  note  $running local NIM container(s) up, $used service(s) routed to them"\n  fi\n}\n',
     'stack.sh  ask resolve() instead of reading NIM_MODE',
     skip_if='routing()')

edit('scripts/stack.sh',
     '  nim_advice\n  echo\n  echo "  logs: bash scripts/stack.sh logs ui | api | milvus"\n',
     '  echo "MODELS"\n  routing || echo "  (could not resolve - is the venv present?)"\n  echo\n  nim_advice\n  echo\n  echo "  logs: bash scripts/stack.sh logs ui | api | milvus"\n',
     'stack.sh  a MODELS section in status',
     skip_if='echo "MODELS"')

# ==================== 4. the engineering record, passes 22-32

append('ENGINEERING.md', '\n## 15. Voice in: Riva ASR, and a self-test that proved nothing\n\nThe ASR path runs Riva over gRPC through NVCF. What it did not have was a test\nworth running. `scripts/test_asr.py` generated a **440 Hz sine tone**, sent it to\nthe recogniser, got an empty transcript, and reported success — because it only\never asserted that the call returned. A tone contains no speech, so the one thing\nthe test could not tell you was whether transcription works.\n\nIt now synthesises real speech (`scripts/make_speech.py`), transcribes it, and\ngrades the result against the text it dictated.\n\nThree separate faults came out of making it real.\n\n**An empty transcript was reported as a failure with no cause.** The pipeline\nreturned `error=None` alongside zero words, and the UI printed\n`Transcription failed: None`. Nothing was wrong with the error handling — there\nwas simply no branch for "the call succeeded and produced nothing", which is\nexactly what a tone produces. `_no_words()` in `app/pipeline/asr.py` names that\ncase.\n\n**A perfect transcript scored 46% word error rate.** The recogniser writes\n`3.5 mm`, the dictation said `three point five millimetres`; it writes `tyre`\nwhere the script said `tire`. Naive WER counts those as errors and a correct\ntranscription looks broken. Numbers and spelling are canonicalised on both sides\nbefore comparison.\n\n**The worst one was silent.** `figures()` scanned the *raw dictated reference*\nfor measurements, and the reference is words — `three point five` — so it found no\ndigits at all, concluded there was nothing to lose, and reported a clean sweep on\na transcript that had dropped every single measurement. A checker that looks in\nthe wrong representation does not fail; it passes, loudly, forever. Canonicalise\nfirst, then compare per figure.\n\n### Still not covered\n\nThe synthesised voice is not a technician in a workshop. It has no background\nnoise, no accent, no overlapping speech and no microphone. The figures it reports\nare a floor, not a field measurement.\n',
       'ENGINEERING.md  section 15', skip_if='## 15. Voice in: Riva ASR')

append('ENGINEERING.md', '\n## 16. Reviewing the data, and the vectors\n\nThe dataset and the index were both write-only from the outside: you could ask\nthe agent a question, but you could not look at what it was answering from.\n`app/review/store.py` and the Data & Retrieval tab make both readable — repair\norders, the event log, the updates, the chunks, and a two-stage retrieval trace\nthat shows what the reranker actually changed.\n\nFour things in the first version were wrong in ways worth recording.\n\n**`overview()` returned zeros for a missing database.** Not an error — zeros. A\nreview screen whose job is to tell you the state of the data reported "0 repair\norders" for both an empty shop and an absent file, which are very different\nproblems.\n\n**The chunk browser pulled every vector to display a page of text.** 1,949\nchunks at 2048 floats each, fetched and discarded to render twenty rows. Arrow\'s\n`drop_columns` leaves them in the store.\n\n**A serialisability check that could not fail.** It tested each value with\n`json.dumps(v, default=str)` — and `default=str` is precisely the instruction\n"serialise anything by stringifying it". Everything passes. The check asserted\nthe fallback, not the property.\n\n**A hardcoded count.** It asserted nine review endpoints; there are ten. A count\nin a test is a second copy of a fact that will drift from the first. It now\nasserts that every documented path is served and that nothing bypasses the store.\n',
       'ENGINEERING.md  section 16', skip_if='## 16. Reviewing the data')

append('ENGINEERING.md', '\n## 17. The clock follows the data\n\nEvery derived state in this system — promise risk, at-risk, "this week", which\nshift someone worked — is computed against "now". The dataset is generated\nrelative to a moment and then stops moving. Those two facts together mean a demo\nrots: on the wall clock, **five days was enough to fail four of the fourteen\nanswer checks**. Every time-window question returned nothing, cited nothing, and\nwas then blocked by the output rail for citing nothing. The agent was behaving\ncorrectly and looked broken.\n\n`app/state/clock.py` makes `now()` the timestamp of the newest event in the log.\nThe shop is always live, a dataset never goes stale, and there is no date to pin\nbefore a demo. `event_time()` is that plus one second, so a new update is always\nafter everything it follows. `ASOIA_NOW` still pins the clock when you want a\nfixed one and `ASOIA_CLOCK=wall` restores the old behaviour.\n\n`app/state/bootstrap.py` generates a dataset when there is none, which removes\nthe other manual step. Two bugs in it are worth keeping:\n\n**It checked one database and generated into another.** The emptiness check used\na fresh connection and the generator wrote wherever `ASOIA_DB` pointed. With a\npopulated database at a non-default path, it would have decided the data was\nmissing and overwritten 400 repair orders with 12. It now resolves the actual\nfile behind the live connection with `PRAGMA database_list`.\n\n**`build_dataset` closes the cached connection.** Everything holding that handle\nafterwards failed with `Cannot operate on a closed database`. The cache is\nevicted and the data read back through a new connection, which also verifies the\ngeneration actually landed.\n\nVerified: four failing answer checks went to zero, and they still pass against a\ndataset 200 days old.\n',
       'ENGINEERING.md  section 17', skip_if='## 17. The clock follows the data')

append('ENGINEERING.md', '\n## 18. The test suite got its own database\n\nThe 81 tests ran against whatever was in `data/generated/`. That is fine until it\nis not: one of them failed with `KeyError: \'found\'` after a tarball was\nre-extracted over the tree and restored a 0-byte placeholder database. The test\nwas correct and the data underneath it had changed.\n\n`tests/conftest.py` now points `ASOIA_DB` at a temporary path and generates a\ndataset into it, at module level so it happens before any test imports the app.\n`ASOIA_TEST_DB=keep` opts out when you want to test against the real thing.\n\nTwo mistakes while writing it:\n\n**The first version called `build_dataset` directly** and hit the closed-cache\nbug from section 17 — `Cannot operate on a closed database`. It goes through\n`ensure_dataset()`, which is where that is handled.\n\n**A replacement assertion was simply wrong.** I asserted `"error" not in r` for a\nhealthy lookup, but a healthy *not-found* result carries **both** `found: False`\nand an `error` describing what was not found. The discriminator is `found`, and\n`error` is explanatory text that may accompany a perfectly correct answer. Reading\nthe shape beats assuming it.\n',
       'ENGINEERING.md  section 18', skip_if='## 18. The test suite got its own database')

append('ENGINEERING.md', '\n## 19. Milvus, and editing a store that is derived\n\nThe vector store is Milvus, behind `app/retrieval/backend.py` so that Milvus and\nthe previous LanceDB store are a config change rather than a code change\n(`VECTOR_BACKEND`). `scripts/start_milvus.sh` runs standalone in one container —\netcd in-process, local filesystem instead of MinIO, which is the right trade for a\nsingle box.\n\n**Embedded Milvus Lite could not be used, and that is a regression the store\nintroduced.** It takes an exclusive file lock on its data directory:\n\n    DataDirLockedError: another process holds the lock on\n    \'.../data/generated/milvus.db\': [Errno 11] Resource temporarily unavailable\n\nWith the UI running, nothing else could open the store — not the API, not\n`scripts/test_review.py`, not a rebuild. LanceDB allowed concurrent readers.\nStandalone is a server and the question does not arise.\n\nSix faults from this work, each of which cost real time:\n\n**`MILVUS_URI` is reserved by pymilvus.** Setting it as our own config variable\nchanged the library\'s behaviour underneath us. Ours is `ASOIA_MILVUS_URI`.\n\n**The image does not ship `embedEtcd.yaml`.** Pointing `ETCD_CONFIG_PATH` at a\nfile that is not there makes Milvus panic with a nil pointer dereference and exit\n134 — a Go stack trace with no mention of a missing config. The launcher writes\nthat file before starting the container.\n\n**An unloaded collection reads as empty.** Milvus will not serve a collection\nuntil it is loaded into memory, and it does not say so — it returns zero rows,\nwhich reads exactly like a store that was never built. `_load()` calls\n`load_collection` before any read.\n\n**Writes were not visible to the next read.** A server is eventually consistent\nby default, so an upsert followed immediately by a search legitimately missed it.\n`consistency_level="Strong"` on create, `get()` and `scan()`.\n\n**Editing wrote to the index, and that is the wrong place.** A chunk is one\n`updates` row, embedded. Edit the chunk and it no longer matches the record it\ncites, and nothing would catch it: `index_staleness()` compared ids and counts,\nnot text, and `check_grounding` checks figures in the answer against the tool\nresults, never that a cited id resolves to a row. You would get confident,\nwell-formed, fully "grounded" answers quoting text that is not in the database.\nSo an edit changes the **source** and re-embeds, and `index_staleness()` gained a\n`text_drift` check that compares the two.\n\n**The audit trail went into `events`, and that broke the agent.** `events` is the\nrepair-order lifecycle log: every row is parsed through the `EventType` enum and\nfolded into state. Three new type strings took out seven of the fourteen answer\nchecks and every read of an affected repair order with\n\n    ValueError: \'UPDATE_TEXT_EDITED\' is not a valid EventType\n\nCorrections live in `index_audit`, where they cannot reach the fold. A data\ncorrection is not something that happened in the workshop.\n\nThe same four operations are on the API (`PATCH /review/chunks/{id}`, and\n`reindex`, `exclude`, `restore`, plus `history` and `/review/edits`), gated by\n`ASOIA_REVIEW_WRITES`. There is deliberately no "add a chunk" — a chunk exists\nbecause an update exists — and no "delete an update", because removing a\ntechnician\'s note is not an edit. `exclude` covers the real need and is reversible.\n\n### Two self-inflicted ones\n\nRenaming a key in `stats()` from `table` to `collection` without grepping for\nconsumers produced `KeyError: \'table\'` at the far end. And appending to `.env`\nwithout checking it ended in a newline **glued the new variable onto the API key**,\nwhich then failed with HTTP 403 and looked like a revoked credential. Both are\ncheap to avoid and neither was.\n',
       'ENGINEERING.md  section 19', skip_if='## 19. Milvus, and editing a store')

append('ENGINEERING.md', '\n## 20. One command up, one command down\n\nStarting this project meant five things in a fixed order, three of them\nbackgrounded by hand, and the order mattered — the store before the API, because\nthe API reads it on the way up. That is a runbook, and a runbook is a bug report\nabout the tooling. `scripts/stack.sh` is `up`, `down`, `restart`, `status` and\n`logs`, and the store carries `--restart unless-stopped` so it survives a reboot.\n\nThree things in it are load-bearing, and all three are there because the obvious\nversion was wrong.\n\n**`echo $!` does not give you the server.** `setsid` forks when it is already a\nprocess group leader and execs when it is not, so `$!` is whichever of the two\nhappened. Measured on the box: `$!` reported **77108** while the process was\n**77110**. A pid file with the wrong number in it is worse than none, because\neverything downstream believes it. Bash writes its own pid and then execs python\nover itself, so the file holds the server by construction.\n\n**`pgrep -f app.ui.gradio_app` matches more than the server.** It matches the ssh\ncommand line that launched it and it matches the script doing the search. That is\nhow twenty minutes went into\n\n    OSError: Cannot find empty port in range: 7860-7860\n\nwhich was a second copy of the UI, not a port problem. Services are tracked by pid\nfile, and `alive()` reads the command line of that pid back to confirm it is still\nthe process we started — so a pid file left behind by a killed process is detected\nrather than believed.\n\n**A server already running without a pid file has to be adopted.** Otherwise the\nfirst `up` on a box where things were started by hand is the port collision above.\n`adopt()` finds the listener, checks it is really ours, and claims it; a port held\nby something else is reported with the offending command line instead of walked\ninto.\n\n**`--share` cannot be added to a live process.** The tunnel opens during launch.\nAdopting a running UI skipped the launch and then reported whatever URL was left\nin the log, which is a dead link presented as the live one. It refuses and says to\nrestart.\n\n### `docker kill` does not test a restart policy\n\nIt stayed dead, and that was correct: Docker treats `kill` and `stop` as\nuser-initiated, and `unless-stopped` exists precisely to not override those — that\nis the whole difference from `always`. The policy covers a crash or a daemon\nrestart. A restart policy is also fixed at container-create time, so `up` applies\nit to a container that predates the change with `docker update`, in place and\nwithout dropping a request.\n',
       'ENGINEERING.md  section 20', skip_if='## 20. One command up, one command down')

append('ENGINEERING.md', "\n## 21. A fallback that changed the shape of its result\n\nThere is **no hosted reranking model**. With `NIM_MODE=hosted` the second\nretrieval stage fails on every query:\n\n    HTTP 404: 404 page not found  (nv-rerankqa-mistral-4b-v3/reranking)\n\n`search()` already handled that correctly — it flags `rerank_error` and returns\nthe vector order. `retrieval_trace()` did not. It had three exit paths and only\nthe healthy one set `citations`, `promoted` and `dropped`, so a degraded trace\nhanded back a dict its own consumers could not read, and `scripts/test_review.py\n--live` died on\n\n    KeyError: 'citations'\n\nThe reranker being unavailable is a service condition. It arrived as a traceback\nin a checker two modules away, which is the worst available way to learn about it.\nEvery exit now goes through one function, so a degraded result is the same\n**shape** as a healthy one: the passages that stood carry `vector_rank` and\n`moved: 0`, and the difference lives in `rerank_applied` and `rerank_error`. The\ntest asserts that shape explicitly and reports a missing reranker as a note.\n\n**The fix for the reranker itself is one variable.** `NIM_MODE_RERANK=local`\nroutes only that service to the container from `scripts/start_nims.sh`, leaving\nthe hosted embedder — and the 2048-dimensional index built with it — alone.\nMeasured with it on: `rerank_ms` 440, five passages promoted and four dropped, and\na passage that ranked **11th** by vector similarity came back **2nd**. That is the\nsecond stage doing real work, and without it the pipeline silently degrades to\nsingle-stage retrieval.\n\nSwitching `NIM_MODE=local` wholesale does not work: the hosted embedder is\n2048-dimensional and the local `nv-embedqa-e5-v5` is 1024, so the index would have\nto be rebuilt. Per-service routing is the only way to have both.\n",
       'ENGINEERING.md  section 21', skip_if='## 21. A fallback that changed the shape')


# ==================== 5. the patch index
edit('patches/README.md',
     '| `quality_pass21.py` | the colang rails had never been called; wired in behind off/shadow/on, defaulting to off |\n',
     "| `quality_pass21.py` | the colang rails had never been called; wired in behind off/shadow/on, defaulting to off |\n| `quality_pass22.py` | the hosted ASR is gRPC, not REST, and the UI hid that it was failing |\n| `quality_pass23.py` | the ASR self-test sent a 440 Hz sine tone and reported success on an empty transcript; real speech, and a graded comparison |\n| *(pass 24 — missing)* | the review layer. Applied and working (`app/review/store.py`, the Data & Retrieval tab) but **its script was never archived here**; see below |\n| `quality_pass25.py` | the clock follows the newest event instead of the wall clock, and a stale index says so |\n| `quality_pass25_readme.py` | the same pass's documentation, split out because a README anchor must never be able to stop a code pass |\n| `quality_pass26.py` | the test suite stops depending on the project's database |\n| `quality_pass27.py` | Milvus, and a vector store you can actually correct |\n| `quality_pass28.py` | model ids are configuration, not code — the hosted embedder was retired underneath us |\n| `quality_pass29.py` | the Vector store tab crashed on a key I renamed without grepping for its readers |\n| `quality_pass30.py` | a launcher for Milvus standalone, and the four edit operations on the API |\n| `quality_pass31.py` | one command up and down for the whole stack, and a restart policy on the store |\n| `quality_pass32.py` | a degraded reranker returned a differently-shaped result and crashed a checker two modules away; the engineering record caught up |\n",
     'patches/README.md  rows for 22-32',
     skip_if='`quality_pass32.py`')

append('patches/README.md', '\n### Pass 24 is not in this directory, and it should be\n\nThe review layer it built is present and working — `app/review/store.py`, the\nreview endpoints, the Data & Retrieval tab — but the script that applied it is on\nneither machine. It was written, run against the tree, and never moved here, and\nthere is no copy to recover.\n\nWhich makes the point of this directory sharper than any of the notes in it: the\ncode survived because it was applied, and the *reasoning* is gone. What pass 24\nfound — `overview()` returning zeros for a missing database rather than an error,\nthe chunk browser fetching 1,949 vectors to render twenty rows of text, a\nserialisability check that used `json.dumps(v, default=str)` and therefore could\nnever fail, a hardcoded count of nine endpoints where there are ten — survives\nonly because section 16 of `ENGINEERING.md` was written from the record before it\nwas lost. Move the script here as part of the pass, not afterwards.\n\n### Pass 26 and the assertion that read the wrong field\n\nIts first conftest called `build_dataset` directly and inherited the closed-cache\nbug — `Cannot operate on a closed database`. Worse was the replacement assertion:\n`"error" not in r` for a healthy lookup. A healthy **not-found** result carries\n*both* `found: False` and an `error` describing what was not found, so the\nassertion was testing something the API never promised. The discriminator is\n`found`; `error` is explanatory text that can accompany a correct answer.\n\n### Pass 27 put the audit trail in the event log, and the agent stopped working\n\n`events` is the repair-order lifecycle log: every row is parsed through the\n`EventType` enum and folded into state. Three new type strings for data\ncorrections took out **seven of the fourteen answer checks** and every read of an\naffected repair order:\n\n    ValueError: \'UPDATE_TEXT_EDITED\' is not a valid EventType\n\nThe docstring in `app/retrieval/edit.py` had already said these were not lifecycle\nevents. Writing them there anyway is the mistake; `index_audit` is where they live.\n\nAlso in pass 27: `MILVUS_URI` is reserved by pymilvus and setting it changed the\nlibrary\'s behaviour underneath us (ours is `ASOIA_MILVUS_URI`), and an unloaded\nMilvus collection reads as **empty** rather than erroring — indistinguishable from\na store that was never built.\n\n### Pass 29: renaming a key without grepping for its readers\n\n`stats()` returned `table`; it became `collection`; nothing else was changed, and\nthe far end raised `KeyError: \'table\'`. The check written for it then asserted a\nstring that appeared in its own explanatory comment, so it passed against broken\ncode. **A check that matches the prose next to it is not a check** — this is the\nthird time in this project (pass 30\'s `embedEtcd.yaml` check, pass 31\'s `pgrep`\ncheck) and it is always the same shape: asserting a word that the file contains\nbecause the file talks about it.\n\n### Pass 30 and Pass 31: three checks that could not fail\n\nPass 30 counted `_writes_allowed` and got 5 for four call sites, because the bare\nname matches the `def` as well. Pass 31 asserted `"pgrep" not in body` on a script\nwhose comments explain at length why `pgrep` is wrong. Both now match a *call*\nrather than a word.\n\nPass 31 also had a genuinely non-idempotent edit: the anchor\n`*.egg-info/\\n*.bak\\n` **survives its own replacement**, so it applied cleanly on\nevery run and left three copies of `run/` in `.gitignore`. An edit whose anchor is\nstill present afterwards can never be idempotent, however careful its `skip_if`;\nthat file is written whole now.\n\n### Pass 32 is mostly documentation, and that is the point\n\nThe code fix is small — one exit path for `retrieval_trace` so a degraded result\nhas the same shape as a healthy one. The rest of the pass is the engineering\nrecord for passes 22 to 31, which had fallen ten passes behind while the table\nabove stopped at 21. A record that lags is a record nobody trusts, and the whole\nvalue of these scripts is that they explain *why* rather than *what*.\n',
       'patches/README.md  what went wrong in 24-32',
       skip_if='### Pass 24 is not in this directory')


# ==================== verify
print("Quality pass 32:")
for c in CHANGES:
    print(c)

bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}" + (f"  ({detail})" if detail else ""))


print("\nthe code parses:")
for f in ("app/review/store.py", "scripts/test_review.py"):
    try:
        ast.parse((ROOT / f).read_text())
        chk(f"{f}", True)
    except SyntaxError as e:
        chk(f"{f}", False, f"line {e.lineno}: {e.msg}")

print("\none shape, every exit:")
st = (ROOT / "app/review/store.py").read_text()
chk("there is a single exit helper", "def _trace_out(" in st)
# The property that was violated: no path may return out directly once the
# helper exists, because that is how a path skips citations/promoted/dropped.
_fn = st.split("def retrieval_trace(")[1].split("\n# ---")[0]
_bare = [l for l in _fn.splitlines() if l.strip() == "return out"]
chk("no exit returns the bare dict", not _bare,
    f"{len(_bare)} bare `return out` left" if _bare else
    "every path goes through _trace_out")
chk("every exit routes through it", _fn.count("_trace_out(out,") == 3,
    f"{_fn.count('_trace_out(out,')} of 3 paths")
chk("the degraded path still labels its passages",
    'd["vector_rank"] = d["rank"]' in st and 'd["moved"] = 0' in st,
    "a fallback must not drop keys its consumers read")
chk("the difference is a flag, not a key",
    'out["rerank_applied"] = applied' in st)

print("\nthe checker cannot crash on it:")
tr = (ROOT / "scripts/test_review.py").read_text()
chk("it asserts the shape before comparing",
    "a degraded trace has the same shape as a healthy one" in tr)
chk("the citation comparison uses .get()",
    't.get("citations", [])' in tr and 't["citations"]' not in tr,
    "a missing key is reported as a shape problem, not raised over one")
chk("a missing reranker is a note, not a failure",
    "the second stage did not run" in tr)
chk("that note names the fix",
    "NIM_MODE_RERANK=local" in tr)

print("\nstatus tells the truth about routing:")
sh = (ROOT / "scripts/stack.sh").read_text()
chk("it asks resolve() rather than reading NIM_MODE",
    "from app.nim.client import resolve" in sh,
    "NIM_MODE stopped being the whole answer once per-service overrides existed")
chk("the advisory counts what is routed, not the mode",
    "routing | grep -cw local" in sh and "NIM_MODE=hosted -" not in sh)
chk("status prints where each model runs", 'echo "MODELS"' in sh)
r = subprocess.run(["bash", "-n", "scripts/stack.sh"], capture_output=True, text=True)
chk("stack.sh is still valid bash", r.returncode == 0, (r.stderr or "").strip()[:90])

print("\nthe record:")
eng = (ROOT / "ENGINEERING.md").read_text()
for n, title in ((15, "Riva ASR"), (16, "Reviewing the data"), (17, "clock follows"),
                 (18, "own database"), (19, "Milvus"), (20, "One command"),
                 (21, "shape of its result")):
    chk(f"ENGINEERING section {n}", f"## {n}." in eng and title in eng)
chk("it records the 440 Hz tone", "440 Hz" in eng)
chk("it records the pid that was not the server", "77108" in eng and "77110" in eng)
chk("it records the EventType failure",
    "is not a valid EventType" in eng)
chk("it records that docker kill does not test a restart policy",
    "does not test a restart policy" in eng)

pr = (ROOT / "patches/README.md").read_text()
rows = pr.count("| `quality_pass")
chk("the table covers every archived pass", rows >= 32, f"{rows} rows")
chk("the missing pass 24 is recorded, not hidden",
    "pass 24 — missing" in pr and "neither machine" in pr)
chk("pass 32 is in the table", "`quality_pass32.py`" in pr)

print("\nthe archive matches the table:")
have = {p.name for p in (ROOT / "patches").glob("quality_pass*.py")}
listed = set()
for line in pr.splitlines():
    if line.startswith("| `quality_pass"):
        listed.add(line.split("`")[1])
# pass 32 is itself not yet moved into patches/ when this runs from the root.
missing_files = sorted(n for n in listed - have if n != "quality_pass32.py")
chk("every listed script is present", not missing_files, str(missing_files))
unlisted = sorted(have - listed)
chk("every present script is listed", not unlisted, str(unlisted))

print("\nthe config note:")
ee = (ROOT / ".env.example").read_text()
chk(".env.example explains the 404 and the per-service fix",
    "404 page not found" in ee and "NIM_MODE_RERANK=local" in ee)
chk("it leaves the override commented out",
    "# NIM_MODE_RERANK=local" in ee,
    "it needs a container, and the file must work without a GPU")
rm = (ROOT / "README.md").read_text()
chk("the environment table lists the per-service override",
    "NIM_MODE_{LLM,EMBED,RERANK}" in rm)

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
    .venv/bin/python scripts/test_review.py --live      degraded or not, no crash
    NIM_MODE_RERANK=local .venv/bin/python scripts/test_review.py --live
""")
sys.exit(1 if bad else 0)

