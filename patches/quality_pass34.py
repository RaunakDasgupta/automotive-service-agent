#!/usr/bin/env python3
"""Thirty-fourth pass: the hosted ASR never served the call we were making.

Run from the project root:   .venv/bin/python quality_pass34.py

WHAT WAS ACTUALLY WRONG

Transcription has never worked end to end in this project. The reason turns out
to be one word in a server response:

    INVALID_ARGUMENT: Error: Unavailable model requested given these parameters:
    language_code=en; sample_rate=16000; type=offline;

`type=offline`. The NVCF Parakeet function serves STREAMING recognition only, and
`_transcribe_grpc` called `service.offline_recognize()`. The request was well
formed, authenticated and delivered; the service simply does not offer batch
recognition for this model.

Verified by doing it the other way, against the same function id, the same key and
the same audio:

    streaming:  OK, final segments: 1
    transcript: Update for repair order R02608165, front pad thickness at
                1.8 mm against a three millimeter minimum.

So the fix is a fallback, not a rewrite: try offline (a LOCAL Riva or Parakeet NIM
does serve it, and it is one round trip instead of a stream), and on that specific
rejection, stream instead.

THE LANGUAGE CODE IS A RED HERRING

The error names `language_code=en` while the config sends `en-US`, which looks
like the bug and is not. Sending `en-GB` produces the identical message, still
saying `en`: the service normalises to the base language before it composes the
error. Anyone reading that message will lose an hour to it, so the reason is now
written next to the code.

AND THE DIAGNOSTIC BLAMED THE NETWORK

scripts/test_asr.py printed:

    Never reached the service. Check egress to grpc.nvcf.nvidia.com:443 on 443.

about a request that reached the service and got an argument error back. It
branches on `"unavailable" in low`, and the server's own words were "Unavailable
MODEL requested" - the adjective belongs to the model, not the connection. A
substring match against prose, which is the same mistake this project keeps
making in its checks, this time in its error handling. INVALID_ARGUMENT is now
told apart from a transport failure, and named for what it is.
"""
import sys, pathlib, ast, subprocess

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


# ==================== 1. stream when offline is refused
edit('app/pipeline/asr.py',
     '''def _transcribe_grpc(audio_path: str, language: str, dur: float | None) -> Transcript:
''',
     '''class _Streamed:
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
''',
     'asr.py  _recognize: stream when the service refuses offline',
     skip_if='def _recognize(')

edit('app/pipeline/asr.py',
     '''        with open(audio_path, "rb") as fh:
            response = service.offline_recognize(fh.read(), config)
''',
     '''        response, _source = _recognize(service, config, audio_path)
''',
     'asr.py  route the call through it',
     skip_if='response, _source = _recognize(')

edit('app/pipeline/asr.py',
     '''        return Transcript(text, confidence, dur, "grpc")''',
     '''        # _source, not "grpc": which transport produced the words is worth
        # knowing, and it is the only visible difference between a local NIM and
        # the hosted function.
        return Transcript(text, confidence, dur, _source)''',
     'asr.py  report which transport answered',
     skip_if='return Transcript(text, confidence, dur, _source)')


# ==================== 2. stop blaming the network for an argument error
edit('scripts/test_asr.py',
     '''        elif "unavailable" in low or "deadline" in low:
            print("\\n  Never reached the service. Check egress to "
                  f"{h['endpoint']} on 443.")
''',
     '''        elif "type=offline" in low or "unavailable model" in low:
            print("\\n  The service was REACHED and refused the parameters: it "
                  "does not\\n  serve offline/batch recognition for this model. "
                  "Streaming works -\\n  app/pipeline/asr.py falls back to it, so "
                  "seeing this means the\\n  fallback itself failed.")
            print("\\n  Note: the `language_code=en` in that message is not the "
                  "problem.\\n  The service normalises to the base language; "
                  "en-GB returns the same.")
        elif "invalid_argument" in low:
            print("\\n  The service was reached and rejected the request. This is "
                  "an\\n  argument error, not a connection problem - read the "
                  "parameters it\\n  echoed back above.")
        elif "unavailable" in low or "deadline" in low:
            # Ordering matters: the server says "Unavailable MODEL requested" for
            # a perfectly delivered request, and matching "unavailable" first made
            # this print "never reached the service" about a service that answered.
            print("\\n  Never reached the service. Check egress to "
                  f"{h['endpoint']} on 443.")
''',
     'test_asr.py  an argument error is not a network failure',
     skip_if='The service was REACHED and refused the parameters')


# ==================== verify
print("Quality pass 34:")
for c in CHANGES:
    print(c)

bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}" + (f"  ({detail})" if detail else ""))


print("\nthe code:")
a = (ROOT / "app/pipeline/asr.py").read_text()
t = (ROOT / "scripts/test_asr.py").read_text()
ast.parse(a)
ast.parse(t)
chk("both files parse", True)
chk("offline is still tried first",
    a.index("offline_recognize") < a.index("streaming_response_generator"),
    "a local NIM serves it in one round trip")
chk("only the offline rejection falls through",
    'if "type=offline" not in str(e):' in a and "raise" in a,
    "a bad key must not be retried down a second path")
chk("the streamed result is reshaped, not special-cased",
    "class _Streamed" in a and "self.results = results" in a)
chk("the transport is reported", "dur, _source)" in a)
# `service.offline_recognize(` - the CALL. Counting the bare name found two,
# because _Streamed's docstring mentions the function it is shaped after. That is
# the fifth time in this project that a check has asserted the prose beside the
# code instead of the code (29, 30, 31, 33, here). Match syntax, never vocabulary.
_calls = a.count("service.offline_recognize(")
chk("only the helper calls offline_recognize", _calls == 1, f"{_calls} call sites")

print("\nthe diagnostic:")
# Order is the whole point: "Unavailable model" must be matched before the
# generic "unavailable", or the network branch wins again.
i_off = t.index('"type=offline" in low')
i_unav = t.index('elif "unavailable" in low')
chk("the offline branch comes before the transport branch", i_off < i_unav,
    "otherwise 'unavailable' matches the server's own wording first")
chk("INVALID_ARGUMENT has its own branch", '"invalid_argument" in low' in t)
chk("it says the service was reached", "The service was REACHED" in t)
chk("it warns that the language code is a red herring",
    "not the \\n  problem" in t or "is not the " in t)

print("\nend to end (needs update.wav and a key):")
if (ROOT / "update.wav").exists():
    try:
        sys.path.insert(0, ".")
        from app.pipeline.asr import transcribe
        r = transcribe("update.wav")
        chk("a transcript came back", bool(r.text), r.error or "")
        chk("it came from the streaming path", r.source == "grpc-stream", r.source)
        low = (r.text or "").lower()
        chk("it contains the measurement", "1.8" in low or "one point eight" in low,
            (r.text or "")[:90])
    except Exception as e:
        chk("transcribe() ran", False, f"{type(e).__name__}: {str(e)[:90]}")
else:
    print("  note    no update.wav here - make one with `say` on a Mac:")
    print("          say --file-format=WAVE --data-format=LEI16@16000 -o update.wav \"...\"")

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
    .venv/bin/python scripts/test_asr.py --wav update.wav
""")
sys.exit(1 if bad else 0)
