#!/usr/bin/env python3
"""Twenty-second pass: the hosted ASR is gRPC, and the UI hid that it was failing.

Run from the project root:   python3 quality_pass22.py

Pressing Transcribe did nothing and Extract-and-apply said "Nothing to submit".
Two separate faults, and the second is why the first took so long to find.

1. THE REST ENDPOINT DOES NOT EXIST.

       ASR_URL: https://ai.api.nvidia.com/v1/speech/nvidia/parakeet-ctc-0_6b-asr
       key present: True | prefix ok: True | length: 70
       HTTP 404
       body: 404 page not found

   The key was fine. There is no REST endpoint for this model: hosted Parakeet is
   Riva over gRPC through NVIDIA Cloud Functions. NVIDIA's own client calls it

       --server grpc.nvcf.nvidia.com:443 --use-ssl
       --metadata function-id "d8dd4e9b-fbf5-4fb0-9dba-8cf436c8d965"
       --metadata authorization "Bearer $NVIDIA_API_KEY"

   which is what the rewritten app/pipeline/asr.py does. The language default
   also moves from en-GB to en-US: this model publishes US English, and an
   unsupported code is rejected at the service rather than quietly ignored.

   ASR_GRPC_SERVER still points the whole thing at a local Riva or Parakeet NIM
   (with ASR_USE_SSL=0), and ASR_BASE_URL still selects an HTTP endpoint - so
   bringing ASR onto the box remains a config change, not a code change.

2. THE FAILURE WAS INVISIBLE WHERE IT MATTERED.

   `transcribe()` returned its reason, `ui_transcribe` put it in a small status
   box beside the button, and the person's attention was on the transcript box -
   which stayed empty and showed its PLACEHOLDER: a complete, plausible update
   ("C/S grinding from the front under braking. Front pads down to 1.8mm..."),
   in grey, indistinguishable from real content at a glance. Pressing Extract and
   apply then reported "Nothing to submit", which describes the symptom and hides
   the cause.

   So: the placeholder now reads as an instruction rather than as data, a failed
   transcription says so IN the transcript box where the eye already is, and
   "Nothing to submit" explains that the box is empty and what to do about it.
   A demo audience would have made exactly the same mistake.

   This is the second time in this project that a correct error message in the
   wrong place cost more than the bug it described.
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
                 "      Run passes 1-21 first. Stopping without changes.")
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


# ============================ 1. gRPC, not REST
write("app/pipeline/asr.py", '"""Speech to text via NVIDIA Parakeet.\n\nThe hosted model is Riva over **gRPC through NVIDIA Cloud Functions**, not a\nREST endpoint. This file used to POST to\n`https://ai.api.nvidia.com/v1/speech/nvidia/parakeet-ctc-0_6b-asr`, which returns\n`404 page not found` - so every transcription failed, the transcript box stayed\nempty, and the UI reported "Nothing to submit", which described the symptom and\nhid the cause.\n\nNVIDIA\'s own client invokes it as:\n\n    --server grpc.nvcf.nvidia.com:443 --use-ssl\n    --metadata function-id "d8dd4e9b-fbf5-4fb0-9dba-8cf436c8d965"\n    --metadata authorization "Bearer $NVIDIA_API_KEY"\n\nwhich is what `_transcribe_grpc` does. The function id identifies the model on\nNVCF and is not a secret; the key is.\n\nTwo ways to point this elsewhere, both without touching code:\n\n    ASR_GRPC_SERVER   a local Riva or Parakeet NIM, e.g. localhost:50051\n                      (set ASR_USE_SSL=0 for a local one - no TLS)\n    ASR_BASE_URL      an HTTP endpoint, if you run a NIM that serves REST\n\nNever raises. A `Transcript` always comes back, carrying the reason in `error`,\nbecause a failed transcription must leave the technician able to type instead.\n"""\nfrom __future__ import annotations\nimport os\nimport wave\nfrom dataclasses import dataclass\n\nimport httpx\nfrom app.nim.client import api_key, _LIMITER\n\n# Hosted Parakeet CTC 0.6B on NVCF. The function id is public - it names the\n# model, not the caller.\nASR_GRPC_SERVER = os.environ.get("ASR_GRPC_SERVER", "grpc.nvcf.nvidia.com:443")\nASR_FUNCTION_ID = os.environ.get("ASR_FUNCTION_ID",\n                                 "d8dd4e9b-fbf5-4fb0-9dba-8cf436c8d965")\nASR_USE_SSL = os.environ.get("ASR_USE_SSL", "1") != "0"\n# en-US, not en-GB: this model publishes US English, and an unsupported code is\n# rejected at the service rather than ignored.\nASR_LANGUAGE = os.environ.get("ASR_LANGUAGE", "en-US")\n# Set only when something local serves ASR over HTTP; empty means use gRPC.\nASR_BASE_URL = os.environ.get("ASR_BASE_URL", "").strip()\n\nINSTALL_HINT = ("nvidia-riva-client is not installed - the hosted ASR is gRPC. "\n                "Install it with:  uv pip install --python .venv nvidia-riva-client")\n\n\n@dataclass\nclass Transcript:\n    text: str\n    confidence: float | None = None\n    duration_s: float | None = None\n    source: str = "hosted"\n    error: str | None = None\n\n    @property\n    def ok(self) -> bool:\n        return self.error is None and bool(self.text.strip())\n\n\ndef _wav_specs(path: str) -> tuple[int | None, int | None, float | None]:\n    """Sample rate, channels and duration, for a WAV. (None, None, None) otherwise."""\n    try:\n        with wave.open(path, "rb") as w:\n            rate = w.getframerate()\n            return rate, w.getnchannels(), w.getnframes() / float(rate)\n    except Exception:\n        return None, None, None\n\n\ndef _duration(path: str) -> float | None:\n    return _wav_specs(path)[2]\n\n\ndef _transcribe_grpc(audio_path: str, language: str, dur: float | None) -> Transcript:\n    try:\n        import riva.client\n    except ImportError:\n        return Transcript("", duration_s=dur, source="grpc", error=INSTALL_HINT)\n    try:\n        if ASR_USE_SSL:                 # hosted: the shared 40/min limiter applies\n            _LIMITER.wait()\n        auth = riva.client.Auth(\n            uri=ASR_GRPC_SERVER, use_ssl=ASR_USE_SSL,\n            metadata_args=[["function-id", ASR_FUNCTION_ID],\n                           ["authorization", f"Bearer {api_key()}"]])\n        service = riva.client.ASRService(auth)\n        config = riva.client.RecognitionConfig(\n            language_code=language, max_alternatives=1,\n            enable_automatic_punctuation=True)\n        try:\n            # Reads the file\'s real encoding, rate and channel count.\n            riva.client.add_audio_file_specs_to_config(config, audio_path)\n        except Exception:\n            rate, channels, _ = _wav_specs(audio_path)\n            config.encoding = riva.client.AudioEncoding.LINEAR_PCM\n            config.sample_rate_hertz = rate or 16000\n            config.audio_channel_count = channels or 1\n        with open(audio_path, "rb") as fh:\n            response = service.offline_recognize(fh.read(), config)\n\n        parts: list[str] = []\n        confidence: float | None = None\n        for result in response.results:\n            if not result.alternatives:\n                continue\n            best = result.alternatives[0]\n            parts.append(best.transcript)\n            c = getattr(best, "confidence", None)\n            if c is not None:\n                confidence = c if confidence is None else min(confidence, c)\n        return Transcript(" ".join(p.strip() for p in parts).strip(),\n                          confidence, dur, "grpc")\n    except Exception as e:\n        # A gRPC failure carries its status in the exception text; keep enough of\n        # it to tell an expired key from an unreachable server.\n        return Transcript("", duration_s=dur, source="grpc",\n                          error=f"{type(e).__name__}: {str(e)[:240]}")\n\n\ndef _transcribe_rest(audio_path: str, language: str, dur: float | None) -> Transcript:\n    """For a NIM that serves ASR over HTTP. Not the hosted path."""\n    try:\n        _LIMITER.wait()\n        with open(audio_path, "rb") as fh:\n            r = httpx.post(ASR_BASE_URL,\n                           headers={"Authorization": f"Bearer {api_key()}"},\n                           files={"file": (os.path.basename(audio_path), fh,\n                                           "audio/wav")},\n                           data={"language": language}, timeout=120.0)\n        r.raise_for_status()\n        data = r.json()\n        text = (data.get("text") or data.get("transcript")\n                or " ".join(s.get("transcript", "")\n                            for s in data.get("segments", []))).strip()\n        return Transcript(text, data.get("confidence"), dur, "rest")\n    except Exception as e:\n        return Transcript("", duration_s=dur, source="rest",\n                          error=f"{type(e).__name__}: {str(e)[:240]}")\n\n\ndef transcribe(audio_path: str, language: str | None = None) -> Transcript:\n    """Transcribe a local audio file. Returns a Transcript, never raises."""\n    if not audio_path or not os.path.exists(audio_path):\n        return Transcript("", error=f"no audio file at {audio_path}")\n    lang = language or ASR_LANGUAGE\n    dur = _duration(audio_path)\n    if ASR_BASE_URL:\n        return _transcribe_rest(audio_path, lang, dur)\n    return _transcribe_grpc(audio_path, lang, dur)\n\n\ndef health() -> dict:\n    """Which ASR path is configured, and whether its client is importable."""\n    try:\n        import riva.client  # noqa: F401\n        have_riva = True\n    except ImportError:\n        have_riva = False\n    return {"mode": "rest" if ASR_BASE_URL else "grpc",\n            "endpoint": ASR_BASE_URL or ASR_GRPC_SERVER,\n            "function_id": None if ASR_BASE_URL else ASR_FUNCTION_ID,\n            "language": ASR_LANGUAGE,\n            "riva_client_installed": have_riva,\n            "ready": have_riva or bool(ASR_BASE_URL)}\n',
      "app/pipeline/asr.py  Riva gRPC via NVCF, with local and REST escapes")


