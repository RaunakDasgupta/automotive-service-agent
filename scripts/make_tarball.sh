#!/usr/bin/env bash
# Pack this working copy for a remote box, without going through GitHub.
#
#   bash scripts/make_tarball.sh [/path/to/out.tar.gz]
#
# Then, on the box:
#   scp asoia.tar.gz <host>:/home/ubuntu/
#   ssh <host> 'cd /home/ubuntu && tar -xzf asoia.tar.gz && cd automotive-service-agent && git log --oneline -1'
#
# TWO THINGS THIS GETS RIGHT, both of which bit once.
#
# macOS metadata. bsdtar on macOS stores xattrs and resource forks by default.
# GNU tar on Linux then prints
#     tar: Ignoring unknown extended header keyword 'LIBARCHIVE.xattr.com.apple.provenance'
# once PER FILE - thousands of lines that read like a failed extraction - and
# writes AppleDouble `._*` siblings. Those land inside .git/objects/pack/, and
# git refuses the repository with
#     error: index file .git/objects/pack/._pack-....idx is too small
# so the extracted tree looked fine and had a broken git. COPYFILE_DISABLE=1
# plus --no-mac-metadata --no-xattrs is the fix; the flags are bsdtar's and are
# simply absent on Linux, so this script is meant to run on the Mac.
#
# Secrets. .env holds a live key and must never travel in an archive, nor must
# the dated .bak copies the patch scripts used to write. Those are excluded, and
# then the result is CHECKED - the script refuses to finish if an .env or a .bak
# made it in, rather than trusting the exclude list it just wrote.
#
# data/generated/ is excluded because it is rebuildable in 0.1s and 368 MB of it
# is a Milvus volume - but .gitkeep is kept, or the directory arrives missing and
# git reports it deleted on a fresh extract.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"; NAME="$(basename "$ROOT")"
OUT="${1:-$ROOT/../asoia.tar.gz}"
case "$OUT" in /*) ;; *) OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")" ;; esac

rm -f "$OUT"
COPYFILE_DISABLE=1 tar --no-mac-metadata --no-xattrs --no-acls --no-fflags \
  --exclude='.venv' --exclude='.venv-curator' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='*.egg-info' \
  --exclude='.env' --exclude='.env.bak*' --exclude='*.bak' --exclude='*.bak.*' \
  --exclude='data/generated/*.sqlite' --exclude='data/generated/*.sqlite-*' \
  --exclude='data/generated/*.json' --exclude='data/generated/*.db' \
  --exclude='data/milvus' --exclude='run' --exclude='.gradio' \
  --exclude='.pytest_cache' --exclude='.ipynb_checkpoints' \
  --exclude='evals/data/*.jsonl' --exclude='*.tar.gz' \
  --exclude='.DS_Store' --exclude='._*' \
  -czf "$OUT" -C "$(dirname "$ROOT")" "$NAME" || { echo "tar failed"; exit 1; }

# ------------------------------------------------------------------ check it
fail=0
if tar -tzf "$OUT" | grep -qE "(^|/)\.env$|\.bak(\$|\.)"; then
  echo "REFUSING: an .env or .bak is in the archive"; fail=1
fi
if tar -tzf "$OUT" | grep -q '/\._'; then
  echo "REFUSING: AppleDouble ._ entries are in the archive"; fail=1
fi
if ! tar -tzf "$OUT" | grep -q 'data/generated/.gitkeep'; then
  echo "warning: data/generated/.gitkeep missing - git will report it deleted"
fi
[ "$fail" = 0 ] || { rm -f "$OUT"; exit 1; }

echo "$OUT"
echo "  size    $(du -h "$OUT" | cut -f1)"
echo "  files   $(tar -tzf "$OUT" | wc -l | tr -d ' ')"
echo "  commit  $(git log --oneline -1 2>/dev/null || echo 'not a git repo')"
echo "  sha256  $(shasum -a 256 "$OUT" | cut -d' ' -f1)"
