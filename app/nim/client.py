"""One interface over the NVIDIA model endpoints, local or hosted.

Every model has two possible homes: a NIM container on this box, or the hosted
endpoint at build.nvidia.com. Selection is per-model and config-driven, so the
app runs unchanged on a GPU box, on a CPU box pointed at a remote NIM host, or
entirely on hosted inference while the containers are still downloading.

Hosted inference is rate limited to ~40 requests/minute on the free tier, so all
calls go through a shared limiter with retry and exponential backoff.
"""
from __future__ import annotations
import os, time, threading, json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx

HOSTED_BASE = "https://integrate.api.nvidia.com/v1"
HOSTED_ASR = "https://ai.api.nvidia.com/v1/speech"

# Local NIM ports, matching scripts/start_nims.sh
LOCAL = {"llm": "http://localhost:8000/v1",
         "embed": "http://localhost:8001/v1",
         "rerank": "http://localhost:8002/v1"}

# Model ids differ between the hosted catalog and a local container.
# Model ids are configuration, not code. `nvidia/nv-embedqa-e5-v5` reached end of
# life on 2026-08-25 and the hosted endpoint now answers
#
#     HTTP 410 ... "has reached its end of life ... no longer available"
#
# which stopped the index building until this file changed. A hosted catalogue
# retires models on its own schedule; an override that needs an edit and a
# redeploy is an outage waiting for a date. Every id can now be set from the
# environment, so the next retirement is a variable, not a patch.
#
# As of 2026-09-29 the hosted catalogue lists seven embedding models and NO
# reranking model at all - every `/v1/retrieval/<model>/reranking` path 404s.
# `search()` already degrades to vector-only and flags `rerank_error` when the
# reranker is unreachable, so retrieval keeps working and says that it is
# working with one stage instead of two. To get the stage back, run the rerank
# NIM on the box: scripts/start_nims.sh, then NIM_MODE_RERANK=local.
def _model(service: str, where: str, default: str) -> str:
    return os.environ.get(f"NIM_MODEL_{service.upper()}_{where.upper()}", default)


MODELS = {
    "llm":    {"hosted": _model("llm", "hosted",
                                "nvidia/llama-3.1-nemotron-nano-8b-v1"),
               "local":  _model("llm", "local",
                                "nvidia/llama-3.1-nemotron-nano-8b-v1")},
    # nemotron-3-embed-1b is 2048-dimensional, where nv-embedqa-e5-v5 was 1024.
    # Nothing hardcodes the width - the vector store takes it from the data at
    # build time - but an index built before this change cannot be searched
    # after it, and index_staleness will not notice, because the ids and counts
    # still match. Rebuild after changing the embedding model.
    "embed":  {"hosted": _model("embed", "hosted", "nvidia/nemotron-3-embed-1b"),
               "local":  _model("embed", "local", "nvidia/nv-embedqa-e5-v5")},
    "rerank": {"hosted": _model("rerank", "hosted",
                                "nvidia/nv-rerankqa-mistral-4b-v3"),
               "local":  _model("rerank", "local",
                                "nvidia/nv-rerankqa-mistral-4b-v3")},
}


class RateLimiter:
    """Token bucket. The hosted free tier allows ~40 req/min."""
    def __init__(self, per_minute: int = 38):
        self.interval = 60.0 / max(1, per_minute)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            if now < self._next:
                time.sleep(self._next - now)
                now = time.monotonic()
            self._next = now + self.interval


_LIMITER = RateLimiter(int(os.environ.get("NIM_RPM", "38")))


def api_key() -> str:
    k = os.environ.get("NVIDIA_API_KEY") or os.environ.get("NGC_API_KEY")
    if not k:
        raise RuntimeError("NVIDIA_API_KEY is not set (put it in .env)")
    return k


def _mode(service: str) -> str:
    """'local' or 'hosted' for one service. NIM_MODE sets the default."""
    return os.environ.get(f"NIM_MODE_{service.upper()}",
                          os.environ.get("NIM_MODE", "auto")).lower()


