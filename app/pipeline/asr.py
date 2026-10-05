"""Speech to text via NVIDIA Parakeet.

The hosted model is Riva over **gRPC through NVIDIA Cloud Functions**, not a
REST endpoint. This file used to POST to
`https://ai.api.nvidia.com/v1/speech/nvidia/parakeet-ctc-0_6b-asr`, which returns
`404 page not found` - so every transcription failed, the transcript box stayed
empty, and the UI reported "Nothing to submit", which described the symptom and
hid the cause.

NVIDIA's own client invokes it as:

    --server grpc.nvcf.nvidia.com:443 --use-ssl
    --metadata function-id "d8dd4e9b-fbf5-4fb0-9dba-8cf436c8d965"
    --metadata authorization "Bearer $NVIDIA_API_KEY"

which is what `_transcribe_grpc` does. The function id identifies the model on
NVCF and is not a secret; the key is.

Two ways to point this elsewhere, both without touching code:

    ASR_GRPC_SERVER   a local Riva or Parakeet NIM, e.g. localhost:50051
                      (set ASR_USE_SSL=0 for a local one - no TLS)
    ASR_BASE_URL      an HTTP endpoint, if you run a NIM that serves REST

Never raises. A `Transcript` always comes back, carrying the reason in `error`,
because a failed transcription must leave the technician able to type instead.
"""
from __future__ import annotations
import array
import os
import sys as _sys
import wave
from dataclasses import dataclass

import httpx
from app.nim.client import api_key, _LIMITER

# Hosted Parakeet CTC 0.6B on NVCF. The function id is public - it names the
# model, not the caller.
ASR_GRPC_SERVER = os.environ.get("ASR_GRPC_SERVER", "grpc.nvcf.nvidia.com:443")
ASR_FUNCTION_ID = os.environ.get("ASR_FUNCTION_ID",
                                 "d8dd4e9b-fbf5-4fb0-9dba-8cf436c8d965")
ASR_USE_SSL = os.environ.get("ASR_USE_SSL", "1") != "0"
# en-US, not en-GB: this model publishes US English, and an unsupported code is
# rejected at the service rather than ignored.
ASR_LANGUAGE = os.environ.get("ASR_LANGUAGE", "en-US")
# Set only when something local serves ASR over HTTP; empty means use gRPC.
ASR_BASE_URL = os.environ.get("ASR_BASE_URL", "").strip()

INSTALL_HINT = ("nvidia-riva-client is not installed - the hosted ASR is gRPC. "
                "Install it with:  uv pip install --python .venv nvidia-riva-client")


@dataclass
class Transcript:
    text: str
    confidence: float | None = None
    duration_s: float | None = None
    source: str = "hosted"
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text.strip())


def _wav_specs(path: str) -> tuple[int | None, int | None, float | None]:
    """Sample rate, channels and duration, for a WAV. (None, None, None) otherwise."""
    try:
        with wave.open(path, "rb") as w:
            rate = w.getframerate()
            return rate, w.getnchannels(), w.getnframes() / float(rate)
    except Exception:
        return None, None, None


def _duration(path: str) -> float | None:
    return _wav_specs(path)[2]


# Rates a speech service will accept without comment. 16000 is what Riva wants
# and what the NIMs serve; the rest are what recorders and browsers produce.
_SANE_RATES = (8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000)


def _level(path: str) -> float | None:
    """Peak amplitude as a fraction of full scale. None if not readable as 16-bit WAV."""
    try:
        with wave.open(path, "rb") as w:
            if w.getsampwidth() != 2:
                return None
            a = array.array("h")
            a.frombytes(w.readframes(min(w.getnframes(), 16000 * 60)))
        if _sys.byteorder == "big":
            a.byteswap()
        return (max(abs(v) for v in a) / 32767) if a else 0.0
    except Exception:
        return None


def _no_words(path: str) -> str:
    """Why a SUCCESSFUL call came back with nothing. Measured, not guessed.

    An empty transcript used to be returned with `error=None`, which made `ok`
    False and left every caller with nothing to say: the UI printed
    "Transcription failed: None" and the self-test printed "transcript: ''
    error=None" and counted it a pass. The connection working and the model
    hearing words are two different claims, and only the second one was ever in
    doubt. So when the words are missing, say which of the few possible reasons
    it is - all of them are things the file itself can be asked.
    """
    rate, channels, dur = _wav_specs(path)
    peak = _level(path)
    facts = []
    if dur is not None:
        facts.append(f"{dur:.1f}s")
    if rate:
        facts.append(f"{rate} Hz")
    if channels:
        facts.append(f"{channels} channel{'s' if channels > 1 else ''}")
    if peak is not None:
        facts.append(f"peak {peak:.0%} of full scale")
    detail = ", ".join(facts) or "not readable as a WAV"

    if dur is not None and dur < 0.35:
        why = "too short to contain a word"
    elif peak is not None and peak < 0.02:
        why = "effectively silent - check the microphone, or the file"
    elif rate and rate not in _SANE_RATES:
        why = f"{rate} Hz is an unusual sample rate; 16000 is what the model wants"
    elif dur is None:
        why = ("not a 16-bit WAV, so the encoding sent with it may have been wrong")
    else:
        why = (f"no recognisable speech in it - a tone, noise, or speech in a "
               f"language other than {ASR_LANGUAGE}")
    return (f"the service returned no words ({detail}): {why}. "
            f"The connection and the key were fine.")


class _Streamed:
    """Gives a streamed result the shape offline_recognize() returns.

    The caller iterates `response.results` and reads `.alternatives`; a streaming
    call hands back many responses each holding results. Collecting the final ones
    into this means the parsing below stays one code path.
    """

    def __init__(self, results: list):
        self.results = results


