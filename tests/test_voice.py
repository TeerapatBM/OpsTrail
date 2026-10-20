"""Voice capture without hardware, downloads or network."""
import threading
import wave

import pytest

from opstrail import voice


def recorder(path, stop, cancel):
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * 1600)


def test_voice_note_redacted_attached_and_audio_deleted(svc):
    svc.record("shell", {"cmd": "echo voice test"})
    svc.refresh()
    ep = svc.list_episodes(svc.cfg.today())[0]["id"]
    paths = []

    def transcribe(cfg, path):
        paths.append(path)
        assert path.exists()
        return "แก้ service แล้ว password=supersecret"

    result = svc.record_voice(episode_id=ep, recorder=recorder, transcriber=transcribe)
    ev = svc.store.get_event(result["event_id"])
    assert ev["source"] == "voice" and ev["type"] == "note"
    assert ev["episode_id"] == ep
    assert "supersecret" not in str(ev)
    assert all(not p.exists() for p in paths)


@pytest.mark.parametrize("failure", ["record", "transcribe", "empty", "cancel"])
def test_cleanup_without_note_on_failure(svc, failure):
    paths = []
    cancel = threading.Event()

    def record(path, stop, cancelled):
        paths.append(path)
        recorder(path, stop, cancelled)
        if failure == "record":
            raise RuntimeError("private device detail")
        if failure == "cancel":
            cancelled.set()

    def transcribe(cfg, path):
        assert failure != "cancel", "cancelled audio must not be transcribed/uploaded"
        if failure == "transcribe":
            raise RuntimeError("private response")
        return " "

    if failure == "cancel":
        assert svc.record_voice(cancel=cancel, recorder=record, transcriber=transcribe) is None
    else:
        with pytest.raises(voice.VoiceError) as exc:
            svc.record_voice(cancel=cancel, recorder=record, transcriber=transcribe)
        assert "private" not in str(exc.value)
    assert paths and all(not p.exists() for p in paths)
    assert not svc.store.count_events(svc.cfg.today()).get("note")


def test_paused_does_not_open_microphone(svc):
    svc.cfg.set_paused(True)
    with pytest.raises(voice.VoiceError):
        svc.record_voice(recorder=lambda *a: pytest.fail("microphone opened"))