def _is_up(base: str, timeout: float = 1.5) -> bool:
    try:
        return httpx.get(f"{base}/models", timeout=timeout).status_code == 200
    except Exception:
        return False


_resolved: dict[str, tuple[str, str, str]] = {}


def resolve(service: str) -> tuple[str, str, str]:
    """-> (base_url, model_id, mode). Cached; 'auto' prefers a healthy local NIM."""
    if service in _resolved:
        return _resolved[service]
    if service == "llm":
        # The router returns (base_url, ROUTE id) and the route id goes where a
        # model id normally would, which is why chat() needs no change: the proxy
        # speaks openai_chat and picks the target itself. None means routing is off
        # or has disabled itself, and then this falls through to the NIM as before.
        try:
            from app.routing import switchyard as _sy
            _ep = _sy.endpoint()
        except Exception:
            _ep = None
        if _ep is not None:
            out = (_ep[0], _ep[1], "switchyard")
            _resolved[service] = out
            return out
    m = _mode(service)
    if m == "auto":
        m = "local" if _is_up(LOCAL[service]) else "hosted"
    base = LOCAL[service] if m == "local" else HOSTED_BASE
    out = (base, MODELS[service][m], m)
    _resolved[service] = out
    return out


def reset_resolution():
    _resolved.clear()


def _is_loopback(mode: str) -> bool:
    """Does this endpoint need no Authorization header from us?

    "local" obviously not. "switchyard" also not, and for a reason worth stating:
    the proxy runs on 127.0.0.1 and holds its own credentials - it adds the hosted
    key itself, from api_key_env, on the one hop that escalates. Sending our Bearer
    to loopback would be pointless at best, and at worst would put the key on a hop
    that never asked for it.
    """
    return mode in ("local", "switchyard")


def _headers(local: bool) -> dict:
    h = {"Content-Type": "application/json"}
    if not local:
        h["Authorization"] = f"Bearer {api_key()}"
    return h


def _post(url: str, payload: dict, local: bool, timeout: float = 120.0,
          retries: int = 4) -> dict:
    last = None
    for attempt in range(retries):
        if not local:
            _LIMITER.wait()
        try:
            from app.obs import metrics as _M
            with _M.nim_call(url):
                r = httpx.post(url, json=payload, headers=_headers(local),
                               timeout=timeout)
            if r.status_code == 429:                       # rate limited - back off
                time.sleep(2 ** attempt * 1.5)
                last = RuntimeError("429 rate limited")
                continue
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            # The body is the only thing that says what was wrong with the
            # request, and it was being discarded in favour of a bare status code.
            last = RuntimeError(f"HTTP {e.response.status_code}: "
                                f"{e.response.text[:500]}")
            if e.response.status_code == 400:
                raise last          # a malformed payload: retrying cannot help
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{url} failed after {retries} attempts: {last}")


# ----------------------------------------------------------------- chat
def chat(messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024,
         json_mode: bool = False, stop: list[str] | None = None,
         meta: dict | None = None) -> str:
    """Complete a chat turn, and record it as a span. The work is in _chat_inner.

    Split in two so that the span wraps the whole call including its retries, and
    so that _chat_inner stays exactly what it was. `meta` is read AFTER the inner
    call because that is when it has been filled in - finish_reason is the field
    that says whether the text stops mid-sentence.
    """
    from app.obs import trace as _trace
    _base, _model, _mode = resolve("llm")
    with _trace.llm_span("chat", {"model": _model, "mode": _mode,
                                  "messages": messages,
                                  "temperature": temperature,
                                  "max_tokens": max_tokens}, _model) as _span:
        out = _chat_inner(messages, temperature, max_tokens, json_mode, stop, meta)
        _span["result"] = {"content": out, "meta": _trace._plain(meta or {})}
        return out


