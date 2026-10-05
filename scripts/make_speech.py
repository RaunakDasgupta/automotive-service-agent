#!/usr/bin/env python3
"""Turn text into a 16 kHz mono WAV, with whatever text-to-speech this machine has.

    .venv/bin/python scripts/make_speech.py --sample 1
    .venv/bin/python scripts/make_speech.py --text "Front pads at 1.8 millimetres"
    .venv/bin/python scripts/make_speech.py --sample 1 -o /tmp/update.wav

WHY THIS EXISTS

The ASR leg could not be tested. This box has no microphone, and the only audio
the checks could manufacture was a 440 Hz sine tone - which a speech model
correctly transcribes as nothing at all. An empty transcript from a tone is
indistinguishable from an ASR that is broken end to end, so the check passed
either way and proved neither. Real words are the entire point.

Synthetic speech is not a technician leaning over a wing in a noisy workshop, and
it will flatter the model. What it does do is exercise every link that was
unproven - encode, authenticate, transport, decode, and return words - and it
puts real figures through, so "1.8 millimetres" either survives or it does not.

Nothing is downloaded and no Python dependency is added. It shells out to a TTS
that is already on the machine, in this order:

    say         macOS, always present
    espeak-ng   Linux:  sudo apt-get install -y espeak-ng
    espeak      older Linux
    pico2wave   Linux:  sudo apt-get install -y libttspico-utils
    piper       only if PIPER_MODEL points at a .onnx voice

If none is installed, there is a second route that needs nothing on the box: run
this on a Mac, then copy the file over. The failure message prints it.
"""
from __future__ import annotations
import argparse, array, os, shutil, subprocess, sys, tempfile, wave

sys.path.insert(0, ".")
import _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py

TARGET_RATE = 16000          # what Riva wants, and what the NIMs serve
TARGET_PEAK = 0.7            # about -3 dBFS: loud enough, no clipping
MAX_GAIN = 8.0               # never amplify near-silence into hiss


# ------------------------------------------------------------------ audio, by hand
# Deliberately no numpy, no ffmpeg, no sox: a 15-line resampler has no install
# story, and this has to work on a fresh box at demo time.