def test_missing_extra_has_install_hint(cfg, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    with pytest.raises(voice.VoiceError, match=r"pip install.*voice"):
        voice.check_available(cfg)


def test_unknown_backend_rejected(cfg):
    cfg.data["voice"]["backend"] = "typo"
    with pytest.raises(voice.VoiceError):
        voice.check_available(cfg)


def test_local_model_stays_in_configured_home(cfg, tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    calls = []

    class Model:
        def __init__(self, name, **kwargs):
            calls.append((name, kwargs))

        def transcribe(self, path, **kwargs):
            assert kwargs == {"vad_filter": True}
            return iter([SimpleNamespace(text=" สรุป "), SimpleNamespace(text="service OK")]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    assert voice.transcribe_audio(cfg, tmp_path / "fake.wav") == "สรุป service OK"
    assert calls == [("small", {"device": "cpu", "compute_type": "int8", "download_root": str(cfg.home / "models")})]


@pytest.mark.parametrize("backend", ["openai", "azure"])
def test_cloud_multipart_and_credentials(cfg, tmp_path, monkeypatch, backend):
    import json
    from types import SimpleNamespace
    from opstrail import llm
    cfg.data["voice"].update(backend=backend, azure_deployment="speech model")
    settings = llm.LLMSettings(provider=backend, azure_endpoint="https://example.openai.azure.com")
    monkeypatch.setattr(llm, "load_settings", lambda cfg: settings)
    monkeypatch.setattr(llm, "api_key", lambda *a: ("test-secret", "stored"))
    path = tmp_path / "test.wav"
    recorder(path, threading.Event(), threading.Event())
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self, limit):
            return json.dumps({"text": "สรุป service OK"}).encode()

    def open_request(req, timeout):
        seen.append(req)
        assert timeout == 120
        assert path.read_bytes() in req.data
        assert b'filename="voice.wav"' in req.data
        return Response()

    monkeypatch.setattr(voice.request, "build_opener", lambda handler: SimpleNamespace(open=open_request))
    assert voice.transcribe_audio(cfg, path) == "สรุป service OK"
    req = seen[0]
    if backend == "openai":
        assert req.full_url == "https://api.openai.com/v1/audio/transcriptions"
        assert req.get_header("Authorization") == "Bearer test-secret"
        assert b"whisper-1" in req.data
    else:
        assert "/speech%20model/audio/transcriptions?api-version=2024-10-21" in req.full_url
        assert req.get_header("Api-key") == "test-secret"


def test_cloud_never_reuses_other_provider_key(cfg, monkeypatch):
    from opstrail import llm
    monkeypatch.setattr(llm, "load_settings", lambda cfg: llm.LLMSettings(provider="anthropic"))
    monkeypatch.setattr(llm, "api_key", lambda *a: pytest.fail("wrong provider key accessed"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(voice.VoiceError):
        voice._cloud_config(cfg, "openai")


def test_recording_frame_cap_stop_and_cancel(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    calls = []

    class Stream:
        def __init__(self, **kwargs):
            assert kwargs == {"samplerate": 16000, "channels": 1, "dtype": "int16"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self, frames):
            calls.append(frames)
            return b"\0\0" * frames, False

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(RawInputStream=Stream))
    path = tmp_path / "bounded.wav"
    stop, cancel = threading.Event(), threading.Event()
    voice.record_audio(path, stop, cancel)
    with wave.open(str(path)) as wav:
        assert wav.getnframes() == 16000 * 60
    assert len(calls) == 600
    for event in (stop, cancel):
        calls.clear()
        event.set()
        voice.record_audio(path, stop, cancel)
        assert not calls
        event.clear()


def test_single_capture_lock(svc):
    from opstrail.locks import file_lock
    with file_lock(svc.cfg.home / "voice.lock", timeout=0) as acquired:
        assert acquired
        with pytest.raises(voice.VoiceError, match="กำลังบันทึก"):
            svc.record_voice(recorder=recorder, transcriber=lambda *a: "unused")


def test_pause_during_recording_discards_before_transcription(svc):
    paths = []

    def record(path, stop, cancel):
        paths.append(path)
        recorder(path, stop, cancel)
        svc.cfg.set_paused(True)

    assert svc.record_voice(recorder=record, transcriber=lambda *a: pytest.fail("uploaded while paused")) is None
    assert all(not p.exists() for p in paths)


def test_auto_attachment_frozen_before_transcription(svc):
    svc.record("shell", {"cmd": "echo original task"})
    svc.refresh()
    ep = svc.list_episodes(svc.cfg.today())[0]["id"]
    def transcribe(*args):
        svc.record("task", {"action": "start", "title": "new work while transcribing"})
        svc.refresh()
        return "สรุปงาน"

    result = svc.record_voice(recorder=recorder, transcriber=transcribe)
    assert result["episode_id"] == ep


def test_popup_missing_extra_shows_toast_without_recording(cfg, monkeypatch):
    from opstrail.agent import popup
    seen = []
    def missing(cfg):
        raise voice.VoiceError(voice.INSTALL_HINT)
    monkeypatch.setattr(voice, "check_available", missing)
    monkeypatch.setattr(popup, "toast", lambda message, **kw: seen.append(message))
    monkeypatch.setattr(popup, "_root", lambda *a: pytest.fail("recorder UI opened"))
    popup.voice(cfg)
    assert seen == [voice.INSTALL_HINT]


@pytest.mark.parametrize("action", ["stop", "cancel"])
def test_popup_controls_worker_and_cleanup(cfg, monkeypatch, action):
    import sys
    from types import SimpleNamespace
    from opstrail.agent import popup
    from opstrail.service import OpsTrail
    buttons, messages, paths = {}, [], []

    class Widget:
        def __init__(self, *a, **kw):
            if "command" in kw:
                buttons[kw["text"]] = kw["command"]

        def pack(self, **kw):
            pass

        def config(self, **kw):
            pass

    class Root:
        def __init__(self):
            self.pending = []
            self.closed = False

        def protocol(self, *a):
            pass

        def bind(self, *a):
            pass

        def after(self, ms, callback):
            self.pending.append(callback)

        def mainloop(self):
            for _ in range(10):
                if self.closed:
                    return
                self.pending.pop(0)()
            pytest.fail("popup failed to finish")

        def destroy(self):
            self.closed = True

        def withdraw(self):
            pass

    class Thread:
        def __init__(self, target, **kw):
            self.target = target

        def start(self):
            buttons["หยุดและถอดเสียง" if action == "stop" else "ยกเลิก"]()
            self.target()

    def record(path, stop, cancel):
        assert stop.is_set()
        paths.append(path)
        recorder(path, stop, cancel)

    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(Label=Widget, Button=Widget))
    monkeypatch.setattr(popup, "_root", lambda *a: Root())
    monkeypatch.setattr(popup, "_center", lambda *a: None)
    monkeypatch.setattr(popup, "toast", lambda text, **kw: messages.append(text))
    monkeypatch.setattr(threading, "Thread", Thread)
    monkeypatch.setattr(voice, "check_available", lambda cfg: None)
    monkeypatch.setattr(voice, "record_audio", record)
    monkeypatch.setattr(voice, "transcribe_audio", lambda *a: "สรุปงานจากเสียง")
    popup.voice(cfg)
    svc = OpsTrail(cfg)
    try:
        notes = svc.store.count_events(cfg.today()).get("note", 0)
        assert notes == (1 if action == "stop" else 0)
    finally:
        svc.store.close()
    assert all(not path.exists() for path in paths)
    assert bool(messages) == (action == "stop")


def test_cancel_during_transcription_discards_result(svc):
    cancel = threading.Event()
    paths = []

    def transcribe(cfg, path):
        paths.append(path)
        cancel.set()
        return "must not be saved"

    assert svc.record_voice(cancel=cancel, recorder=recorder, transcriber=transcribe) is None
    assert not svc.store.count_events(svc.cfg.today()).get("note")
    assert all(not p.exists() for p in paths)
