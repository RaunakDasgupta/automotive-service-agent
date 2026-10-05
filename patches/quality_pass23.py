#!/usr/bin/env python3
"""Twenty-third pass: the ASR could not be tested, and an empty result said nothing.

Run from the project root:   .venv/bin/python quality_pass23.py

Pass 22 fixed the endpoint. It did not give anyone a way to find out whether
transcription WORKS, and its own check quietly proved that:

    note    riva client present - transcript: '' error=None

That line is what a 440 Hz sine tone transcribes to. It is also exactly what a
completely broken ASR returns. The check could not fail and could not pass, and
printing it under "riva client present" made it read like success.

1. AN EMPTY TRANSCRIPT NOW CARRIES ITS REASON.

   `_transcribe_grpc` returned `Transcript("", ..., error=None)` when the service
   came back with no alternatives. `ok` is False and `error` is None, so:

       the UI          "Transcription failed: None"
       test_voice_update  "transcription failed: None"
       the self-test   "transcript: '' error=None"   <- counted as fine

   A successful call that returns no words has a short list of causes, and every
   one of them can be measured from the file: too short, silent, an odd sample
   rate, not a WAV, or genuinely no speech. `_no_words()` measures and says which.
   The connection working and the model hearing words are separate claims; only
   the second was ever in doubt, and it was the one nothing reported on.

2. THERE IS NOW REAL SPEECH TO TEST WITH.

   The box has no microphone, so the only audio the tests could make was a tone.
   `scripts/make_speech.py` shells out to whatever text-to-speech the machine
   already has - macOS `say`, or espeak-ng / pico2wave / piper on Linux - and
   writes a 16 kHz mono WAV. No dependency is added and nothing is downloaded;
   the resampler and the normaliser are fifteen lines of `wave` and `array`,
   because a check that needs ffmpeg installed is a check that fails at demo time.

   Synthetic speech flatters the model. It still exercises every link that was
   unproven - encode, authenticate, transport, decode, return words - and it puts
   real figures through, which is what an update is made of.

3. THE FIGURES ARE GRADED SEPARATELY FROM THE WORDS.

   `scripts/test_asr.py` speaks a sample update, transcribes it, and scores word
   error rate AND every number on its own. The second is the one that matters,
   and this is why:

       transcript                        WER     figures
       perfect                           0.0%      5/5
       one point eight -> one point four  1.2%      4/5  MISSING 1.8

   A measurement corrupted from 1.8 to 1.4 is 1.2% word error - invisible - and a
   silently wrong service record. Word error rate cannot see it. So the figure
   check is the gate, and WER is context.

   Two things had to be canonicalised before any of it meant anything. A model
   that says "1.8" has not erred when the script said "one point eight", and one
   writing US English has not erred against a British sample: naively compared, a
   PERFECT transcript scored 46% word error. Both sides now normalise numbers to
   digits and spelling to one form. The first version of the figure check had the
   same bug in reverse - it scanned the reference for digits, found only the ones
   literally written as digits, and reported a clean sweep on a transcript that
   had dropped every measurement.
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
                 "      Run passes 1-22 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


def write(rel, body, label):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        if p.read_text() == body:
            CHANGES.append(f"  skip  {label} (already present)")
        else:
            p.write_text(body)
            CHANGES.append(f"  ok    {label} (replaced)")
        return
    p.write_text(body)
    CHANGES.append(f"  ok    {label}")


# ==================== 1. an empty transcript carries its reason
edit('app/pipeline/asr.py',
     'from __future__ import annotations\nimport os\nimport wave\nfrom dataclasses import dataclass',
     'from __future__ import annotations\nimport array\nimport os\nimport sys as _sys\nimport wave\nfrom dataclasses import dataclass',
     'asr.py  array and sys, for measuring the audio',
     skip_if='import sys as _sys')

edit('app/pipeline/asr.py',
     'def _duration(path: str) -> float | None:\n    return _wav_specs(path)[2]',
     'def _duration(path: str) -> float | None:\n    return _wav_specs(path)[2]\n\n\n# Rates a speech service will accept without comment. 16000 is what Riva wants\n# and what the NIMs serve; the rest are what recorders and browsers produce.\n_SANE_RATES = (8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000)\n\n\ndef _level(path: str) -> float | None:\n    """Peak amplitude as a fraction of full scale. None if not readable as 16-bit WAV."""\n    try:\n        with wave.open(path, "rb") as w:\n            if w.getsampwidth() != 2:\n                return None\n            a = array.array("h")\n            a.frombytes(w.readframes(min(w.getnframes(), 16000 * 60)))\n        if _sys.byteorder == "big":\n            a.byteswap()\n        return (max(abs(v) for v in a) / 32767) if a else 0.0\n    except Exception:\n        return None\n\n\ndef _no_words(path: str) -> str:\n    """Why a SUCCESSFUL call came back with nothing. Measured, not guessed.\n\n    An empty transcript used to be returned with `error=None`, which made `ok`\n    False and left every caller with nothing to say: the UI printed\n    "Transcription failed: None" and the self-test printed "transcript: \'\'\n    error=None" and counted it a pass. The connection working and the model\n    hearing words are two different claims, and only the second one was ever in\n    doubt. So when the words are missing, say which of the few possible reasons\n    it is - all of them are things the file itself can be asked.\n    """\n    rate, channels, dur = _wav_specs(path)\n    peak = _level(path)\n    facts = []\n    if dur is not None:\n        facts.append(f"{dur:.1f}s")\n    if rate:\n        facts.append(f"{rate} Hz")\n    if channels:\n        facts.append(f"{channels} channel{\'s\' if channels > 1 else \'\'}")\n    if peak is not None:\n        facts.append(f"peak {peak:.0%} of full scale")\n    detail = ", ".join(facts) or "not readable as a WAV"\n\n    if dur is not None and dur < 0.35:\n        why = "too short to contain a word"\n    elif peak is not None and peak < 0.02:\n        why = "effectively silent - check the microphone, or the file"\n    elif rate and rate not in _SANE_RATES:\n        why = f"{rate} Hz is an unusual sample rate; 16000 is what the model wants"\n    elif dur is None:\n        why = ("not a 16-bit WAV, so the encoding sent with it may have been wrong")\n    else:\n        why = (f"no recognisable speech in it - a tone, noise, or speech in a "\n               f"language other than {ASR_LANGUAGE}")\n    return (f"the service returned no words ({detail}): {why}. "\n            f"The connection and the key were fine.")',
     'asr.py  _no_words() says why a successful call returned nothing',
     skip_if='def _no_words')

edit('app/pipeline/asr.py',
     '        return Transcript(" ".join(p.strip() for p in parts).strip(),\n                          confidence, dur, "grpc")',
     '        text = " ".join(p.strip() for p in parts).strip()\n        if not text:\n            return Transcript("", confidence, dur, "grpc",\n                              error=_no_words(audio_path))\n        return Transcript(text, confidence, dur, "grpc")',
     'asr.py  gRPC: no words is an error, not a silent empty string',
     skip_if='dur, "grpc",')

edit('app/pipeline/asr.py',
     '        return Transcript(text, data.get("confidence"), dur, "rest")',
     '        if not text:\n            return Transcript("", data.get("confidence"), dur, "rest",\n                              error=_no_words(audio_path))\n        return Transcript(text, data.get("confidence"), dur, "rest")',
     'asr.py  REST: the same, for a local NIM',
     skip_if='dur, "rest",')


# ==================== 2. real speech to test with
write('scripts/make_speech.py',
      '#!/usr/bin/env python3\n"""Turn text into a 16 kHz mono WAV, with whatever text-to-speech this machine has.\n\n    .venv/bin/python scripts/make_speech.py --sample 1\n    .venv/bin/python scripts/make_speech.py --text "Front pads at 1.8 millimetres"\n    .venv/bin/python scripts/make_speech.py --sample 1 -o /tmp/update.wav\n\nWHY THIS EXISTS\n\nThe ASR leg could not be tested. This box has no microphone, and the only audio\nthe checks could manufacture was a 440 Hz sine tone - which a speech model\ncorrectly transcribes as nothing at all. An empty transcript from a tone is\nindistinguishable from an ASR that is broken end to end, so the check passed\neither way and proved neither. Real words are the entire point.\n\nSynthetic speech is not a technician leaning over a wing in a noisy workshop, and\nit will flatter the model. What it does do is exercise every link that was\nunproven - encode, authenticate, transport, decode, and return words - and it\nputs real figures through, so "1.8 millimetres" either survives or it does not.\n\nNothing is downloaded and no Python dependency is added. It shells out to a TTS\nthat is already on the machine, in this order:\n\n    say         macOS, always present\n    espeak-ng   Linux:  sudo apt-get install -y espeak-ng\n    espeak      older Linux\n    pico2wave   Linux:  sudo apt-get install -y libttspico-utils\n    piper       only if PIPER_MODEL points at a .onnx voice\n\nIf none is installed, there is a second route that needs nothing on the box: run\nthis on a Mac, then copy the file over. The failure message prints it.\n"""\nfrom __future__ import annotations\nimport argparse, array, os, shutil, subprocess, sys, tempfile, wave\n\nsys.path.insert(0, ".")\n\nTARGET_RATE = 16000          # what Riva wants, and what the NIMs serve\nTARGET_PEAK = 0.7            # about -3 dBFS: loud enough, no clipping\nMAX_GAIN = 8.0               # never amplify near-silence into hiss\n\n\n# ------------------------------------------------------------------ audio, by hand\n# Deliberately no numpy, no ffmpeg, no sox: a 15-line resampler has no install\n# story, and this has to work on a fresh box at demo time.\n\ndef read_wav(path: str) -> tuple[array.array, int]:\n    """16-bit WAV -> (mono samples, rate). Downmixes; raises on other widths."""\n    with wave.open(path, "rb") as w:\n        ch, sw, rate, n = (w.getnchannels(), w.getsampwidth(),\n                           w.getframerate(), w.getnframes())\n        raw = w.readframes(n)\n    if sw != 2:\n        raise ValueError(f"{path} is {sw * 8}-bit; this expects 16-bit PCM")\n    a = array.array("h")\n    a.frombytes(raw)\n    if sys.byteorder == "big":       # WAV is little-endian\n        a.byteswap()\n    if ch > 1:\n        a = array.array("h", [sum(a[i * ch:(i + 1) * ch]) // ch\n                              for i in range(len(a) // ch)])\n    return a, rate\n\n\ndef resample(a: array.array, src: int, dst: int) -> array.array:\n    """Linear interpolation. Good enough for speech that a model has to read."""\n    if src == dst or not a:\n        return a\n    ratio = src / dst\n    out = array.array("h")\n    n = int(len(a) / ratio)\n    last = len(a) - 1\n    for i in range(n):\n        x = i * ratio\n        j = int(x)\n        if j >= last:\n            out.append(a[last])\n            continue\n        v = a[j] + (a[j + 1] - a[j]) * (x - j)\n        out.append(int(max(-32768, min(32767, v))))\n    return out\n\n\ndef normalise(a: array.array, target: float = TARGET_PEAK) -> array.array:\n    """Bring the peak up to `target` of full scale. A quiet file transcribes badly."""\n    peak = max((abs(v) for v in a), default=0)\n    if peak == 0:\n        return a\n    gain = min((target * 32767) / peak, MAX_GAIN)\n    if 0.98 < gain < 1.02:\n        return a\n    return array.array("h", [int(max(-32768, min(32767, v * gain))) for v in a])\n\n\ndef write_wav(path: str, a: array.array, rate: int = TARGET_RATE) -> None:\n    b = array.array("h", a)\n    if sys.byteorder == "big":\n        b.byteswap()\n    with wave.open(path, "wb") as w:\n        w.setnchannels(1)\n        w.setsampwidth(2)\n        w.setframerate(rate)\n        w.writeframes(b.tobytes())\n\n\n# ------------------------------------------------------------------ the engines\n\ndef _run(cmd: list[str]) -> bool:\n    try:\n        r = subprocess.run(cmd, capture_output=True, timeout=180)\n        return r.returncode == 0\n    except (OSError, subprocess.SubprocessError):\n        return False\n\n\ndef synthesise(text: str, out: str, voice: str | None, wpm: int | None) -> str:\n    """Write raw TTS audio to `out`. Returns the engine name, or "" if none worked."""\n    if shutil.which("say"):                       # macOS: asks for 16k directly\n        cmd = ["say", "--file-format=WAVE", f"--data-format=LEI16@{TARGET_RATE}",\n               "-r", str(wpm or 175), "-o", out]\n        if voice:\n            cmd += ["-v", voice]\n        if _run(cmd + [text]):\n            return "say"\n    for exe in ("espeak-ng", "espeak"):\n        if shutil.which(exe):\n            cmd = [exe, "-w", out, "-s", str(wpm or 150)]\n            if voice:\n                cmd += ["-v", voice]\n            if _run(cmd + [text]):\n                return exe\n    if shutil.which("pico2wave"):\n        if _run(["pico2wave", "-l", voice or "en-GB", "-w", out, text]):\n            return "pico2wave"\n    model = os.environ.get("PIPER_MODEL", "")\n    if shutil.which("piper") and model:\n        try:\n            with open(out, "wb") as fh:\n                p = subprocess.run(["piper", "--model", model, "--output_file", out],\n                                   input=text.encode(), capture_output=True,\n                                   timeout=180)\n            if p.returncode == 0 and os.path.getsize(out):\n                return "piper"\n        except (OSError, subprocess.SubprocessError):\n            pass\n    return ""\n\n\nNO_TTS = """No text-to-speech on this machine, so there is no way to make the audio here.\n\nInstall one (a few seconds, no GPU):\n\n    sudo apt-get update && sudo apt-get install -y espeak-ng\n\nOr make the file on your Mac, which already has `say`, and copy it over:\n\n    say --file-format=WAVE --data-format=LEI16@16000 -o update.wav \\\\\n        "Update for repair order RO-2024-0142. Front pad thickness at one point \\\\\n         eight millimetres against a three millimetre minimum."\n    scp update.wav capstone-poc:~/automotive-service-agent/update.wav\n\nThen:\n\n    .venv/bin/python scripts/test_asr.py --wav update.wav\n"""\n\n\n# ------------------------------------------------------------------ samples\n\ndef sample_text(n: int) -> tuple[str, str | None]:\n    """The nth spoken update from test_voice_update.py, with a real RO in it."""\n    import importlib.util\n    spec = importlib.util.spec_from_file_location(\n        "_tvu", os.path.join("scripts", "test_voice_update.py"))\n    m = importlib.util.module_from_spec(spec)\n    spec.loader.exec_module(m)\n    if not 1 <= n <= len(m.SAMPLES):\n        raise SystemExit(f"--sample must be 1-{len(m.SAMPLES)}")\n    s = m.SAMPLES[n - 1]\n    ron = None\n    try:\n        from app.state import db as dbm\n        ron = m._pick_ro(dbm.connect(), s.get("needs", "open"))\n    except Exception:\n        pass\n    text = s["text"].replace("{RO}", ron or "RO-2024-0142")\n    return text, ron\n\n\ndef main() -> int:\n    ap = argparse.ArgumentParser(\n        description="Make a 16 kHz mono WAV of spoken text, for testing the ASR leg.")\n    g = ap.add_mutually_exclusive_group(required=True)\n    g.add_argument("--sample", type=int, help="a spoken update from test_voice_update.py")\n    g.add_argument("--text", help="your own words")\n    ap.add_argument("-o", "--out", default="update.wav")\n    ap.add_argument("--voice", help="an engine voice name, e.g. Daniel or en-gb")\n    ap.add_argument("--wpm", type=int, help="speaking rate (say: 175, espeak: 150)")\n    args = ap.parse_args()\n\n    if not (os.path.exists("pyproject.toml") and os.path.isdir("app/pipeline")):\n        print("Run from the project root:\\n"\n              "  cd ~/automotive-service-agent && "\n              ".venv/bin/python scripts/make_speech.py --sample 1")\n        return 2\n\n    ron = None\n    if args.sample:\n        text, ron = sample_text(args.sample)\n    else:\n        text = args.text\n\n    raw = os.path.join(tempfile.mkdtemp(), "raw.wav")\n    engine = synthesise(text, raw, args.voice, args.wpm)\n    if not engine:\n        print(NO_TTS)\n        return 2\n\n    a, rate = read_wav(raw)\n    a = normalise(resample(a, rate, TARGET_RATE))\n    write_wav(args.out, a)\n    secs = len(a) / TARGET_RATE\n    peak = max((abs(v) for v in a), default=0) / 32767\n\n    print(f"-- spoken {\'-\' * 65}")\n    print("  " + text[:300] + ("..." if len(text) > 300 else ""))\n    print(f"\\n-- audio {\'-\' * 66}")\n    print(f"  {args.out}")\n    print(f"  {engine}, {rate} Hz -> {TARGET_RATE} Hz mono, "\n          f"{secs:.1f}s, peak {peak:.0%} of full scale")\n    print(f"\\nNext, transcribe it and grade what comes back:")\n    if args.sample:\n        print(f"  .venv/bin/python scripts/test_asr.py --sample {args.sample}")\n    else:\n        print(f"  .venv/bin/python scripts/test_asr.py --wav {args.out} "\n              f"--expect {text!r}")\n    print(f"\\nOr put it through the whole update pipeline:")\n    print(f"  .venv/bin/python scripts/test_voice_update.py --audio {args.out}"\n          + (f" --ro {ron}" if ron else ""))\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
      'scripts/make_speech.py  text to a 16 kHz mono WAV, with local TTS')


# ==================== 3. grade the words, and grade the figures
write('scripts/test_asr.py',
      '#!/usr/bin/env python3\n"""Does speech to text actually work? Real words in, graded transcript out.\n\n    .venv/bin/python scripts/test_asr.py --sample 1      # synthesise and grade\n    .venv/bin/python scripts/test_asr.py --wav u.wav --expect "what was said"\n    .venv/bin/python scripts/test_asr.py --wav u.wav      # no grade, just read it\n\nExit codes:  0 transcribed and accurate | 1 transcribed but poor | 2 not working\n\nWHAT WAS WRONG WITH THE OLD CHECK\n\nIt transcribed a 440 Hz sine tone and printed the result. A tone contains no\nwords, so an empty transcript was the correct answer - and also exactly what a\ncompletely broken ASR returns. The check could not fail, and it could not pass.\nIt measured the transport and nothing else, while reading as though it had\nmeasured transcription.\n\nThis one speaks a real update, with real figures, and grades three things\nseparately, because they fail for different reasons and need different fixes:\n\n  READINESS   is the client installed, is a route configured\n  TRANSPORT   did the call reach NVCF and come back without a gRPC status\n  ACCURACY    did the words come back, and did the FIGURES survive\n\nThe figures matter more than the words. "Front pads at 1.8mm against a 3mm\nminimum" is the whole content of that update; a transcript that renders the prose\nbeautifully and turns 1.8 into 1.4 is worse than useless, because it is wrong in\na way nobody will notice. So the word error rate is reported, and then every\nnumber is checked for on its own.\n"""\nfrom __future__ import annotations\nimport argparse, os, re, sys, time\n\nsys.path.insert(0, ".")\n\nWER_WARN = 0.35      # synthetic speech through a good model should beat this\n\n\n# ------------------------------------------------------------------ scoring\n\n# A model that says "1.8" has not made an error when the script said "one point\n# eight", and one that writes US English has not made an error when the sample was\n# written in British English. Both count as errors to a naive word comparison, and\n# the first alone put a PERFECT transcript at 46% - a check that reports failure on\n# correct output teaches people to ignore it. So both sides are canonicalised to\n# one spelling and one way of writing a number before anything is counted.\n\n_DIGIT = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3",\n          "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",\n          "nine": "9"}\n_TEENS = {"ten": "10", "eleven": "11", "twelve": "12"}\n_SPELLING = [("metre", "meter"), ("litre", "liter"), ("tyre", "tire"),\n             ("isation", "ization"), ("isati", "izati"), ("ise", "ize"),\n             ("colour", "color"), ("authorise", "authorize"),\n             ("kerb", "curb"), ("gauge", "gage")]\n\n\ndef _despell(w: str) -> str:\n    """One spelling for both sides. en-US out of the model, en-GB in the samples."""\n    for gb, us in _SPELLING:\n        if gb in w:\n            w = w.replace(gb, us)\n    return w\n\n\ndef _numbers(toks: list[str]) -> list[str]:\n    """Spoken numbers to digits, so \'1.8\' and \'one point eight\' compare equal.\n\n    Three shapes, in this order of precedence:\n      one point eight        -> 1.8     a measurement\n      zero one seven one     -> 0171    a code or a repair order, read out\n      three                  -> 3       a bare figure\n    """\n    out: list[str] = []\n    i = 0\n    while i < len(toks):\n        t = toks[i]\n        # decimal: <digit-word|teen> point <digit-word|digit>...\n        if (t in _DIGIT or t in _TEENS) and i + 2 < len(toks) and toks[i + 1] == "point":\n            frac = []\n            j = i + 2\n            while j < len(toks) and (toks[j] in _DIGIT or toks[j].isdigit()):\n                frac.append(_DIGIT.get(toks[j], toks[j]))\n                j += 1\n            if frac:\n                whole = _DIGIT.get(t) or _TEENS[t]\n                out.append(f"{whole}.{\'\'.join(frac)}")\n                i = j\n                continue\n        # a run of two or more digit-words is one number read out loud\n        if t in _DIGIT:\n            j = i\n            run = []\n            while j < len(toks) and toks[j] in _DIGIT:\n                run.append(_DIGIT[toks[j]])\n                j += 1\n            out.append("".join(run) if len(run) > 1 else run[0])\n            i = j\n            continue\n        out.append(_TEENS.get(t, t))\n        i += 1\n    return out\n\n\ndef _words(s: str) -> list[str]:\n    """Comparable words: lowercase, no punctuation, one spelling, numbers as digits."""\n    s = s.lower().replace("-", " ")\n    toks = re.findall(r"[a-z]+|\\d+(?:\\.\\d+)?", s)\n    return _numbers([_despell(t) for t in toks])\n\n\ndef wer(ref: list[str], hyp: list[str]) -> tuple[float, int, int, int]:\n    """Word error rate by Levenshtein. Returns (rate, substitutions, deletions, insertions)."""\n    n, m = len(ref), len(hyp)\n    if n == 0:\n        return (0.0 if m == 0 else 1.0), 0, 0, m\n    # (cost, subs, dels, ins) per cell; one row at a time.\n    prev = [(j, 0, 0, j) for j in range(m + 1)]\n    for i in range(1, n + 1):\n        cur = [(i, 0, i, 0)] + [None] * m\n        for j in range(1, m + 1):\n            if ref[i - 1] == hyp[j - 1]:\n                cur[j] = prev[j - 1]\n                continue\n            c_sub = (prev[j - 1][0] + 1, prev[j - 1][1] + 1, prev[j - 1][2], prev[j - 1][3])\n            c_del = (prev[j][0] + 1, prev[j][1], prev[j][2] + 1, prev[j][3])\n            c_ins = (cur[j - 1][0] + 1, cur[j - 1][1], cur[j - 1][2], cur[j - 1][3] + 1)\n            cur[j] = min(c_sub, c_del, c_ins, key=lambda t: t[0])\n        prev = cur\n    cost, subs, dels, ins = prev[m]\n    return cost / n, subs, dels, ins\n\n\n_ONES = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",\n         6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",\n         11: "eleven", 12: "twelve"}\n\n\ndef spoken_forms(tok: str) -> set[str]:\n    """Every way a model might render one figure. \'1.8\' -> {\'1.8\', \'one point eight\'}."""\n    forms = {tok}\n    if "." in tok:\n        whole, frac = tok.split(".", 1)\n        w = _ONES.get(int(whole)) if whole.isdigit() and int(whole) < 13 else None\n        f = " ".join(_ONES[int(d)] for d in frac if d.isdigit())\n        if w and f:\n            forms.add(f"{w} point {f}")\n        forms.add(tok.rstrip("0").rstrip("."))          # 3.0 -> 3\n    elif tok.isdigit():\n        if int(tok) < 13:\n            forms.add(_ONES[int(tok)])\n        forms.add(f"{tok}.0")\n        if len(tok) > 1:                                # 2024 -> two zero two four\n            forms.add(" ".join(_ONES[int(d)] for d in tok))\n    return forms\n\n\ndef figures(s: str) -> list[str]:\n    """Every number in a string, in order, deduplicated.\n\n    Canonicalises FIRST. The samples are dictated the way a technician speaks -\n    "one point eight millimetres" - so a raw digit scan finds nothing to check and\n    reports a clean sweep on a transcript that lost every measurement. That is the\n    exact failure this file was written to catch, and the first version of it had\n    the bug itself.\n    """\n    seen, out = set(), []\n    for tok in _words(s):\n        if re.fullmatch(r"\\d+(?:\\.\\d+)?", tok) and tok not in seen:\n            seen.add(tok)\n            out.append(tok)\n    return out\n\n\ndef figure_survived(fig: str, hyp: str) -> bool:\n    """Did this figure come through, written any way a model might write it?"""\n    h = " " + " ".join(_words(hyp)) + " "\n    return any(f" {\' \'.join(_words(f))} " in h for f in spoken_forms(fig))\n\n\n# ------------------------------------------------------------------ audio facts\n\ndef describe(path: str) -> str:\n    """Rate, channels, duration and level - the four things that make ASR return nothing."""\n    try:\n        sys.path.insert(0, "scripts")\n        import importlib.util\n        spec = importlib.util.spec_from_file_location(\n            "_ms", os.path.join("scripts", "make_speech.py"))\n        ms = importlib.util.module_from_spec(spec)\n        spec.loader.exec_module(ms)\n        a, rate = ms.read_wav(path)\n        if not a:\n            return f"{rate} Hz, 0 samples - the file is empty"\n        peak = max(abs(v) for v in a) / 32767\n        rms = (sum(v * v for v in a) / len(a)) ** 0.5 / 32767\n        warn = ""\n        if peak < 0.02:\n            warn = "  <-- effectively silent, nothing to transcribe"\n        elif rate not in (8000, 16000, 22050, 44100, 48000):\n            warn = f"  <-- unusual rate; Riva expects 16000"\n        return (f"{rate} Hz mono, {len(a) / rate:.1f}s, "\n                f"peak {peak:.0%}, rms {rms:.1%}{warn}")\n    except Exception as e:\n        return f"could not read as 16-bit WAV ({type(e).__name__}: {e})"\n\n\ndef main() -> int:\n    ap = argparse.ArgumentParser(description="Grade the speech-to-text leg.")\n    ap.add_argument("--wav", help="audio to transcribe")\n    ap.add_argument("--sample", type=int,\n                    help="synthesise spoken update N and grade against its text")\n    ap.add_argument("--expect", help="what the audio says, to score against")\n    ap.add_argument("--text", help="words to synthesise, instead of a sample")\n    ap.add_argument("--keep", action="store_true", help="keep the generated wav")\n    args = ap.parse_args()\n\n    if not (os.path.exists("pyproject.toml") and os.path.isdir("app/pipeline")):\n        print("Run from the project root:\\n"\n              "  cd ~/automotive-service-agent && "\n              ".venv/bin/python scripts/test_asr.py --sample 1")\n        return 2\n    if not (args.wav or args.sample or args.text):\n        ap.error("give --wav, or --sample N, or --text to synthesise")\n\n    from app.pipeline.asr import transcribe, health\n\n    h = health()\n    print(f"-- configuration {\'-\' * 58}")\n    for k, v in h.items():\n        print(f"  {k:24s} {v}")\n    if not h["ready"]:\n        print(f"\\nNOT READY. {h[\'mode\']} via {h[\'endpoint\']}.")\n        if not h["riva_client_installed"] and h["mode"] == "grpc":\n            print("  uv pip install --python .venv nvidia-riva-client")\n        return 2\n\n    # ------------------------------------------------------------------ audio in\n    wav, expect, made = args.wav, args.expect, None\n    if not wav:\n        import importlib.util\n        spec = importlib.util.spec_from_file_location(\n            "_ms", os.path.join("scripts", "make_speech.py"))\n        ms = importlib.util.module_from_spec(spec)\n        spec.loader.exec_module(ms)\n        if args.sample:\n            expect, _ = ms.sample_text(args.sample)\n        else:\n            expect = args.text\n        import tempfile\n        made = wav = os.path.join(tempfile.mkdtemp(), "spoken.wav")\n        raw = os.path.join(tempfile.mkdtemp(), "raw.wav")\n        engine = ms.synthesise(expect, raw, None, None)\n        if not engine:\n            print(ms.NO_TTS)\n            return 2\n        a, rate = ms.read_wav(raw)\n        ms.write_wav(wav, ms.normalise(ms.resample(a, rate, ms.TARGET_RATE)))\n        print(f"\\n-- synthesised {\'-\' * 60}")\n        print(f"  {engine}: {len(expect)} characters of speech")\n\n    print(f"\\n-- audio {\'-\' * 66}")\n    print(f"  {wav}")\n    print(f"  {describe(wav)}")\n\n    # ------------------------------------------------------------------ the call\n    t0 = time.time()\n    t = transcribe(wav)\n    elapsed = time.time() - t0\n    print(f"\\n-- transcription {\'-\' * 58}")\n    print(f"  {elapsed:.1f}s wall, source {t.source}, confidence {t.confidence}")\n\n    if t.error:\n        print(f"\\n  FAILED: {t.error}")\n        low = t.error.lower()\n        if "unauthenticated" in low or "401" in low:\n            print("\\n  The key was rejected. Check NVIDIA_API_KEY in .env.")\n        elif "not_found" in low or "not found" in low:\n            print("\\n  The function id was rejected. The model may have been "\n                  "republished under a new id on build.nvidia.com.")\n        elif "unavailable" in low or "deadline" in low:\n            print("\\n  Never reached the service. Check egress to "\n                  f"{h[\'endpoint\']} on 443.")\n        elif "no words" in low:\n            print("\\n  The call SUCCEEDED - the model returned no words for this "\n                  "audio. See the audio line above: silence, or the wrong rate, "\n                  "or genuinely no speech in it.")\n        return 2\n\n    print(f"\\n  {t.text}")\n\n    if not expect:\n        print("\\nTranscribed. No --expect given, so nothing was graded - read it "\n              "yourself, or re-run with --sample N to score it.")\n        return 0\n\n    # ------------------------------------------------------------------ grading\n    ref, hyp = _words(expect), _words(t.text)\n    rate, subs, dels, ins = wer(ref, hyp)\n    print(f"\\n-- accuracy {\'-\' * 63}")\n    print(f"  word error rate  {rate:.1%}   "\n          f"({subs} substituted, {dels} dropped, {ins} inserted, "\n          f"{len(ref)} reference words)")\n\n    figs = figures(expect)\n    missing = [f for f in figs if not figure_survived(f, t.text)]\n    kept = len(figs) - len(missing)\n    print(f"  figures          {kept}/{len(figs)} survived"\n          + (f"   MISSING: {\', \'.join(missing)}" if missing else ""))\n\n    bad = 0\n    if rate > WER_WARN:\n        bad = 1\n        print(f"\\n  POOR: {rate:.0%} of words wrong, above the {WER_WARN:.0%} "\n              f"limit. Check the audio level and rate above first - a quiet or "\n              f"resampled file scores like a bad model.")\n    if missing:\n        bad = 1\n        print(f"\\n  FIGURES LOST: {\', \'.join(missing)}. This is the failure that "\n              f"matters: the prose can be rough and the update still lands, but a "\n              f"dropped measurement is a silently wrong record.")\n    if not bad:\n        print(f"\\n  GOOD: words and every figure came through.")\n        print(f"\\nNow put it through the whole update pipeline:")\n        print(f"  .venv/bin/python scripts/test_voice_update.py --audio {wav}")\n\n    if made and not args.keep:\n        print(f"\\n(generated audio left at {made})" if bad\n              else f"\\n(generated audio at {made})")\n    return bad\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
      'scripts/test_asr.py  transcribe real speech and score it')