# ============================ 2. the placeholder that looked like content
edit("app/ui/gradio_app.py",
     '                                placeholder="C/S grinding from the front under braking. "\n                                            "Front pads down to 1.8mm, rotor at 22.8mm...")',
     '                                placeholder="Type the update here, or press "\n                                            "Transcribe to fill it from audio. "\n                                            "Example: C/S grinding from the front "\n                                            "under braking, front pads 1.8mm "\n                                            "against a 3mm minimum...")',
     "gradio_app.py  the placeholder reads as an instruction",
     skip_if="Type the update here, or press")


# ============================ 3. say what went wrong, where it is being read
edit("app/ui/gradio_app.py",
     '    from app.pipeline.asr import transcribe\n    t = transcribe(audio_path)\n    if not t.ok:\n        return "", f"Transcription failed: {t.error}"\n    dur = f" ({t.duration_s:.1f}s)" if t.duration_s else ""\n    return t.text, f"Transcribed{dur}. Check it, correct anything, then submit."',
     '    from app.pipeline.asr import transcribe\n    t = transcribe(audio_path)\n    if not t.ok:\n        # Put the reason IN the transcript box. It used to go only to the status\n        # line beside the button, while the box kept showing its grey placeholder\n        # - which read as a filled-in update, so the failure was invisible.\n        return (f"[ Transcription failed - type the update here instead ]\\n\\n"\n                f"{t.error}",\n                f"**Transcription failed.** {t.error}")\n    dur = f" ({t.duration_s:.1f}s)" if t.duration_s else ""\n    return t.text, f"Transcribed{dur}. Check it, correct anything, then submit."',
     "gradio_app.py  a failed transcription says so in the box",
     skip_if="Transcription failed - type the update here instead")

