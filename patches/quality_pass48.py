#!/usr/bin/env python3
"""pass 48 - replace the two components that were not NVIDIA but had an NVIDIA
equivalent sitting unused.

    .venv/bin/python patches/quality_pass48.py            apply
    .venv/bin/python patches/quality_pass48.py --check    verify, change nothing

WHAT AND WHY

1. TEXT-TO-SPEECH.  scripts/make_speech.py shelled out to `say`, `espeak-ng`,
   `pico2wave` or `piper` - whatever the machine happened to have. On this box
   that is espeak, whose output is a buzz that flatters nothing, and on a Mac it
   is Apple's voice. Neither is NVIDIA, and the project already ships a Riva
   client and a key entitled to Magpie TTS. The ASR leg was NVIDIA and the leg
   that fed it was not, so the one end-to-end speech test in the project was
   half off-stack. Riva Magpie TTS is now the first engine tried; the shell-out
   engines remain as the offline fallback.

   Verified before writing: ai-magpie-tts-multilingual is ACTIVE for this key,
   returns 16 kHz LINEAR_PCM, and its output round-trips through the project's
   own Parakeet ASR as "Front pads at 1.8 mm on Ro 26 08165" - the figure
   survives, which is the only thing that harness exists to prove.

2. GPU TELEMETRY.  Prometheus scraped the application's own counters and
   nothing else. On a single-L40S deployment whose whole argument is that three
   NIMs co-reside in 40 GB, not measuring the GPU is a strange omission, and
   NVIDIA ships the exporter for exactly this: DCGM. It now runs beside
   Prometheus and Grafana, on 9401 because the app already holds 9400.

NOT DONE, and why: NeMo Curator PII redaction. The reference architecture shows
it, but nemo_curator 1.3.0 exposes no PII or de-identification modifier -
checked by walking the whole package. Writing the detection here and calling it
NeMo Curator would be a label, not a component.
"""
from __future__ import annotations
import argparse, json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = "--check" in sys.argv


def edit(rel: str, subs: list[tuple[str, str]], *, skip_if: str | None = None) -> str:
    p = ROOT / rel
    if not p.exists():
        return f"MISSING   {rel}"
    s = orig = p.read_text()
    if skip_if and skip_if in s:
        return f"already   {rel}"
    for a, b in subs:
        if a not in s:
            return f"ANCHOR    {rel}  ->  {a[:60]!r}"
        s = s.replace(a, b, 1)
    if s == orig:
        return f"no-op     {rel}"
    if not CHECK:
        p.write_text(s)
    return f"{'would patch' if CHECK else 'patched  '} {rel}"


# ===================================================================== 1. TTS
RIVA_BLOCK = '''
# ------------------------------------------------------------------ Riva TTS
# The first engine tried. Magpie is NVIDIA's multilingual TTS and it is reached
# the same way as Parakeet ASR: Riva over NVCF gRPC, the function id in a header.
# Both legs of the speech test are now on the NVIDIA stack.
TTS_GRPC_SERVER = os.environ.get("TTS_GRPC_SERVER", "grpc.nvcf.nvidia.com:443")
TTS_FUNCTION_ID = os.environ.get("TTS_FUNCTION_ID",
                                 "877104f7-e885-42b9-8de8-f6e4c6303969")
TTS_VOICE = os.environ.get("TTS_VOICE", "Magpie-Multilingual.EN-US.Sofia")
TTS_USE_SSL = os.environ.get("TTS_USE_SSL", "1") != "0"


def _riva_tts(text: str, out: str, voice: str | None) -> str:
    """Synthesise with Riva. Returns the engine name, or "" with a reason on
    stderr - a missing key or client is a reason to fall back, not to fail."""
    try:
        import riva.client as rc
    except ImportError:
        print("   riva: nvidia-riva-client not installed "
              "(uv pip install --python .venv nvidia-riva-client)", file=sys.stderr)
        return ""
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key and TTS_USE_SSL:
        print("   riva: NVIDIA_API_KEY is not set", file=sys.stderr)
        return ""
    try:
        meta = [["function-id", TTS_FUNCTION_ID]]
        if key:
            meta.append(["authorization", f"Bearer {key}"])
        auth = rc.Auth(uri=TTS_GRPC_SERVER, use_ssl=TTS_USE_SSL, metadata_args=meta)
        resp = rc.SpeechSynthesisService(auth).synthesize(
            text, voice_name=voice or TTS_VOICE, language_code="en-US",
            sample_rate_hz=TARGET_RATE, encoding=rc.AudioEncoding.LINEAR_PCM)
        pcm = resp.audio
        if not pcm:
            print("   riva: empty audio returned", file=sys.stderr)
            return ""
        # LINEAR_PCM at TARGET_RATE already - wrap it, do not resample.
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(TARGET_RATE)
            w.writeframes(pcm)
        return "riva/magpie"
    except Exception as e:                       # grpc raises a dozen types
        print(f"   riva: {type(e).__name__}: {str(e)[:150]}", file=sys.stderr)
        return ""

'''

