#!/usr/bin/env python3
"""Does speech to text actually work? Real words in, graded transcript out.

    .venv/bin/python scripts/test_asr.py --sample 1      # synthesise and grade
    .venv/bin/python scripts/test_asr.py --wav u.wav --expect "what was said"
    .venv/bin/python scripts/test_asr.py --wav u.wav      # no grade, just read it

Exit codes:  0 transcribed and accurate | 1 transcribed but poor | 2 not working

WHAT WAS WRONG WITH THE OLD CHECK

It transcribed a 440 Hz sine tone and printed the result. A tone contains no
words, so an empty transcript was the correct answer - and also exactly what a
completely broken ASR returns. The check could not fail, and it could not pass.
It measured the transport and nothing else, while reading as though it had
measured transcription.

This one speaks a real update, with real figures, and grades three things
separately, because they fail for different reasons and need different fixes:

  READINESS   is the client installed, is a route configured
  TRANSPORT   did the call reach NVCF and come back without a gRPC status
  ACCURACY    did the words come back, and did the FIGURES survive

The figures matter more than the words. "Front pads at 1.8mm against a 3mm
minimum" is the whole content of that update; a transcript that renders the prose
beautifully and turns 1.8 into 1.4 is worse than useless, because it is wrong in
a way nobody will notice. So the word error rate is reported, and then every
number is checked for on its own.
"""
from __future__ import annotations
import argparse, os, re, sys, time

sys.path.insert(0, ".")
import _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py

WER_WARN = 0.35      # synthetic speech through a good model should beat this


# ------------------------------------------------------------------ scoring

# A model that says "1.8" has not made an error when the script said "one point
# eight", and one that writes US English has not made an error when the sample was
# written in British English. Both count as errors to a naive word comparison, and
# the first alone put a PERFECT transcript at 46% - a check that reports failure on
# correct output teaches people to ignore it. So both sides are canonicalised to
# one spelling and one way of writing a number before anything is counted.

_DIGIT = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3",
          "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
          "nine": "9"}
_TEENS = {"ten": "10", "eleven": "11", "twelve": "12"}
_SPELLING = [("metre", "meter"), ("litre", "liter"), ("tyre", "tire"),
             ("isation", "ization"), ("isati", "izati"), ("ise", "ize"),
             ("colour", "color"), ("authorise", "authorize"),
             ("kerb", "curb"), ("gauge", "gage")]


def _despell(w: str) -> str:
    """One spelling for both sides. en-US out of the model, en-GB in the samples."""
    for gb, us in _SPELLING:
        if gb in w:
            w = w.replace(gb, us)
    return w


def _numbers(toks: list[str]) -> list[str]:
    """Spoken numbers to digits, so '1.8' and 'one point eight' compare equal.

    Three shapes, in this order of precedence:
      one point eight        -> 1.8     a measurement
      zero one seven one     -> 0171    a code or a repair order, read out
      three                  -> 3       a bare figure
    """
    out: list[str] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        # decimal: <digit-word|teen> point <digit-word|digit>...
        if (t in _DIGIT or t in _TEENS) and i + 2 < len(toks) and toks[i + 1] == "point":
            frac = []
            j = i + 2
            while j < len(toks) and (toks[j] in _DIGIT or toks[j].isdigit()):
                frac.append(_DIGIT.get(toks[j], toks[j]))
                j += 1
            if frac:
                whole = _DIGIT.get(t) or _TEENS[t]
                out.append(f"{whole}.{''.join(frac)}")
                i = j
                continue
        # a run of two or more digit-words is one number read out loud
        if t in _DIGIT:
            j = i
            run = []
            while j < len(toks) and toks[j] in _DIGIT:
                run.append(_DIGIT[toks[j]])
                j += 1
            out.append("".join(run) if len(run) > 1 else run[0])
            i = j
            continue
        out.append(_TEENS.get(t, t))
        i += 1
    return out


def _words(s: str) -> list[str]:
    """Comparable words: lowercase, no punctuation, one spelling, numbers as digits."""
    s = s.lower().replace("-", " ")
    toks = re.findall(r"[a-z]+|\d+(?:\.\d+)?", s)
    return _numbers([_despell(t) for t in toks])


