"""Local Ollama discovery and chat proxy for Windhover."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable

from chat_text import clean_chat_text


def is_ollama_model_id(model_id: str | None) -> bool:
    return bool(model_id) and str(model_id).startswith("ollama/")


def ollama_tag(model_id: str) -> str:
    """ollama/gemma4:latest → gemma4:latest"""
    return str(model_id)[len("ollama/") :].strip()


def ollama_url(path: str, host: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return f"{host.rstrip('/')}{path}"


def ollama_reachable(host: str, timeout: float = 0.6) -> bool:
    try:
        req = urllib.request.Request(ollama_url("/api/tags", host), method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def ollama_list_models(host: str, timeout: float = 1.5) -> list[dict]:
    """Return virtual installed entries for models already pulled into Ollama."""
    try:
        req = urllib.request.Request(ollama_url("/api/tags", host), method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return []
    out: list[dict] = []
    for m in data.get("models") or []:
        name = str(m.get("name") or m.get("model") or "").strip()
        if not name:
            continue
        size = int(m.get("size") or 0)
        details = m.get("details") or {}
        out.append(
            {
                "id": f"ollama/{name}",
                "name": name,
                "path": None,
                "ready": True,
                "engine": "ollama",
                "source": "ollama",
                "backend": "ollama",
                "chat": "ollama",
                "chat_mode": "ollama",
                "chat_ok": True,
                "impostor": False,
                "has_weights": True,
                "size_bytes": size,
                "weight_bytes": size,
                "family": "ollama",
                "description": f"Local Ollama model ({name})",
                "ollama_digest": m.get("digest"),
                "ollama_modified": m.get("modified_at") or m.get("modified"),
                "parameter_size": details.get("parameter_size"),
                "quantization": details.get("quantization_level"),
            }
        )
    out.sort(key=lambda x: str(x.get("id") or ""))
    return out


def ollama_chat(
    messages: list,
    max_tokens: int,
    temperature: float,
    *,
    model_tag: str,
    host: str,
    rss_mb: float = 0.0,
    stats_sink: Callable[[dict], None] | None = None,
) -> tuple[str, dict]:
    """Proxy chat to the local Ollama OpenAI-compatible API."""
    t0 = time.time()
    clean_msgs = [
        {"role": m.get("role") or "user", "content": m.get("content") or ""}
        for m in messages
        if (m.get("content") or "").strip() or (m.get("role") in ("assistant", "system"))
    ]
    text = ""
    err: str | None = None
    completion_tokens = 0
    attempts = (
        (
            "/v1/chat/completions",
            {
                "model": model_tag,
                "messages": clean_msgs,
                "stream": False,
                "temperature": float(temperature),
                "max_tokens": int(max_tokens),
            },
        ),
        (
            "/api/chat",
            {
                "model": model_tag,
                "messages": clean_msgs,
                "stream": False,
                "options": {
                    "temperature": float(temperature),
                    "num_predict": int(max_tokens),
                },
            },
        ),
    )
    for path, payload in attempts:
        body = json.dumps(payload).encode("utf-8")
        try:
            req = urllib.request.Request(
                ollama_url(path, host),
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=600) as resp:
                raw = json.loads(resp.read().decode("utf-8", errors="replace"))
            if path.startswith("/v1/"):
                choices = raw.get("choices") or []
                if choices:
                    msg = choices[0].get("message") or {}
                    text = str(msg.get("content") or "")
                usage = raw.get("usage") or {}
                completion_tokens = int(usage.get("completion_tokens") or 0)
            else:
                msg = raw.get("message") or {}
                text = str(msg.get("content") or raw.get("response") or "")
                completion_tokens = int(raw.get("eval_count") or 0)
            err = None
            break
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            err = f"Ollama HTTP {e.code}: {e.reason}" + (f" — {detail}" if detail else "")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
    dt = max(1e-6, time.time() - t0)
    if err and not text:
        stats = {
            "backend": "ollama",
            "error": err,
            "selected_model": f"ollama/{model_tag}",
            "preview_model": None,
            "latency_ms": round(dt * 1000, 1),
            "tokens_per_sec": 0.0,
            "completion_tokens": 0,
            "rss_mb": round(rss_mb, 1),
            "engine": "ollama",
        }
        if stats_sink:
            stats_sink(stats)
        return f"(ollama error: {err})", stats
    ntok = completion_tokens if completion_tokens > 0 else max(1, len((text or "").split()))
    stats = {
        "backend": "ollama",
        "selected_model": f"ollama/{model_tag}",
        "preview_model": model_tag,
        "family": "ollama",
        "latency_ms": round(dt * 1000, 1),
        "tokens_per_sec": round(ntok / dt, 2),
        "completion_tokens": ntok,
        "rss_mb": round(rss_mb, 1),
        "engine": "ollama",
    }
    if stats_sink:
        stats_sink(stats)
    return clean_chat_text(text) or "(empty ollama generation)", stats