SYNTH_OLD = '''def synthesise(text: str, out: str, voice: str | None, wpm: int | None) -> str:
    """Write raw TTS audio to `out`. Returns the engine name, or "" if none worked."""
    if shutil.which("say"):'''

SYNTH_NEW = '''def synthesise(text: str, out: str, voice: str | None, wpm: int | None,
               engine: str = "auto") -> str:
    """Write raw TTS audio to `out`. Returns the engine name, or "" if none worked.

    Riva first, because it is the NVIDIA engine and because it sounds like a
    person; the shell-out engines are the offline fallback. TTS_ENGINE=local
    skips Riva, TTS_ENGINE=riva refuses to fall back - useful when you want the
    test to fail rather than quietly prove something else.
    """
    want = (engine or os.environ.get("TTS_ENGINE", "auto")).strip().lower()
    if want in ("auto", "riva"):
        name = _riva_tts(text, out, voice)
        if name:
            return name
        if want == "riva":
            return ""
    if shutil.which("say"):'''

REPORT_OLD = '''    raw = os.path.join(tempfile.mkdtemp(), "raw.wav")
    engine = synthesise(text, raw, args.voice, args.wpm)'''
REPORT_NEW = '''    raw = os.path.join(tempfile.mkdtemp(), "raw.wav")
    engine = synthesise(text, raw, args.voice, args.wpm, args.engine)'''

ARG_OLD = '''    ap.add_argument("--wpm", type=int, help="speaking rate (say: 175, espeak: 150)")'''
ARG_NEW = '''    ap.add_argument("--wpm", type=int, help="speaking rate (say: 175, espeak: 150)")
    ap.add_argument("--engine", default="auto", choices=("auto", "riva", "local"),
                    help="auto tries Riva then the local engines; riva refuses "
                         "to fall back; local skips Riva entirely")'''

results = [edit("scripts/make_speech.py", [
    ("def _run(cmd: list[str]) -> bool:", RIVA_BLOCK.lstrip("\n") + "\ndef _run(cmd: list[str]) -> bool:"),
    (SYNTH_OLD, SYNTH_NEW),
    (ARG_OLD, ARG_NEW),
    (REPORT_OLD, REPORT_NEW),
], skip_if="_riva_tts")]


# ============================================================ 2. GPU telemetry
PROM_OLD = '''  # The three NIMs publish Triton metrics on their own container port 8002.'''
PROM_NEW = '''  # NVIDIA DCGM. The GPU itself - utilisation, framebuffer, power, temperature,
  # clocks. 9401 because the app already holds 9400. Started by
  # scripts/start_observability.sh; if it is not running this target is simply
  # down, which Prometheus reports and nothing else notices.
  - job_name: dcgm
    static_configs:
      - targets: ["localhost:9401"]

  # The three NIMs publish Triton metrics on their own container port 8002.'''

OBS_PORT_OLD = '''APP_METRICS="${ASOIA_METRICS_PORT:-9400}"'''
OBS_PORT_NEW = '''APP_METRICS="${ASOIA_METRICS_PORT:-9400}"
DCGM_PORT="${DCGM_PORT:-9401}"
DCGM_IMAGE="${DCGM_IMAGE:-nvcr.io/nvidia/k8s/dcgm-exporter:4.1.1-4.0.4-ubuntu22.04}"'''

OBS_UP_OLD = '''  echo "==> grafana on :$GRAF_PORT (anonymous viewer, no login)"'''
OBS_UP_NEW = '''  # NVIDIA DCGM exporter. Needs the GPU and SYS_ADMIN for the profiling
  # counters. Loopback-bound like everything else here. A box with no GPU
  # simply does not get this container, and the dcgm scrape target stays down.
  if command -v nvidia-smi >/dev/null 2>&1; then
    echo "==> dcgm-exporter on :$DCGM_PORT (GPU telemetry)"
    docker rm -f asoia-dcgm >/dev/null 2>&1
    docker run -d --name asoia-dcgm --gpus all --cap-add SYS_ADMIN \\
      --restart unless-stopped -p "127.0.0.1:$DCGM_PORT:9400" \\
      "$DCGM_IMAGE" >/dev/null \\
      || echo "    dcgm-exporter did not start - GPU panels will be empty"
  else
    echo "==> no nvidia-smi, skipping dcgm-exporter"
  fi

  echo "==> grafana on :$GRAF_PORT (anonymous viewer, no login)"'''