def _recognize(service, config, audio_path: str):
    """-> (response, source). Offline first, streaming when offline is refused.

    The hosted NVCF Parakeet function does not serve batch recognition:

        INVALID_ARGUMENT: Unavailable model requested given these parameters:
        language_code=en; sample_rate=16000; type=offline;

    `type=offline` is the whole of it. The `language_code=en` in that message is a
    red herring - the service normalises to the base language before composing the
    error, and sending en-GB returns the identical text - so do not go looking at
    ASR_LANGUAGE when you see it.

    Offline is still tried first, because a LOCAL Riva or Parakeet NIM does serve
    it and it is one round trip rather than a stream. Only that specific rejection
    falls through; any other failure is raised, so a bad key or a dead endpoint
    still reports itself instead of being retried down a second path.
    """
    try:
        with open(audio_path, "rb") as fh:
            return service.offline_recognize(fh.read(), config), "grpc"
    except Exception as e:
        if "type=offline" not in str(e):
            raise

    import riva.client
    s_config = riva.client.StreamingRecognitionConfig(config=config,
                                                      interim_results=False)
    # 16000 frames is one second at 16 kHz. Chunk size changes how many messages
    # cross the wire, not the transcript.
    finals: list = []
    with riva.client.AudioChunkFileIterator(audio_path, 16000) as chunks:
        for resp in service.streaming_response_generator(
                audio_chunks=chunks, streaming_config=s_config):
            for result in resp.results:
                if result.is_final and result.alternatives:
                    finals.append(result)
    return _Streamed(finals), "grpc-stream"


def _transcribe_grpc(audio_path: str, language: str, dur: float | None) -> Transcript:
    try:
        import riva.client
    except ImportError:
        return Transcript("", duration_s=dur, source="grpc", error=INSTALL_HINT)
    try:
        if ASR_USE_SSL:                 # hosted: the shared 40/min limiter applies
            _LIMITER.wait()
        auth = riva.client.Auth(
            uri=ASR_GRPC_SERVER, use_ssl=ASR_USE_SSL,
            metadata_args=[["function-id", ASR_FUNCTION_ID],
                           ["authorization", f"Bearer {api_key()}"]])
        service = riva.client.ASRService(auth)
        config = riva.client.RecognitionConfig(
            language_code=language, max_alternatives=1,
            enable_automatic_punctuation=True)
        try:
            # Reads the file's real encoding, rate and channel count.
            riva.client.add_audio_file_specs_to_config(config, audio_path)
        except Exception:
            rate, channels, _ = _wav_specs(audio_path)
            config.encoding = riva.client.AudioEncoding.LINEAR_PCM
            config.sample_rate_hertz = rate or 16000
            config.audio_channel_count = channels or 1
        response, _source = _recognize(service, config, audio_path)

        parts: list[str] = []
        confidence: float | None = None
        for result in response.results:
            if not result.alternatives:
                continue
            best = result.alternatives[0]
            parts.append(best.transcript)
            c = getattr(best, "confidence", None)
            if c is not None:
                confidence = c if confidence is None else min(confidence, c)
        text = " ".join(p.strip() for p in parts).strip()
        if not text:
            return Transcript("", confidence, dur, "grpc",
                              error=_no_words(audio_path))
        # _source, not "grpc": which transport produced the words is worth
        # knowing, and it is the only visible difference between a local NIM and
        # the hosted function.
        return Transcript(text, confidence, dur, _source)
    except Exception as e:
        # A gRPC failure carries its status in the exception text; keep enough of
        # it to tell an expired key from an unreachable server.
        return Transcript("", duration_s=dur, source="grpc",
                          error=f"{type(e).__name__}: {str(e)[:240]}")


def _transcribe_rest(audio_path: str, language: str, dur: float | None) -> Transcript:
    """For a NIM that serves ASR over HTTP. Not the hosted path."""
    try:
        _LIMITER.wait()
        with open(audio_path, "rb") as fh:
            r = httpx.post(ASR_BASE_URL,
                           headers={"Authorization": f"Bearer {api_key()}"},
                           files={"file": (os.path.basename(audio_path), fh,
                                           "audio/wav")},
                           data={"language": language}, timeout=120.0)
        r.raise_for_status()
        data = r.json()
        text = (data.get("text") or data.get("transcript")
                or " ".join(s.get("transcript", "")
                            for s in data.get("segments", []))).strip()
        if not text:
            return Transcript("", data.get("confidence"), dur, "rest",
                              error=_no_words(audio_path))
        return Transcript(text, data.get("confidence"), dur, "rest")
    except Exception as e:
        return Transcript("", duration_s=dur, source="rest",
                          error=f"{type(e).__name__}: {str(e)[:240]}")


def transcribe(audio_path: str, language: str | None = None) -> Transcript:
    """Transcribe a local audio file. Returns a Transcript, never raises."""
    if not audio_path or not os.path.exists(audio_path):
        return Transcript("", error=f"no audio file at {audio_path}")
    lang = language or ASR_LANGUAGE
    dur = _duration(audio_path)
    if ASR_BASE_URL:
        return _transcribe_rest(audio_path, lang, dur)
    return _transcribe_grpc(audio_path, lang, dur)


def health() -> dict:
    """Which ASR path is configured, and whether its client is importable."""
    try:
        import riva.client  # noqa: F401
        have_riva = True
    except ImportError:
        have_riva = False
    return {"mode": "rest" if ASR_BASE_URL else "grpc",
            "endpoint": ASR_BASE_URL or ASR_GRPC_SERVER,
            "function_id": None if ASR_BASE_URL else ASR_FUNCTION_ID,
            "language": ASR_LANGUAGE,
            "riva_client_installed": have_riva,
            "ready": have_riva or bool(ASR_BASE_URL)}