def _chat_inner(messages: list[dict], temperature: float = 0.0,
                max_tokens: int = 1024, json_mode: bool = False,
                stop: list[str] | None = None, meta: dict | None = None) -> str:
    """Complete a chat turn.

    Pass `meta` to learn how the completion ended. `finish_reason == "length"`
    means the model ran into max_tokens and the text stops mid-sentence - which
    was previously thrown away with the rest of the response envelope, so a
    truncated answer was indistinguishable from a finished one.
    """
    base, model, mode = resolve("llm")
    payload: dict[str, Any] = {"model": model, "messages": messages,
                               "temperature": temperature, "max_tokens": max_tokens}
    if stop:
        payload["stop"] = stop
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    data = _post(f"{base}/chat/completions", payload, local=_is_loopback(mode))
    choice = data["choices"][0]
    if meta is not None:
        meta["finish_reason"] = choice.get("finish_reason")
        usage = data.get("usage") or {}
        meta["prompt_tokens"] = usage.get("prompt_tokens")
        meta["completion_tokens"] = usage.get("completion_tokens")
    return choice["message"]["content"]


def chat_stream(messages: list[dict], temperature: float = 0.0,
                max_tokens: int = 1024, timeout: float = 120.0,
                meta: dict | None = None):
    """Yield the narration as it is generated.

    Same request as chat() with stream=true, parsed from the server-sent event
    stream. Deliberately not retried: half a response has already been shown to
    the reader, so a retry would restart the text in front of them. The caller
    falls back to chat() if this raises before yielding anything.
    """
    base, model, mode = resolve("llm")
    local = _is_loopback(mode)
    if not local:
        _LIMITER.wait()
    payload: dict[str, Any] = {"model": model, "messages": messages,
                               "temperature": temperature,
                               "max_tokens": max_tokens, "stream": True}
    with httpx.stream("POST", f"{base}/chat/completions", json=payload,
                      headers=_headers(local), timeout=timeout) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                return
            try:
                frame = json.loads(body)
                choice = frame["choices"][0]
            except Exception:
                continue            # a keep-alive or a partial frame
            if meta is not None:
                # The last frame carries the reason; usage arrives only if the
                # server was asked for it, so treat both as optional.
                if choice.get("finish_reason"):
                    meta["finish_reason"] = choice["finish_reason"]
                usage = frame.get("usage") or {}
                if usage:
                    meta["prompt_tokens"] = usage.get("prompt_tokens")
                    meta["completion_tokens"] = usage.get("completion_tokens")
            piece = (choice.get("delta") or {}).get("content")
            if piece:
                yield piece


# ----------------------------------------------------------------- embed
@lru_cache(maxsize=512)
def _embed_query_cached(text: str) -> tuple[float, ...]:
    return tuple(embed([text], input_type="query")[0])


def embed_query(text: str) -> list[float]:
    """Embed one search query, caching the result.

    The same question asked twice produces the same vector, so the second round
    trip to the embedding NIM buys nothing. A demo asks a handful of questions
    repeatedly, which makes this most of the embedding traffic.

    Query side only. Passage embedding happens once at index build time, where a
    cache would only consume memory, and where a stale hit would be a correctness
    bug rather than a saving.
    """
    return list(_embed_query_cached(text))


def embed(texts: list[str], input_type: str = "passage") -> list[list[float]]:
    base, model, mode = resolve("embed")
    payload = {"model": model, "input": texts, "input_type": input_type,
               "encoding_format": "float", "truncate": "END"}
    data = _post(f"{base}/embeddings", payload, local=(mode == "local"))
    return [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]


# ----------------------------------------------------------------- rerank
def rerank(query: str, passages: list[str], top_n: int | None = None) -> list[dict]:
    base, model, mode = resolve("rerank")
    payload = {"model": model, "query": {"text": query},
               "passages": [{"text": p} for p in passages]}
    url = (f"{base}/ranking" if mode == "local"
           else f"{HOSTED_BASE}/retrieval/{model}/reranking")
    data = _post(url, payload, local=(mode == "local"))
    rank = data.get("rankings", [])
    out = [{"index": r["index"], "score": r.get("logit", r.get("score", 0.0))} for r in rank]
    return out[:top_n] if top_n else out


def health() -> dict:
    out = {}
    for svc in ("llm", "embed", "rerank"):
        base, model, mode = resolve(svc)
        out[svc] = {"mode": mode, "base": base, "model": model,
                    "reachable": _is_up(base) if mode == "local" else True}
    return out
