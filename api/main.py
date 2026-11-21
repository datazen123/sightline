"""FastAPI service.

    GET  /health                 liveness + which LLM provider is active
    GET  /corpora                installed corpus plugins
    POST /audit                  multipart: corpus=<name>, files=<one or more>
                                 (no files -> audits the corpus's sample data)
    GET  /                       React UI (if web/dist has been built)

Run: uv run sightline serve   (or: uv run uvicorn api.main:app --reload)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agents.llm import detect_provider
from sightline.core.engine import run_audit
from sightline.core.plugins import REPO_ROOT, discover
from sightline.core.schema import AuditResult
from sightline.ingest.mapping import MappingRejected

MAX_FILES = 25
MAX_BYTES = 25 * 1024 * 1024

app = FastAPI(title="Sightline audit engine", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"],
                   allow_headers=["*"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "provider": detect_provider(), "corpora": list(discover())}


@app.get("/corpora")
def corpora() -> list[dict]:
    return [{"name": c.name, "title": c.title, "accepts": c.accepts} for c in discover().values()]


@app.post("/audit", response_model=AuditResult)
async def audit(corpus: str = Form(...), files: list[UploadFile] | None = File(None)) -> AuditResult:
    cfgs = discover()
    if corpus not in cfgs:
        raise HTTPException(400, f"unknown corpus '{corpus}'; choose one of {list(cfgs)}")
    files = files or []
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"at most {MAX_FILES} files per audit")
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for up in files:
            name = Path(up.filename or "").name  # strip any client-side path
            if not name or Path(name).suffix.lower() not in cfgs[corpus].accepts:
                raise HTTPException(415, f"{name or 'file'}: accepted types are {cfgs[corpus].accepts}")
            data = await up.read()
            if len(data) > MAX_BYTES:
                raise HTTPException(413, f"{name} is larger than {MAX_BYTES // 1024 // 1024} MB")
            dest = Path(d) / name
            dest.write_bytes(data)
            paths.append(dest)
        try:
            result, _ = run_audit(corpus, paths or None)
        except (ValueError, MappingRejected) as e:
            raise HTTPException(422, str(e)) from e
    return result


_dist = REPO_ROOT / "web" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")