def read_wav(path: str) -> tuple[array.array, int]:
    """16-bit WAV -> (mono samples, rate). Downmixes; raises on other widths."""
    with wave.open(path, "rb") as w:
        ch, sw, rate, n = (w.getnchannels(), w.getsampwidth(),
                           w.getframerate(), w.getnframes())
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError(f"{path} is {sw * 8}-bit; this expects 16-bit PCM")
    a = array.array("h")
    a.frombytes(raw)
    if sys.byteorder == "big":       # WAV is little-endian
        a.byteswap()
    if ch > 1:
        a = array.array("h", [sum(a[i * ch:(i + 1) * ch]) // ch
                              for i in range(len(a) // ch)])
    return a, rate


def resample(a: array.array, src: int, dst: int) -> array.array:
    """Linear interpolation. Good enough for speech that a model has to read."""
    if src == dst or not a:
        return a
    ratio = src / dst
    out = array.array("h")
    n = int(len(a) / ratio)
    last = len(a) - 1
    for i in range(n):
        x = i * ratio
        j = int(x)
        if j >= last:
            out.append(a[last])
            continue
        v = a[j] + (a[j + 1] - a[j]) * (x - j)
        out.append(int(max(-32768, min(32767, v))))
    return out


def normalise(a: array.array, target: float = TARGET_PEAK) -> array.array:
    """Bring the peak up to `target` of full scale. A quiet file transcribes badly."""
    peak = max((abs(v) for v in a), default=0)
    if peak == 0:
        return a
    gain = min((target * 32767) / peak, MAX_GAIN)
    if 0.98 < gain < 1.02:
        return a
    return array.array("h", [int(max(-32768, min(32767, v * gain))) for v in a])


def write_wav(path: str, a: array.array, rate: int = TARGET_RATE) -> None:
    b = array.array("h", a)
    if sys.byteorder == "big":
        b.byteswap()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b.tobytes())


# ------------------------------------------------------------------ the engines

def _run(cmd: list[str]) -> bool:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def synthesise(text: str, out: str, voice: str | None, wpm: int | None) -> str:
    """Write raw TTS audio to `out`. Returns the engine name, or "" if none worked."""
    if shutil.which("say"):                       # macOS: asks for 16k directly
        cmd = ["say", "--file-format=WAVE", f"--data-format=LEI16@{TARGET_RATE}",
               "-r", str(wpm or 175), "-o", out]
        if voice:
            cmd += ["-v", voice]
        if _run(cmd + [text]):
            return "say"
    for exe in ("espeak-ng", "espeak"):
        if shutil.which(exe):
            cmd = [exe, "-w", out, "-s", str(wpm or 150)]
            if voice:
                cmd += ["-v", voice]
            if _run(cmd + [text]):
                return exe
    if shutil.which("pico2wave"):
        if _run(["pico2wave", "-l", voice or "en-GB", "-w", out, text]):
            return "pico2wave"
    model = os.environ.get("PIPER_MODEL", "")
    if shutil.which("piper") and model:
        try:
            with open(out, "wb") as fh:
                p = subprocess.run(["piper", "--model", model, "--output_file", out],
                                   input=text.encode(), capture_output=True,
                                   timeout=180)
            if p.returncode == 0 and os.path.getsize(out):
                return "piper"
        except (OSError, subprocess.SubprocessError):
            pass
    return ""


NO_TTS = """No text-to-speech on this machine, so there is no way to make the audio here.

Install one (a few seconds, no GPU):

    sudo apt-get update && sudo apt-get install -y espeak-ng

Or make the file on your Mac, which already has `say`, and copy it over:

    say --file-format=WAVE --data-format=LEI16@16000 -o update.wav \\
        "Update for repair order RO-2024-0142. Front pad thickness at one point \\
         eight millimetres against a three millimetre minimum."
    scp update.wav capstone-poc:~/automotive-service-agent/update.wav

Then:

    .venv/bin/python scripts/test_asr.py --wav update.wav
"""


# ------------------------------------------------------------------ samples

def sample_text(n: int) -> tuple[str, str | None]:
    """The nth spoken update from test_voice_update.py, with a real RO in it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_tvu", os.path.join("scripts", "test_voice_update.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if not 1 <= n <= len(m.SAMPLES):
        raise SystemExit(f"--sample must be 1-{len(m.SAMPLES)}")
    s = m.SAMPLES[n - 1]
    ron = None
    try:
        from app.state import db as dbm
        ron = m._pick_ro(dbm.connect(), s.get("needs", "open"))
    except Exception:
        pass
    text = s["text"].replace("{RO}", ron or "RO-2024-0142")
    return text, ron


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Make a 16 kHz mono WAV of spoken text, for testing the ASR leg.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sample", type=int, help="a spoken update from test_voice_update.py")
    g.add_argument("--text", help="your own words")
    ap.add_argument("-o", "--out", default="update.wav")
    ap.add_argument("--voice", help="an engine voice name, e.g. Daniel or en-gb")
    ap.add_argument("--wpm", type=int, help="speaking rate (say: 175, espeak: 150)")
    args = ap.parse_args()

    if not (os.path.exists("pyproject.toml") and os.path.isdir("app/pipeline")):
        print("Run from the project root:\n"
              "  cd ~/automotive-service-agent && "
              ".venv/bin/python scripts/make_speech.py --sample 1")
        return 2

    ron = None
    if args.sample:
        text, ron = sample_text(args.sample)
    else:
        text = args.text

    raw = os.path.join(tempfile.mkdtemp(), "raw.wav")
    engine = synthesise(text, raw, args.voice, args.wpm)
    if not engine:
        print(NO_TTS)
        return 2

    a, rate = read_wav(raw)
    a = normalise(resample(a, rate, TARGET_RATE))
    write_wav(args.out, a)
    secs = len(a) / TARGET_RATE
    peak = max((abs(v) for v in a), default=0) / 32767

    print(f"-- spoken {'-' * 65}")
    print("  " + text[:300] + ("..." if len(text) > 300 else ""))
    print(f"\n-- audio {'-' * 66}")
    print(f"  {args.out}")
    print(f"  {engine}, {rate} Hz -> {TARGET_RATE} Hz mono, "
          f"{secs:.1f}s, peak {peak:.0%} of full scale")
    print(f"\nNext, transcribe it and grade what comes back:")
    if args.sample:
        print(f"  .venv/bin/python scripts/test_asr.py --sample {args.sample}")
    else:
        print(f"  .venv/bin/python scripts/test_asr.py --wav {args.out} "
              f"--expect {text!r}")
    print(f"\nOr put it through the whole update pipeline:")
    print(f"  .venv/bin/python scripts/test_voice_update.py --audio {args.out}"
          + (f" --ro {ron}" if ron else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
