"""Local web app: FastAPI backend + static frontend (vaani/web).

Binds to 127.0.0.1 only. A strict Content-Security-Policy (default-src 'self')
means the page itself cannot load or send anything outside this machine.
"""

from __future__ import annotations

import argparse
import threading
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import device
from .asr import load_asr
from .audio import load_wav_bytes
from .config import LANGUAGES, OUTPUT_LANGUAGES, Config
from .llm import load_llm
from .pipeline import SECTIONS, NotesEngine

WEB = Path(__file__).parent / "web"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # ~4 h of 16 kHz mono 16-bit audio
MAX_JOBS = 20

CFG = Config()
app = FastAPI(title="VaaniNotes", docs_url=None, redoc_url=None)
_engines: dict = {}
_jobs: dict[str, dict] = {}
_worker = ThreadPoolExecutor(max_workers=1)  # one recording at a time on the NPU
_lock = threading.Lock()


def engines():
    with _lock:
        if not _engines:
            _engines["asr"] = load_asr(CFG)
            _engines["llm"] = load_llm(CFG)
            _engines["notes"] = NotesEngine(_engines["llm"], CFG.llm_chunk_chars)
    return _engines["asr"], _engines["notes"]


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; media-src 'self' blob:; img-src 'self' data:; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/api/status")
def status():
    asr, notes = engines()
    return {
        "device": device.summary(),
        "asr": asr.name,
        "asr_on_npu": "NPU" in asr.name,
        "llm": notes.llm.name,
        "llm_on_npu": "NPU" in notes.llm.name,
        "llm_is_extractive": notes.is_extractive,
        "languages": LANGUAGES,
        "output_languages": OUTPUT_LANGUAGES,
        "sections": SECTIONS,
    }


def _run(job: dict, audio_bytes: bytes, language: str, task: str, notes_language: str,
         sections: list[str]) -> None:
    try:
        asr, engine = engines()
        samples = load_wav_bytes(audio_bytes)
        del audio_bytes

        def asr_progress(frac: float, message: str) -> None:
            job.update(progress=0.6 * frac, message=message)

        def notes_progress(frac: float, message: str) -> None:
            job.update(progress=0.6 + 0.4 * frac, message=message)

        job.update(status="transcribing", message=f"Transcribing on {asr.name}")
        transcript = asr.transcribe(
            samples, language, task, progress=asr_progress,
            on_segment=lambda s: job["segments"].append({"start": s.start, "text": s.text}),
        )
        job.update(status="writing", progress=0.6, language=transcript.language,
                   message=f"Writing notes with {engine.llm.name}")
        notes = engine.build(
            transcript, notes_language, sections, progress=notes_progress,
            on_section=lambda key, text: job["sections"].__setitem__(key, text),
        )
        stats = getattr(engine.llm, "last_stats", {}) or {}
        chunks = transcript.per_chunk_ms
        job.update(
            status="done", progress=1.0, message="Done",
            transcript=transcript, markdown=notes.to_markdown(),
            perf={
                "audio_seconds": round(transcript.audio_seconds, 1),
                "asr_backend": transcript.backend,
                "asr_seconds": round(transcript.elapsed_seconds, 2),
                "speed_x_realtime": round(1 / max(transcript.realtime_factor, 1e-6), 1),
                "avg_window_ms": round(sum(chunks) / max(len(chunks), 1)),
                "llm_backend": notes.llm_name,
                "llm_seconds": round(notes.llm_seconds, 1),
                "llm_tokens_per_second": round(stats["tokens_per_second"], 1)
                if "tokens_per_second" in stats else None,
                "bytes_sent_to_internet": 0,
            },
        )
    except Exception as e:  # surfaced to the UI; the worker must never die
        job.update(status="error", message=f"{type(e).__name__}: {e}")


@app.post("/api/jobs", status_code=202)
async def create_job(
    audio: UploadFile = File(...),
    language: str = Form("auto"),
    task: str = Form("transcribe"),
    notes_language: str = Form("English"),
    sections: str = Form(",".join(SECTIONS)),
):
    if language not in LANGUAGES:
        raise HTTPException(422, "Unknown spoken language")
    if task not in ("transcribe", "translate"):
        raise HTTPException(422, "Unknown task")
    if notes_language not in OUTPUT_LANGUAGES:
        raise HTTPException(422, "Unknown notes language")
    wanted = [s for s in sections.split(",") if s in SECTIONS]
    if not wanted:
        raise HTTPException(422, "Select at least one section")
    data = await audio.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Recording is too large")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise HTTPException(415, "Audio must be WAV (the app converts other formats in the browser)")

    while len(_jobs) >= MAX_JOBS:  # keep memory bounded: drop the oldest job
        _jobs.pop(next(iter(_jobs)))
    job_id = uuid.uuid4().hex
    job = {"status": "queued", "progress": 0.0, "message": "Queued", "segments": [],
           "sections": {}, "language": None, "perf": None, "notes_language": notes_language}
    _jobs[job_id] = job
    _worker.submit(_run, job, data, language, task, notes_language, wanted)
    return {"id": job_id}


def _job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    return job


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = _job(job_id)
    return {k: job[k] for k in ("status", "progress", "message", "segments", "sections",
                                "language", "perf")}


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@app.post("/api/jobs/{job_id}/ask")
def ask(job_id: str, body: Question):
    job = _job(job_id)
    if job["status"] != "done":
        raise HTTPException(409, "Notes are not ready yet")
    _, engine = engines()
    return {"answer": engine.ask(job["transcript"], body.question, job["notes_language"])}


@app.get("/api/jobs/{job_id}/notes.md")
def download(job_id: str):
    job = _job(job_id)
    if job["status"] != "done":
        raise HTTPException(409, "Notes are not ready yet")
    return PlainTextResponse(
        job["markdown"], media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="vaani-notes.md"'},
    )


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="VaaniNotes local web app")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    print("Loading models ...")
    asr, notes = engines()
    print(f"Speech: {asr.name}\nNotes:  {notes.llm.name}")
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