def wer(ref: list[str], hyp: list[str]) -> tuple[float, int, int, int]:
    """Word error rate by Levenshtein. Returns (rate, substitutions, deletions, insertions)."""
    n, m = len(ref), len(hyp)
    if n == 0:
        return (0.0 if m == 0 else 1.0), 0, 0, m
    # (cost, subs, dels, ins) per cell; one row at a time.
    prev = [(j, 0, 0, j) for j in range(m + 1)]
    for i in range(1, n + 1):
        cur = [(i, 0, i, 0)] + [None] * m
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                cur[j] = prev[j - 1]
                continue
            c_sub = (prev[j - 1][0] + 1, prev[j - 1][1] + 1, prev[j - 1][2], prev[j - 1][3])
            c_del = (prev[j][0] + 1, prev[j][1], prev[j][2] + 1, prev[j][3])
            c_ins = (cur[j - 1][0] + 1, cur[j - 1][1], cur[j - 1][2], cur[j - 1][3] + 1)
            cur[j] = min(c_sub, c_del, c_ins, key=lambda t: t[0])
        prev = cur
    cost, subs, dels, ins = prev[m]
    return cost / n, subs, dels, ins


_ONES = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
         6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
         11: "eleven", 12: "twelve"}


def spoken_forms(tok: str) -> set[str]:
    """Every way a model might render one figure. '1.8' -> {'1.8', 'one point eight'}."""
    forms = {tok}
    if "." in tok:
        whole, frac = tok.split(".", 1)
        w = _ONES.get(int(whole)) if whole.isdigit() and int(whole) < 13 else None
        f = " ".join(_ONES[int(d)] for d in frac if d.isdigit())
        if w and f:
            forms.add(f"{w} point {f}")
        forms.add(tok.rstrip("0").rstrip("."))          # 3.0 -> 3
    elif tok.isdigit():
        if int(tok) < 13:
            forms.add(_ONES[int(tok)])
        forms.add(f"{tok}.0")
        if len(tok) > 1:                                # 2024 -> two zero two four
            forms.add(" ".join(_ONES[int(d)] for d in tok))
    return forms


def figures(s: str) -> list[str]:
    """Every number in a string, in order, deduplicated.

    Canonicalises FIRST. The samples are dictated the way a technician speaks -
    "one point eight millimetres" - so a raw digit scan finds nothing to check and
    reports a clean sweep on a transcript that lost every measurement. That is the
    exact failure this file was written to catch, and the first version of it had
    the bug itself.
    """
    seen, out = set(), []
    for tok in _words(s):
        if re.fullmatch(r"\d+(?:\.\d+)?", tok) and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def figure_survived(fig: str, hyp: str) -> bool:
    """Did this figure come through, written any way a model might write it?"""
    h = " " + " ".join(_words(hyp)) + " "
    return any(f" {' '.join(_words(f))} " in h for f in spoken_forms(fig))


# ------------------------------------------------------------------ audio facts

def describe(path: str) -> str:
    """Rate, channels, duration and level - the four things that make ASR return nothing."""
    try:
        sys.path.insert(0, "scripts")
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_ms", os.path.join("scripts", "make_speech.py"))
        ms = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ms)
        a, rate = ms.read_wav(path)
        if not a:
            return f"{rate} Hz, 0 samples - the file is empty"
        peak = max(abs(v) for v in a) / 32767
        rms = (sum(v * v for v in a) / len(a)) ** 0.5 / 32767
        warn = ""
        if peak < 0.02:
            warn = "  <-- effectively silent, nothing to transcribe"
        elif rate not in (8000, 16000, 22050, 44100, 48000):
            warn = f"  <-- unusual rate; Riva expects 16000"
        return (f"{rate} Hz mono, {len(a) / rate:.1f}s, "
                f"peak {peak:.0%}, rms {rms:.1%}{warn}")
    except Exception as e:
        return f"could not read as 16-bit WAV ({type(e).__name__}: {e})"


