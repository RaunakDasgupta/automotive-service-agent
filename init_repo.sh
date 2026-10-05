#!/usr/bin/env bash
# Initialise the git repository and make the first commit.
#
#   bash init_repo.sh --dry-run    # show what would happen, change nothing
#   bash init_repo.sh
#
# Refuses to commit if a key, the virtualenv, the database or the vector index
# would be staged. Safe to re-run: it will not rewrite an existing history.
set -uo pipefail
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
say(){ printf '%s\n' "$*"; }
step(){ printf '\n== %s\n' "$*"; }

[ -f pyproject.toml ] && [ -d app/agent ] || { say "Run from the project root."; exit 1; }
command -v git >/dev/null || { say "git is not installed."; exit 1; }
[ "$DRY" = 1 ] && say "DRY RUN - nothing will be changed."

step "required ignore rules"
for must in '.env' '.venv/' 'data/generated/*'; do
  grep -qF "$must" .gitignore 2>/dev/null \
    && say "   present: $must" \
    || { say "   MISSING: $must - stopping."; exit 1; }
done

step "git"
if [ -d .git ] && git rev-parse HEAD >/dev/null 2>&1; then
  say "   history already exists at $(git rev-parse --short HEAD)."
  say "   This script will not rewrite it. Commit further changes yourself."
  exit 0
fi
[ -d .git ] || { say "   git init -b main"; [ "$DRY" = 1 ] || git init -q -b main; }
[ "$DRY" = 1 ] && { say ""; say "DRY RUN complete."; exit 0; }

[ -n "$(git config user.email)" ] || {
  git config user.email "code.fourhorsemen@gmail.com"
  git config user.name  "Raunak Dasgupta"
  say "   set a repo-local identity (your global config is untouched)."
}

git add -A
step "safety check"
LEAK=$(git diff --cached --name-only \
       | grep -E '^\.env$|(^|/)\.venv/|(^|/)\.tv/|service\.sqlite|\.lance(/|$)|\.pyc$' || true)
if [ -n "$LEAK" ]; then
  say "   REFUSING TO COMMIT - these would be included:"
  printf '     %s\n' $LEAK
  say "   Nothing was committed. Fix .gitignore, then: git reset && bash init_repo.sh"
  exit 1
fi
if git diff --cached -U0 | grep -qE 'nvapi-[A-Za-z0-9_-]{20,}'; then
  say "   REFUSING TO COMMIT - a string that looks like a live NVIDIA key is staged."
  say "   Find it with: git diff --cached | grep -n 'nvapi-'"
  exit 1
fi
say "   no key, virtualenv, database, vector index or bytecode staged"
say "   staging $(git diff --cached --name-only | wc -l | tr -d ' ') files"

step "commit"
git commit -q -F - <<'MSG'
Deterministic answer composition, NIM deployment fixes, dashboard UI

Bring a three-NIM stack up on an L40S and make every structured answer correct by
construction rather than by prompt compliance.

scripts/start_nims.sh: pin the reranker to a tag that exists, run containers as
the invoking user so the model cache is writable, stop forcing the container's
internal HTTP port onto Triton's gRPC and metrics ports, source .env so
logs/stop/health work in a fresh shell, and set the VRAM cap for whichever
backend the image selects.

app/agent: one renderer per tool shape composes the answer in Python for every
structured question, so those paths make no model call at all. The LLM keeps only
search_updates, which is genuine language work, and gets a prompt fitted to that
payload rather than to a structured one. Renderers never derive a figure, so the
grounding rail cannot fire on them. A new rail rejects claims about what did not
happen - absence from the records is not evidence of absence in the workshop.
Fallbacks are recorded and surfaced instead of silently degrading to narration.

app/analytics: get_shift_activity answers "who worked yesterday afternoon" from
the shift column, which is recorded, rather than by searching update prose. Tools
now return what their answers need: operation descriptions, safety findings,
vehicle and concern, and an honest shown count.

app/pipeline: resolve_op required only a generic word in common to return a
confident match, and its ambiguity guard sat above the acceptance threshold and
had never blocked anything.

app/retrieval: the reranker was only ever seeing k candidates because the wide
pool built by limit() was sliced away. Query embeddings are cached.

app/ui: six tabs to five, with a dashboard. The technician tab shows the repair
order's own completed and pending work instead of the whole catalogue. Answers
stream, and the footer says whether the text was computed or narrated.

Adds scripts/verify_answers.py, scripts/timings.py and
scripts/test_voice_update.py, which prove the above against the real database and
exit non-zero on failure. patches/ keeps the sixteen migration scripts as the
record; ENGINEERING.md explains each defect and how it was found.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
say "   committed $(git rev-parse --short HEAD)"
git show --stat --oneline HEAD | head -20
cat <<'NEXT'

To put it on GitHub (private):

  gh auth status
  gh repo create automotive-service-agent --private --source=. --remote=origin --push
NEXT