# ==================== verify
print("Quality pass 23:")
for c in CHANGES:
    print(c)
for f in ("app/pipeline/asr.py", "scripts/make_speech.py", "scripts/test_asr.py"):
    ast.parse((ROOT / f).read_text())
print("\nasr.py, make_speech.py and test_asr.py parse cleanly.")

sys.path.insert(0, ".")
import importlib, importlib.util, os, wave, array, math, struct, tempfile, shutil
import app.pipeline.asr as A
importlib.reload(A)

def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

T = _load("scripts/test_asr.py", "_ta")
M = _load("scripts/make_speech.py", "_ms")
bad = 0
D = tempfile.mkdtemp()


def tone(name, secs=1.0, rate=16000, amp=3000, hz=440.0):
    p = os.path.join(D, name)
    n = int(secs * rate)
    with wave.open(p, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(amp * math.sin(2 * math.pi * hz * i / rate)))
            for i in range(n)))
    return p


# ---- an empty result now explains itself
print("\nwhy a successful call returned no words:")
for name, path, must in [
        ("a tone",        tone("tone.wav"),                          "no recognisable speech"),
        ("silence",       tone("silent.wav", amp=0),                 "effectively silent"),
        ("a 0.2s clip",   tone("short.wav", secs=0.2),               "too short"),
        ("7 kHz audio",   tone("odd.wav", rate=7000),                "unusual sample rate")]:
    msg = A._no_words(path)
    ok = must in msg
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}: {msg}")