def main() -> int:
    ap = argparse.ArgumentParser(description="Grade the speech-to-text leg.")
    ap.add_argument("--wav", help="audio to transcribe")
    ap.add_argument("--sample", type=int,
                    help="synthesise spoken update N and grade against its text")
    ap.add_argument("--expect", help="what the audio says, to score against")
    ap.add_argument("--text", help="words to synthesise, instead of a sample")
    ap.add_argument("--keep", action="store_true", help="keep the generated wav")
    args = ap.parse_args()

    if not (os.path.exists("pyproject.toml") and os.path.isdir("app/pipeline")):
        print("Run from the project root:\n"
              "  cd ~/automotive-service-agent && "
              ".venv/bin/python scripts/test_asr.py --sample 1")
        return 2
    if not (args.wav or args.sample or args.text):
        ap.error("give --wav, or --sample N, or --text to synthesise")

    from app.pipeline.asr import transcribe, health

    h = health()
    print(f"-- configuration {'-' * 58}")
    for k, v in h.items():
        print(f"  {k:24s} {v}")
    if not h["ready"]:
        print(f"\nNOT READY. {h['mode']} via {h['endpoint']}.")
        if not h["riva_client_installed"] and h["mode"] == "grpc":
            print("  uv pip install --python .venv nvidia-riva-client")
        return 2

    # ------------------------------------------------------------------ audio in
    wav, expect, made = args.wav, args.expect, None
    if not wav:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_ms", os.path.join("scripts", "make_speech.py"))
        ms = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ms)
        if args.sample:
            expect, _ = ms.sample_text(args.sample)
        else:
            expect = args.text
        import tempfile
        made = wav = os.path.join(tempfile.mkdtemp(), "spoken.wav")
        raw = os.path.join(tempfile.mkdtemp(), "raw.wav")
        engine = ms.synthesise(expect, raw, None, None)
        if not engine:
            print(ms.NO_TTS)
            return 2
        a, rate = ms.read_wav(raw)
        ms.write_wav(wav, ms.normalise(ms.resample(a, rate, ms.TARGET_RATE)))
        print(f"\n-- synthesised {'-' * 60}")
        print(f"  {engine}: {len(expect)} characters of speech")

    print(f"\n-- audio {'-' * 66}")
    print(f"  {wav}")
    print(f"  {describe(wav)}")

    # ------------------------------------------------------------------ the call
    t0 = time.time()
    t = transcribe(wav)
    elapsed = time.time() - t0
    print(f"\n-- transcription {'-' * 58}")
    print(f"  {elapsed:.1f}s wall, source {t.source}, confidence {t.confidence}")

    if t.error:
        print(f"\n  FAILED: {t.error}")
        low = t.error.lower()
        if "unauthenticated" in low or "401" in low:
            print("\n  The key was rejected. Check NVIDIA_API_KEY in .env.")
        elif "not_found" in low or "not found" in low:
            print("\n  The function id was rejected. The model may have been "
                  "republished under a new id on build.nvidia.com.")
        elif "type=offline" in low or "unavailable model" in low:
            print("\n  The service was REACHED and refused the parameters: it "
                  "does not\n  serve offline/batch recognition for this model. "
                  "Streaming works -\n  app/pipeline/asr.py falls back to it, so "
                  "seeing this means the\n  fallback itself failed.")
            print("\n  Note: the `language_code=en` in that message is not the "
                  "problem.\n  The service normalises to the base language; "
                  "en-GB returns the same.")
        elif "invalid_argument" in low:
            print("\n  The service was reached and rejected the request. This is "
                  "an\n  argument error, not a connection problem - read the "
                  "parameters it\n  echoed back above.")
        elif "unavailable" in low or "deadline" in low:
            # Ordering matters: the server says "Unavailable MODEL requested" for
            # a perfectly delivered request, and matching "unavailable" first made
            # this print "never reached the service" about a service that answered.
            print("\n  Never reached the service. Check egress to "
                  f"{h['endpoint']} on 443.")
        elif "no words" in low:
            print("\n  The call SUCCEEDED - the model returned no words for this "
                  "audio. See the audio line above: silence, or the wrong rate, "
                  "or genuinely no speech in it.")
        return 2

    print(f"\n  {t.text}")

    if not expect:
        print("\nTranscribed. No --expect given, so nothing was graded - read it "
              "yourself, or re-run with --sample N to score it.")
        return 0

    # ------------------------------------------------------------------ grading
    ref, hyp = _words(expect), _words(t.text)
    rate, subs, dels, ins = wer(ref, hyp)
    print(f"\n-- accuracy {'-' * 63}")
    print(f"  word error rate  {rate:.1%}   "
          f"({subs} substituted, {dels} dropped, {ins} inserted, "
          f"{len(ref)} reference words)")

    figs = figures(expect)
    missing = [f for f in figs if not figure_survived(f, t.text)]
    kept = len(figs) - len(missing)
    print(f"  figures          {kept}/{len(figs)} survived"
          + (f"   MISSING: {', '.join(missing)}" if missing else ""))

    bad = 0
    if rate > WER_WARN:
        bad = 1
        print(f"\n  POOR: {rate:.0%} of words wrong, above the {WER_WARN:.0%} "
              f"limit. Check the audio level and rate above first - a quiet or "
              f"resampled file scores like a bad model.")
    if missing:
        bad = 1
        print(f"\n  FIGURES LOST: {', '.join(missing)}. This is the failure that "
              f"matters: the prose can be rough and the update still lands, but a "
              f"dropped measurement is a silently wrong record.")
    if not bad:
        print(f"\n  GOOD: words and every figure came through.")
        print(f"\nNow put it through the whole update pipeline:")
        print(f"  .venv/bin/python scripts/test_voice_update.py --audio {wav}")

    if made and not args.keep:
        print(f"\n(generated audio left at {made})" if bad
              else f"\n(generated audio at {made})")
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
