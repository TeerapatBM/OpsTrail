"""Optional LLM providers for the web UI's "AI write" button (stdlib HTTP only).

Providers:
  anthropic  – Claude Messages API (https://api.anthropic.com)
  openai     – any OpenAI-compatible Chat Completions endpoint (OpenAI, Ollama, LM Studio, vLLM, …)
  azure      – Azure OpenAI deployment (data stays in your tenant)
  none       – disabled (the web UI still offers Copy prompt / Paste result)

Settings live in ~/.opstrail/llm.json (written by the web Settings page). The API key is stored
DPAPI-encrypted on Windows, or taken from OPSTRAIL_LLM_API_KEY / provider env vars.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from opstrail.config import Config
from opstrail.secretstore import SecretError, protect, unprotect

PROVIDERS = ("none", "anthropic", "openai", "azure")
DEFAULT_MODELS = {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4.1", "azure": ""}
DEFAULT_BASE = {"anthropic": "https://api.anthropic.com", "openai": "https://api.openai.com/v1"}
PROVIDER_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "azure": "AZURE_OPENAI_API_KEY"}
TIMEOUT_S = 240


class LLMError(RuntimeError):
    pass


@dataclass
class LLMSettings:
    provider: str = "none"
    model: str = ""
    base_url: str = ""
    azure_endpoint: str = ""
    azure_deployment: str = ""
    azure_api_version: str = "2024-10-21"
    anthropic_workspace_id: str = ""  # needed for multi-workspace ("all workspaces") personal/service keys
    max_tokens: int = 16000


@dataclass
class LLMResult:
    text: str
    label: str
    truncated: bool = False


def _path(cfg: Config):
    return cfg.home / "llm.json"


def _read(cfg: Config) -> dict[str, Any]:
    path = _path(cfg)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def _profile_data(cfg: Config, profile: str) -> dict[str, Any]:
    if profile not in ("writer", "reviewer"):
        raise LLMError("ไม่พบ profile AI")
    data = _read(cfg)
    selected = data if profile == "writer" else data.get("reviewer", {})
    return selected if isinstance(selected, dict) else {}


def load_settings(cfg: Config, *, profile: str = "writer") -> LLMSettings:
    data = _profile_data(cfg, profile)
    s = LLMSettings()
    for key in asdict(s):
        if key in data and data[key] not in (None, ""):
            setattr(s, key, data[key])
    if s.provider not in PROVIDERS:
        s.provider = "none"
    try:
        s.max_tokens = max(1000, min(int(s.max_tokens), 64000))
    except (TypeError, ValueError):
        s.max_tokens = 16000
    return s


def save_settings(cfg: Config, values: dict[str, Any], api_key: str | None = None,
                  *, profile: str = "writer") -> dict[str, Any]:
    """Persist settings. api_key: None = keep the stored key, "" = remove it, text = store (encrypted)."""
    current = _profile_data(cfg, profile)
    s = LLMSettings()
    out: dict[str, Any] = {}
    for key, default in asdict(s).items():
        value = values.get(key, current.get(key, default))
        out[key] = value
    if out["provider"] not in PROVIDERS:
        raise LLMError(f"provider must be one of {', '.join(PROVIDERS)}")
    if api_key is None:
        if current.get("api_key"):
            out["api_key"] = current["api_key"]
    elif api_key.strip():
        try:
            out["api_key"] = protect(api_key.strip())
        except SecretError as exc:
            raise LLMError(f"{exc} – set the OPSTRAIL_LLM_API_KEY environment variable instead") from exc
    path = _path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    root = _read(cfg)
    if profile == "reviewer":
        root["reviewer"] = out
    else:
        if "reviewer" in root:
            out["reviewer"] = root["reviewer"]
        root = out
    path.write_text(json.dumps(root, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return public_settings(cfg, profile=profile)


def api_key(cfg: Config, s: LLMSettings | None = None, *, profile: str = "writer") -> tuple[str, str]:
    """(key, source) – source is 'stored', an env var name, or '' when missing."""
    s = s or load_settings(cfg, profile=profile)
    stored = _profile_data(cfg, profile).get("api_key")
    if stored:
        try:
            return unprotect(stored), "stored"
        except (SecretError, ValueError):
            pass
    generic_env = "OPSTRAIL_REVIEWER_API_KEY" if profile == "reviewer" else "OPSTRAIL_LLM_API_KEY"
    for env in (generic_env, PROVIDER_ENV.get(s.provider, "")):
        if env and os.environ.get(env):
            return os.environ[env], env
    return "", ""


def public_settings(cfg: Config, *, profile: str = "writer") -> dict[str, Any]:
    s = load_settings(cfg, profile=profile)
    _, source = api_key(cfg, s, profile=profile)
    data = asdict(s)
    stored = str(_profile_data(cfg, profile).get("api_key") or "")
    data.update(
        {
            "has_key": bool(source),
            "key_source": source,
            "key_protection": stored.split(":", 1)[0] if source == "stored" else "",
            "effective_model": _model(s),
            "providers": list(PROVIDERS),
            "default_models": DEFAULT_MODELS,
            "ready": s.provider != "none" and (bool(source) or _local_endpoint(s)),
        }
    )
    return data


def _local_endpoint(s: LLMSettings) -> bool:
    return s.provider == "openai" and bool(re.match(r"https?://(localhost|127\.0\.0\.1)", s.base_url or ""))


def _model(s: LLMSettings) -> str:
    if s.provider == "azure":
        return s.azure_deployment
    return s.model or DEFAULT_MODELS.get(s.provider, "")


def _request(method: str, url: str, headers: dict[str, str], body: dict | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        try:
            parsed = json.loads(detail)
            err = parsed.get("error")
            detail = (err.get("message") if isinstance(err, dict) else err) or detail
        except (json.JSONDecodeError, AttributeError):
            pass
        hint = WORKSPACE_HINT if "anthropic-workspace-id" in str(detail) else ""
        raise LLMError(f"HTTP {exc.code} from {url.split('?')[0]}: {detail}{hint}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"cannot reach {url.split('?')[0]}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise LLMError(f"timeout after {TIMEOUT_S}s calling {url.split('?')[0]}") from exc


def _anthropic_headers(s: LLMSettings, key: str) -> dict[str, str]:
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    workspace = (s.anthropic_workspace_id or "").strip()
    if workspace:
        headers["anthropic-workspace-id"] = workspace
    return headers


WORKSPACE_HINT = (
    " → API key นี้ใช้ได้หลาย workspace ต้องระบุ Workspace ID: ไปที่ Claude Console → Settings → Workspaces "
    "ก๊อป ID ที่ขึ้นต้นด้วย wrkspc_ มาใส่ช่อง “Workspace ID” ในหน้าตั้งค่า (หรือสร้าง API key ใหม่ที่ผูกกับ workspace เดียว)"
)


def _endpoint(s: LLMSettings) -> str:
    return (s.base_url or DEFAULT_BASE.get(s.provider, "")).rstrip("/")


def complete(cfg: Config, system: str, user: str, *, profile: str = "writer") -> LLMResult:
    s = load_settings(cfg, profile=profile)
    if s.provider == "none":
        raise LLMError("no AI provider configured – open Settings in the web UI (or use Copy prompt)")
    key, _ = api_key(cfg, s, profile=profile)
    if not key and not _local_endpoint(s):
        raise LLMError("API key missing – add it in Settings or set OPSTRAIL_LLM_API_KEY")
    model = _model(s)

    if s.provider == "anthropic":
        res = _request(
            "POST",
            f"{_endpoint(s)}/v1/messages",
            _anthropic_headers(s, key),
            {
                "model": model,
                "max_tokens": s.max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        text = "".join(b.get("text", "") for b in res.get("content", []) if b.get("type") == "text")
        return LLMResult(text, f"anthropic:{res.get('model', model)}", res.get("stop_reason") == "max_tokens")

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if s.provider == "azure":
        if not s.azure_endpoint or not s.azure_deployment:
            raise LLMError("Azure OpenAI needs endpoint and deployment name")
        url = (
            f"{s.azure_endpoint.rstrip('/')}/openai/deployments/{s.azure_deployment}/chat/completions"
            f"?api-version={s.azure_api_version}"
        )
        res = _request("POST", url, {"api-key": key}, {"messages": messages})
        label = f"azure:{s.azure_deployment}"
    else:
        headers = {"authorization": f"Bearer {key}"} if key else {}
        res = _request("POST", f"{_endpoint(s)}/chat/completions", headers, {"model": model, "messages": messages})
        label = f"openai:{res.get('model', model)}"
    try:
        choice = res["choices"][0]
        text = choice["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected response: {str(res)[:300]}") from exc
    return LLMResult(text, label, choice.get("finish_reason") == "length")


def _sse(url: str, headers: dict[str, str], body: dict) -> Iterator[dict | str]:
    """Read complete SSE data frames, not network chunks (including split UTF-8)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={**headers, "content-type": "application/json", "accept": "text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            if "text/event-stream" not in resp.headers.get("content-type", ""):
                raise LLMError("ผู้ให้บริการไม่รองรับ streaming (ต้องเป็น text/event-stream)")
            lines: list[str] = []
            for raw in resp:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line.startswith("data:"):
                    lines.append(line[5:].removeprefix(" "))
                elif not line and lines:
                    data = "\n".join(lines)
                    lines.clear()
                    if data == "[DONE]":
                        yield data
                    else:
                        value = json.loads(data)
                        if not isinstance(value, dict):
                            raise LLMError("รูปแบบ streaming จากผู้ให้บริการไม่ถูกต้อง")
                        yield value
    except urllib.error.HTTPError as exc:
        # Do not echo upstream bodies: they may include credentials or prompt text.
        raise LLMError(f"ผู้ให้บริการ streaming ตอบ HTTP {exc.code}; ตรวจการตั้งค่า AI") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise LLMError("ติดต่อผู้ให้บริการ streaming ไม่สำเร็จหรือการเชื่อมต่อขาด") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LLMError("รูปแบบ streaming จากผู้ให้บริการไม่ถูกต้อง") from exc


def stream_complete(cfg: Config, system: str, user: str) -> Iterator[str | LLMResult]:
    """Yield text immediately, then exactly one result after the terminal frame."""
    s = load_settings(cfg)
    if s.provider == "none":
        raise LLMError("ยังไม่ได้ตั้งค่า AI — เปิดหน้าตั้งค่าหรือใช้ Copy prompt")
    key, _ = api_key(cfg, s)
    if not key and not _local_endpoint(s):
        raise LLMError("ไม่มี API key — เพิ่มในหน้าตั้งค่า")
    model = _model(s)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if s.provider == "anthropic":
        url = f"{_endpoint(s)}/v1/messages"
        headers = _anthropic_headers(s, key)
        body = {"model": model, "max_tokens": s.max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}], "stream": True}
    elif s.provider == "azure":
        if not s.azure_endpoint or not s.azure_deployment:
            raise LLMError("Azure OpenAI ต้องระบุ endpoint และ deployment")
        url = (f"{s.azure_endpoint.rstrip('/')}/openai/deployments/{s.azure_deployment}/chat/completions"
               f"?api-version={s.azure_api_version}")
        headers = {"api-key": key}
        body = {"messages": messages, "stream": True}
    else:
        url = f"{_endpoint(s)}/chat/completions"
        headers = {"authorization": f"Bearer {key}"} if key else {}
        body = {"model": model, "messages": messages, "stream": True}
    parts: list[str] = []
    truncated = False
    finished = False
    frames = _sse(url, headers, body)
    try:
        for frame in frames:
            if frame == "[DONE]":
                if s.provider != "anthropic" and finished:
                    break
                raise LLMError("streaming จบก่อนคำตอบสมบูรณ์")
            if not isinstance(frame, dict):
                raise LLMError("รูปแบบ streaming ไม่ถูกต้อง")
            if frame.get("error") or frame.get("type") == "error":
                raise LLMError("ผู้ให้บริการ AI แจ้งข้อผิดพลาดระหว่าง streaming — ลองใหม่อีกครั้ง")
            text = ""
            if s.provider == "anthropic":
                kind = frame.get("type")
                if kind == "message_start":
                    model = frame.get("message", {}).get("model", model)
                elif kind == "content_block_delta" and frame.get("delta", {}).get("type") == "text_delta":
                    text = frame["delta"].get("text", "")
                elif kind == "message_delta":
                    reason = frame.get("delta", {}).get("stop_reason")
                    if reason:
                        if reason not in ("end_turn", "stop_sequence", "max_tokens"):
                            raise LLMError("AI หยุดโดยยังไม่ได้เอกสารสมบูรณ์ — ยังไม่ได้บันทึกเวอร์ชันใหม่")
                        finished = True
                        truncated = reason == "max_tokens"
                elif kind == "message_stop":
                    if not finished:
                        raise LLMError("streaming จบก่อนคำตอบสมบูรณ์")
                    break
            else:
                model = frame.get("model") or model
                for choice in frame.get("choices", []):
                    if choice.get("index", 0) != 0:
                        continue
                    text = (choice.get("delta") or {}).get("content") or ""
                    reason = choice.get("finish_reason")
                    if reason:
                        if reason not in ("stop", "length"):
                            raise LLMError("AI หยุดโดยยังไม่ได้เอกสารสมบูรณ์ — ยังไม่ได้บันทึกเวอร์ชันใหม่")
                        finished = True
                        truncated = reason == "length"
            if text:
                if not isinstance(text, str):
                    raise LLMError("รูปแบบข้อความ streaming ไม่ถูกต้อง")
                parts.append(text)
                yield text
        else:
            # EOF without message_stop / [DONE] must never save a partial answer.
            raise LLMError("streaming ขาดก่อนจบ — ยังไม่ได้บันทึกเวอร์ชันใหม่")
    except (AttributeError, TypeError, KeyError, ValueError) as exc:
        raise LLMError("รูปแบบ streaming จากผู้ให้บริการไม่ถูกต้อง") from exc
    finally:
        frames.close()
    yield LLMResult("".join(parts), f"{s.provider}:{model}", truncated)