ok = "not readable as a WAV" in A._no_words(os.path.join(D, "nope.wav"))
bad += (not ok)
print(f"  {'ok     ' if ok else 'WRONG  '} a missing file does not raise")

# the old shape is gone: no path returns empty text with no reason
src = (ROOT / "app/pipeline/asr.py").read_text()
for name, ok in [
        ("gRPC empty result carries an error", "error=_no_words(audio_path))" in src),
        ("both return sites are covered", src.count("_no_words(audio_path)") == 2)]:
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}")

# ---- the scorer: the cases that made the old check useless
print("\nscoring:")
REF = ("Update for repair order RO-2024-0142. Front pad thickness at one point "
       "eight millimetres against a three millimetre minimum. That took one point "
       "nine hours, and it needs customer authorisation.")
PERFECT_US = ("Update for repair order RO-2024-0142. Front pad thickness at 1.8 "
              "millimeters against a 3 millimeter minimum. That took 1.9 hours, "
              "and it needs customer authorization.")
CORRUPT = REF.replace("one point eight", "one point four")

r_us, *_ = T.wer(T._words(REF), T._words(PERFECT_US))
r_same, *_ = T.wer(T._words(REF), T._words(REF))
r_bad, *_ = T.wer(T._words(REF), T._words(CORRUPT))
figs = T.figures(REF)
miss_us = [f for f in figs if not T.figure_survived(f, PERFECT_US)]
miss_bad = [f for f in figs if not T.figure_survived(f, CORRUPT)]