edit("app/ui/gradio_app.py",
     '    if not (text or "").strip():\n        return "Nothing to submit - record or type an update first.", ""',
     '    if not (text or "").strip():\n        from app.pipeline.asr import health as asr_health\n        h = asr_health()\n        hint = ("" if h["ready"] else\n                f"\\n\\nSpeech to text is not ready: {h[\'mode\']} via "\n                f"{h[\'endpoint\']}"\n                + ("" if h["riva_client_installed"] or h["mode"] == "rest"\n                   else ", and nvidia-riva-client is not installed."))\n        return ("The transcript box is empty, so there is nothing to apply.\\n\\n"\n                "The grey text in it is a placeholder, not content - click into "\n                "the box and type or paste the update, or press Transcribe to "\n                "fill it from audio." + hint), ""',
     "gradio_app.py  explain WHY there is nothing to submit",
     skip_if="The grey text in it is a placeholder")


# ============================ 4. declare the dependency
edit("pyproject.toml",
     'nvidia = ["nemoguardrails>=0.11", "aiqtoolkit>=1.1"]',
     'nvidia = ["nemoguardrails>=0.11", "aiqtoolkit>=1.1"]\n# Hosted Parakeet is Riva over gRPC; this is the client for it. Separate because\n# it pulls grpcio, and everything except speech-to-text works without it.\nvoice = ["nvidia-riva-client>=2.16"]',
     "pyproject.toml  a voice extra for nvidia-riva-client",
     skip_if="nvidia-riva-client")