def list_models(cfg: Config) -> list[str]:
    """Used by Settings → Test connection."""
    s = load_settings(cfg)
    key, _ = api_key(cfg, s)
    if s.provider == "anthropic":
        res = _request("GET", f"{_endpoint(s)}/v1/models?limit=100", _anthropic_headers(s, key))
        return [m["id"] for m in res.get("data", []) if m.get("id")]
    if s.provider == "openai":
        headers = {"authorization": f"Bearer {key}"} if key else {}
        res = _request("GET", f"{_endpoint(s)}/models", headers)
        return sorted(m["id"] for m in res.get("data", []) if m.get("id"))
    if s.provider == "azure":
        # a tiny completion proves endpoint + deployment + key in one go
        complete(cfg, "Reply with OK.", "ping")
        return [s.azure_deployment]
    raise LLMError("no AI provider configured")


_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(markdown|md)?[ \t]*\n(.*)\n\1\s*$", re.S | re.I)


def strip_fences(text: str) -> str:
    """Remove a fence that wraps the *whole* answer (models sometimes do that)."""
    text = text or ""
    m = _FENCE.match(text)
    if m and (m.group(2) or not re.search(r"^\s*(```|~~~)", m.group(3), re.M)):
        text = m.group(3)
    return text.strip() + "\n"
