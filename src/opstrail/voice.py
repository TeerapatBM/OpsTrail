"""Opt-in microphone notes. No audio survives a completed capture attempt."""
from __future__ import annotations

import importlib
import json
import os
import tempfile
import threading
import uuid
import wave
from pathlib import Path
from urllib import request
from urllib.parse import quote, urlsplit

from opstrail.locks import file_lock
from opstrail.service import OpsTrailError

MAX_SECONDS = 60
SAMPLE_RATE = 16000
INSTALL_HINT = 'ยังไม่ได้ติดตั้ง voice: python -m pip install -e ".[voice]" แล้ว restart agent'


class VoiceError(OpsTrailError):
    pass


def _backend(cfg):
    backend = cfg.data.get("voice", {}).get("backend", "local")
    if backend not in ("local", "openai", "azure"):
        raise VoiceError('ตั้งค่า [voice] backend เป็น local, openai หรือ azure')
    return backend


def _cloud_config(cfg, backend):
    from opstrail.llm import api_key, load_settings

    settings = load_settings(cfg)
    # A saved Anthropic/OpenAI key must never go to a different provider.
    if settings.provider == backend:
        key, _ = api_key(cfg, settings)
    else:
        key = os.environ.get("OPENAI_API_KEY" if backend == "openai" else "AZURE_OPENAI_API_KEY", "")
    if not key:
        raise VoiceError("กรุณาตั้งค่า API key ของ voice backend ใน Settings หรือ environment")
    if backend == "openai":
        return "https://api.openai.com/v1/audio/transcriptions", {"Authorization": f"Bearer {key}"}, "whisper-1"
    deployment = str(cfg.data.get("voice", {}).get("azure_deployment", "")).strip()
    endpoint = settings.azure_endpoint.rstrip("/")
    parsed = urlsplit(endpoint)
    if not deployment or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        raise VoiceError("กรุณาตั้ง Azure HTTPS endpoint ใน Settings และ [voice] azure_deployment สำหรับ Whisper")
    url = (f"{endpoint}/openai/deployments/{quote(deployment, safe='')}/audio/transcriptions"
           f"?api-version={quote(str(settings.azure_api_version), safe='')}")
    return url, {"api-key": key}, deployment


def check_available(cfg):
    backend = _backend(cfg)
    try:
        importlib.import_module("sounddevice")
        if backend == "local":
            importlib.import_module("faster_whisper")
    except Exception:
        raise VoiceError(INSTALL_HINT) from None
    if backend != "local":
        _cloud_config(cfg, backend)


def record_audio(path, stop, cancel):
    """Read 100 ms blocks from the default microphone, capped by frame count."""
    import sounddevice as sd

    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
            for _ in range(MAX_SECONDS * 10):
                if stop.is_set() or cancel.is_set():
                    break
                data, overflow = stream.read(SAMPLE_RATE // 10)
                if overflow:
                    raise VoiceError("ไมโครโฟนอ่านเสียงไม่ทัน กรุณาลองใหม่")
                wav.writeframes(bytes(data))


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def transcribe_audio(cfg, path):
    backend = _backend(cfg)
    if backend == "local":
        from faster_whisper import WhisperModel

        model = WhisperModel("small", device="cpu", compute_type="int8",
                             download_root=str(cfg.home / "models"))
        segments, _ = model.transcribe(str(path), vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()
    url, headers, model = _cloud_config(cfg, backend)
    boundary = "opstrail-" + uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{model}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="voice.wav"\r\n'
            'Content-Type: audio/wav\r\n\r\n').encode()
    body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = request.Request(url, data=body, headers=headers, method="POST")
    with request.build_opener(_NoRedirect()).open(req, timeout=120) as response:
        return json.loads(response.read(1_000_000))["text"]


def capture_note(svc, episode_id=None, *, stop=None, cancel=None, recorder=None, transcriber=None):
    """Injectable capture transaction, called on a popup worker's own service connection."""
    cfg = svc.cfg
    stop = stop if stop is not None else threading.Event()
    cancel = cancel if cancel is not None else threading.Event()
    if cfg.is_paused():
        raise VoiceError("OpsTrail หยุดบันทึกอยู่ กรุณาเริ่มบันทึกต่อก่อนใช้ voice")
    if recorder is None or transcriber is None:
        check_available(cfg)
    with file_lock(cfg.home / "voice.lock", timeout=0) as acquired:
        if not acquired:
            raise VoiceError("กำลังบันทึกหรือถอดเสียงอยู่ กรุณารอให้เสร็จก่อน")
        svc.refresh()
        if episode_id:
            svc._require_episode(episode_id)
        else:
            # Freeze the target before model loading/transcription can take minutes.
            import time
            now = time.time()
            attach_s = float(cfg.episodes.get("note_attach_min", 15)) * 60
            episodes = svc.store.episodes_between(cfg.today())
            recent = [ep for ep in episodes if ep["start_epoch"] <= now
                      and (ep.get("open_task") or now - ep["end_epoch"] <= attach_s)]
            if recent:
                episode_id = max(recent, key=lambda ep: ep["end_epoch"])["id"]
        fd, name = tempfile.mkstemp(prefix="opstrail-voice-", suffix=".wav")
        os.close(fd)  # reopenable on Windows; mkstemp restricts POSIX permissions
        path = Path(name)
        try:
            if cancel.is_set() or cfg.is_paused():
                return None
            (recorder or record_audio)(path, stop, cancel)
            if cancel.is_set() or cfg.is_paused():
                return None
            with wave.open(str(path), "rb") as wav:
                if not wav.getnframes():
                    raise VoiceError("ไม่พบเสียง กรุณาลองบันทึกใหม่")
            text = (transcriber or transcribe_audio)(cfg, path)
            if cancel.is_set() or cfg.is_paused():
                return None
            if not isinstance(text, str) or not text.strip():
                raise VoiceError("ไม่พบคำพูด กรุณาลองบันทึกใหม่")
            return svc.add_note(text, episode_id, source="voice")
        except VoiceError:
            raise
        except Exception:
            # Provider/device exceptions may contain secrets, transcript or raw audio.
            raise VoiceError("บันทึกหรือถอดเสียงไม่สำเร็จ ตรวจไมโครโฟน / voice backend แล้วลองใหม่") from None
        finally:
            path.unlink(missing_ok=True)
