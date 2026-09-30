"""API tests with a stubbed speech model (no model download, no NPU needed)."""

import io
import time

import numpy as np
import pytest
from scipy.io import wavfile

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from vaani import server  # noqa: E402
from vaani.asr import BaseASR  # noqa: E402
from vaani.llm import ExtractiveLLM  # noqa: E402
from vaani.pipeline import NotesEngine  # noqa: E402

TEXT = ("Photosynthesis converts light energy into chemical energy in plants. "
        "Your lab report on photosynthesis must be submitted by Friday.")


class StubASR(BaseASR):
    name = "Stub ASR"

    def _transcribe_chunk(self, audio, language, task):
        return TEXT, "en"


@pytest.fixture
def client(monkeypatch):
    llm = ExtractiveLLM()
    monkeypatch.setattr(server, "_engines", {"asr": StubASR(), "llm": llm, "notes": NotesEngine(llm)})
    server._jobs.clear()
    return TestClient(server.app)


def wav_bytes(seconds=2, rate=16000):
    buf = io.BytesIO()
    wavfile.write(buf, rate, np.zeros(seconds * rate, dtype=np.int16))
    return buf.getvalue()


def wait_done(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_status_reports_backends(client):
    body = client.get("/api/status").json()
    assert body["asr"] == "Stub ASR" and body["llm_is_extractive"] is True
    assert "hi" in body["languages"] and "summary" in body["sections"]


def test_pages_carry_a_strict_csp(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "default-src 'self'" in res.headers["content-security-policy"]


def test_full_job_then_ask_and_download(client):
    res = client.post("/api/jobs", files={"audio": ("a.wav", wav_bytes(), "audio/wav")},
                      data={"language": "auto", "task": "transcribe", "notes_language": "English"})
    assert res.status_code == 202
    job_id = res.json()["id"]
    job = wait_done(client, job_id)
    assert job["status"] == "done", job["message"]
    assert job["language"] == "en" and job["segments"][0]["text"] == TEXT
    assert "Friday" in job["sections"]["action_items"]
    assert job["perf"]["bytes_sent_to_internet"] == 0

    answer = client.post(f"/api/jobs/{job_id}/ask", json={"question": "When is the lab report due?"})
    assert "Friday" in answer.json()["answer"]
    notes = client.get(f"/api/jobs/{job_id}/notes.md")
    assert notes.status_code == 200 and notes.text.startswith("# VaaniNotes")


@pytest.mark.parametrize("data, status", [
    ({"language": "xx"}, 422),
    ({"task": "delete"}, 422),
    ({"notes_language": "Klingon"}, 422),
    ({"sections": "nope"}, 422),
])
def test_rejects_bad_options(client, data, status):
    res = client.post("/api/jobs", files={"audio": ("a.wav", wav_bytes(), "audio/wav")}, data=data)
    assert res.status_code == status


def test_rejects_non_wav_upload(client):
    res = client.post("/api/jobs", files={"audio": ("a.wav", b"not audio at all", "audio/wav")})
    assert res.status_code == 415


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404
    assert client.post("/api/jobs/does-not-exist/ask", json={"question": "hi"}).status_code == 404