OBS_DOWN_OLD = '''  docker rm -f asoia-prometheus asoia-grafana >/dev/null 2>&1'''
OBS_DOWN_NEW = '''  docker rm -f asoia-prometheus asoia-grafana asoia-dcgm >/dev/null 2>&1'''

OBS_STATUS_OLD = '''  printf 'prometheus   -> '
  curl -s -o /dev/null -w '%{http_code}\\n' --max-time 4 "http://localhost:$PROM_PORT/-/ready" \\
    || echo "unreachable"'''
OBS_STATUS_NEW = '''  printf 'prometheus   -> '
  curl -s -o /dev/null -w '%{http_code}\\n' --max-time 4 "http://localhost:$PROM_PORT/-/ready" \\
    || echo "unreachable"
  printf 'dcgm /metrics -> '
  curl -s -o /dev/null -w '%{http_code}\\n' --max-time 4 "http://localhost:$DCGM_PORT/metrics" \\
    || echo "unreachable"'''

results.append(edit("configs/prometheus.yml", [(PROM_OLD, PROM_NEW)],
                    skip_if="job_name: dcgm"))
results.append(edit("scripts/start_observability.sh", [
    (OBS_PORT_OLD, OBS_PORT_NEW),
    (OBS_UP_OLD, OBS_UP_NEW),
    (OBS_DOWN_OLD, OBS_DOWN_NEW),
    (OBS_STATUS_OLD, OBS_STATUS_NEW),
], skip_if="asoia-dcgm"))


# -------------------------------------------------- Grafana: a GPU row
GPU_PANELS = [
 {"type": "timeseries",
  "title": "GPU utilisation and framebuffer",
  "description": "NVIDIA DCGM. Three NIMs co-reside in about 40 GB of the 48; "
                 "this is where that stops being a claim.",
  "gridPos": {"h": 7, "w": 12, "x": 0, "y": 20},
  "targets": [
    {"expr": "DCGM_FI_DEV_GPU_UTIL", "legendFormat": "SM util %"},
    {"expr": "DCGM_FI_DEV_FB_USED / 1024", "legendFormat": "framebuffer used (GiB)"},
  ],
  "fieldConfig": {"defaults": {"min": 0, "custom": {"fillOpacity": 8}}, "overrides": []}},
 {"type": "timeseries",
  "title": "GPU power, temperature and clock",
  "description": "NVIDIA DCGM. Power and temperature are what throttle an L40S "
                 "long before memory does.",
  "gridPos": {"h": 7, "w": 12, "x": 12, "y": 20},
  "targets": [
    {"expr": "DCGM_FI_DEV_POWER_USAGE", "legendFormat": "power (W)"},
    {"expr": "DCGM_FI_DEV_GPU_TEMP", "legendFormat": "temp (C)"},
    {"expr": "DCGM_FI_DEV_SM_CLOCK", "legendFormat": "SM clock (MHz)"},
  ],
  "fieldConfig": {"defaults": {"min": 0, "custom": {"fillOpacity": 0}}, "overrides": []}},
]

dash = ROOT / "configs/grafana/dashboards/asoia-dashboard.json"
if not dash.exists():
    results.append("MISSING   configs/grafana/dashboards/asoia-dashboard.json")
else:
    d = json.loads(dash.read_text())
    have = {p.get("title") for p in d.get("panels", [])}
    todo = [p for p in GPU_PANELS if p["title"] not in have]
    if not todo:
        results.append("already   configs/grafana/dashboards/asoia-dashboard.json")
    else:
        d["panels"].extend(todo)
        if not CHECK:
            dash.write_text(json.dumps(d, indent=1) + "\n")
        results.append(("would patch" if CHECK else "patched  ")
                       + " configs/grafana/dashboards/asoia-dashboard.json "
                       + f"(+{len(todo)} GPU panels)")

for r in results:
    print(" ", r)
bad = [r for r in results if r.startswith(("ANCHOR", "MISSING"))]
print()
print("FAILED" if bad else ("check only - nothing written" if CHECK else "pass 48 applied"))
sys.exit(1 if bad else 0)
