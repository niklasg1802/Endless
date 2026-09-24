"""Text LLM client.

Prefers a local OpenAI-compatible endpoint (ultra-zen's translation proxy) so
text work runs on a subscription instead of metered API credits, and falls back
to OpenRouter when no local endpoint is configured.

ultra-zen serves an Anthropic -> OpenAI translation proxy:

    ultra-zen --proxy-only <model>        # 127.0.0.1:<free port>
    ultra-zen --port 8787 <model>         # pin a port

Its endpoints are /v1/messages, /v1/models, /v1/usage and /health. It is a
CHAT-COMPLETIONS bridge only -- it has no image endpoint, and it replaces
incoming images with the text "[image omitted]". So it is usable for text
(writers' room, shot lists, prompts, critique) and never for keyframes; image
generation goes to a local model instead (see comfy.py / scene.py).

Point the pipeline at it with:

    export ENDLESS_LLM_BASE_URL=http://127.0.0.1:<port>/v1
    export ENDLESS_LLM_MODEL=<model-id>
"""

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 300


def base_url():
    """OpenAI-compatible base URL, or None when only OpenRouter is available."""
    return os.environ.get("ENDLESS_LLM_BASE_URL") or None


def model_name():
    return os.environ.get("ENDLESS_LLM_MODEL") or "grok-4.5"


class LLMError(RuntimeError):
    pass


def _post(url, payload, headers, timeout=DEFAULT_TIMEOUT):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code} from {url}: {e.read().decode(errors='replace')[:600]}") from None
    except urllib.error.URLError as e:
        raise LLMError(f"cannot reach {url}: {e.reason}") from None


def complete(prompt, system=None, model=None, json_mode=False, temperature=None):
    """One-shot completion. Returns (text, usage).

    Uses the local ultra-zen proxy when ENDLESS_LLM_BASE_URL is set, otherwise
    OpenRouter.
    """
    base = base_url()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    if base:
        payload = {"model": model or model_name(), "messages": messages}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if temperature is not None:
            payload["temperature"] = temperature
        resp = _post(base.rstrip("/") + "/chat/completions", payload, {})
        text = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return text, resp.get("usage", {})

    # OpenRouter fallback. Kept for when no local proxy is running; note that
    # this path costs money and needs OPENROUTER_API_KEY in .env.
    from pipeline import openrouter  # local import: only needed on this path
    payload = {"model": model or "anthropic/claude-sonnet-5", "messages": messages}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if temperature is not None:
        payload["temperature"] = temperature
    resp = openrouter.request(openrouter.CHAT_API, openrouter.api_key(), payload)
    text = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return text, resp.get("usage", {})


def available():
    """True when some backend is configured."""
    if base_url():
        return True
    return _openrouter_key_present()


def _openrouter_key_present():
    """True if OpenRouter is usable. Never exits -- api_key() raises SystemExit."""
    try:
        from pipeline import openrouter
        openrouter.api_key()
        return True
    except SystemExit:
        return False
    except Exception:
        return False


def describe():
    if base_url():
        return f"local proxy {base_url()} (model {model_name()})"
    if _openrouter_key_present():
        return "OpenRouter (metered)"
    return "none configured -- set ENDLESS_LLM_BASE_URL, or add OPENROUTER_API_KEY to .env"


if __name__ == "__main__":
    print(describe(), file=sys.stderr)
    if not available():
        raise SystemExit(1)
    txt, usage = complete("Reply with exactly: OK")
    print(txt.strip())
    print(usage, file=sys.stderr)