# ============================ verify
print("Quality pass 22:")
for c in CHANGES:
    print(c)
for f in ("app/pipeline/asr.py", "app/ui/gradio_app.py"):
    ast.parse((ROOT / f).read_text())
print("\nasr.py and gradio_app.py parse cleanly.")

sys.path.insert(0, ".")
import importlib, os
import app.pipeline.asr as A
importlib.reload(A)
bad = 0

h = A.health()
print(f"\nASR configuration:")
for k, v in h.items():
    print(f"  {k:24s} {v}")

CHECKS = [
    # Behavioural, not textual: the old URL still appears in the module
    # docstring, where it explains the bug. What matters is that nothing
    # reaches for it - no ASR_URL constant, and no REST default.
    ("the dead REST endpoint is no longer reachable from code",
     not hasattr(A, "ASR_URL") and A.ASR_BASE_URL == ""),
    ("gRPC is the default path", h["mode"] == "grpc"),
    ("points at NVCF", h["endpoint"] == "grpc.nvcf.nvidia.com:443"),
    ("carries the function id",
     h["function_id"] == "d8dd4e9b-fbf5-4fb0-9dba-8cf436c8d965"),
    ("language is en-US", h["language"] == "en-US"),
]
print()
for name, ok in CHECKS:
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}")

# never raises, whatever it is handed
for name, path in (("a missing file", "/nonexistent/none.wav"),
                   ("an empty path", "")):
    try:
        t = A.transcribe(path)
        ok = isinstance(t, A.Transcript) and t.error and not t.ok
    except Exception as e:
        ok = False
        print(f"  WRONG   {name} raised {type(e).__name__}")
    bad += (not ok)
    if ok:
        print(f"  ok      {name} returns a Transcript carrying its reason")

# a real WAV: with riva absent it must say so, not crash
import wave, struct, math, tempfile
p = os.path.join(tempfile.mkdtemp(), "tone.wav")
with wave.open(p, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
    w.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / 16000)))
                           for i in range(16000)))
t = A.transcribe(p)
dur_ok = t.duration_s is not None and abs(t.duration_s - 1.0) < 0.01
bad += (not dur_ok)
print(f"  {'ok     ' if dur_ok else 'WRONG  '} reads the audio duration "
      f"({t.duration_s}s from a 1s file)")
if not h["riva_client_installed"]:
    ok = t.error and "nvidia-riva-client" in t.error
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} without the client it names the "
          f"install, it does not crash")
    print(f"           {t.error}")
else:
    print(f"  note    riva client present - transcript: {t.text!r} error={t.error}")

# the UI no longer hides the cause
g = (ROOT / "app/ui/gradio_app.py").read_text()
for name, ok in [("placeholder is an instruction", "Type the update here, or press" in g),
                 ("failure lands in the transcript box",
                  "Transcription failed - type the update here instead" in g),
                 ("empty-box message explains the placeholder",
                  "The grey text in it is a placeholder" in g)]:
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}")

print(f"\n{bad} check(s) unexpected" if bad
      else "\nAll pass-22 checks behaved as expected.")
print("\nNext:  uv pip install --python .venv nvidia-riva-client")
print("Then:  restart Gradio and press Transcribe")
print("\nA local Riva/Parakeet NIM instead of the hosted one, no code change:")
print("  export ASR_GRPC_SERVER=localhost:50051 ASR_USE_SSL=0")