for name, ok, detail in [
        ("digits vs spoken words score equal", r_us == 0.0, f"{r_us:.1%}"),
        ("a verbatim transcript scores zero", r_same == 0.0, f"{r_same:.1%}"),
        ("figures are found in a spoken reference",
         set(figs) == {"2024", "0142", "1.8", "3", "1.9"}, str(figs)),
        ("a perfect transcript loses no figure", miss_us == [], str(miss_us)),
        ("1.8 -> 1.4 is invisible to WER", r_bad < 0.05, f"{r_bad:.1%}"),
        ("1.8 -> 1.4 IS caught by the figure check", miss_bad == ["1.8"], str(miss_bad))]:
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}  ({detail})")

# ---- the audio plumbing, without a service
print("\naudio:")
a16 = M.resample(array.array("h", [0, 8000, 16000, 8000, 0] * 4410), 22050, 16000)
ok = abs(len(a16) - int(22050 / 22050 * 16000)) <= 2
bad += (not ok)
print(f"  {'ok     ' if ok else 'WRONG  '} resample 22050 -> 16000 keeps the duration "
      f"({len(a16)} samples from 22050)")

quiet = array.array("h", [300, -300] * 100)
loud = M.normalise(quiet)
gain = max(loud) / max(quiet)
ok = 2.0 < gain <= M.MAX_GAIN + 0.01
bad += (not ok)
print(f"  {'ok     ' if ok else 'WRONG  '} a quiet file is brought up (x{gain:.1f})")

p = os.path.join(D, "rt.wav")
M.write_wav(p, array.array("h", [0, 1000, -1000, 0] * 4000))
rt, rate = M.read_wav(p)
ok = rate == 16000 and len(rt) == 16000
bad += (not ok)
print(f"  {'ok     ' if ok else 'WRONG  '} write then read round-trips "
      f"({rate} Hz, {len(rt)} samples)")

stereo = os.path.join(D, "st.wav")
with wave.open(stereo, "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(16000)
    w.writeframes(array.array("h", [1000, 3000] * 1600).tobytes())
mono, _ = M.read_wav(stereo)
ok = len(mono) == 1600 and mono[0] == 2000
bad += (not ok)
print(f"  {'ok     ' if ok else 'WRONG  '} stereo is downmixed ({len(mono)} samples, "
      f"first = {mono[0]})")

# ---- can this machine actually make speech?
print("\nspeech synthesis on this machine:")
engine = ""
for exe in ("say", "espeak-ng", "espeak", "pico2wave"):
    if shutil.which(exe):
        engine = exe
        break
if engine:
    probe = os.path.join(D, "probe.wav")
    used = M.synthesise("Front pad thickness at one point eight millimetres.",
                        probe, None, None)
    if used and os.path.exists(probe) and os.path.getsize(probe) > 1000:
        a, rate = M.read_wav(probe)
        secs = len(a) / rate
        pk = max(abs(v) for v in a) / 32767
        ok = secs > 0.8 and pk > 0.02
        bad += (not ok)
        print(f"  {'ok     ' if ok else 'WRONG  '} {used}: {secs:.1f}s at {rate} Hz, "
              f"peak {pk:.0%} - real speech, not a tone")
    else:
        print(f"  note    {engine} is installed but produced nothing usable")
else:
    print("  note    no text-to-speech here. Either")
    print("            sudo apt-get update && sudo apt-get install -y espeak-ng")
    print("          or make the wav on your Mac and copy it over - "
          "scripts/make_speech.py prints how.")

h = A.health()
print(f"\nASR: {h['mode']} via {h['endpoint']}, "
      f"riva client {'installed' if h['riva_client_installed'] else 'MISSING'}")

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
Nothing above touched the network. To actually test transcription:

    .venv/bin/python scripts/test_asr.py --sample 1

That speaks a real update, sends it to NVCF, prints the transcript, and grades
the words and every figure in it. Then, for the whole pipeline:

    .venv/bin/python scripts/make_speech.py --sample 1 -o update.wav
    .venv/bin/python scripts/test_voice_update.py --audio update.wav
""")
sys.exit(1 if bad else 0)
