from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


KOLKATA_TZ = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class Settings:
    uploads_dir: Path
    reconcile_script: Path
    cors_origins: list[str]
    cors_origin_regex: str
    reconcile_timeout_seconds: int


def get_settings() -> Settings:
    repo_root = Path(__file__).resolve().parent

    uploads_dir = Path(os.environ.get("QLINK_UPLOADS_DIR", str(repo_root / "uploads")))
    if not uploads_dir.is_absolute():
        uploads_dir = (repo_root / uploads_dir).resolve()

    reconcile_script = Path(os.environ.get("QLINK_RECONCILE_SCRIPT", str(repo_root / "main.py")))
    if not reconcile_script.is_absolute():
        reconcile_script = (repo_root / reconcile_script).resolve()

    cors_raw = os.environ.get(
        "QLINK_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    )
    cors_origins = [origin.strip() for origin in cors_raw.split(",") if origin.strip()]

    cors_origin_regex = os.environ.get(
        "QLINK_CORS_ORIGIN_REGEX",
        r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    )

    timeout_seconds = int(os.environ.get("QLINK_RECONCILE_TIMEOUT_SECONDS", "900"))

    return Settings(
        uploads_dir=uploads_dir,
        reconcile_script=reconcile_script,
        cors_origins=cors_origins,
        cors_origin_regex=cors_origin_regex,
        reconcile_timeout_seconds=timeout_seconds,
    )


def now_kolkata() -> datetime:
    return datetime.now(tz=KOLKATA_TZ)


def month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def run_stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%d_%H%M%S_%f")


def safe_filename(name: str, fallback: str = "upload.bin") -> str:
    base = Path(name or "").name
    base = base.strip()
    if not base:
        return fallback

    base = re.sub(r"\s+", "_", base)
    base = re.sub(r"[^A-Za-z0-9._-]", "", base)
    if base in {".", "..", ""}:
        return fallback
    return base


def ensure_allowed_extension(filename: str) -> None:
    allowed = {".csv", ".xlsx", ".xls"}
    ext = Path(filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(allowed))}",
        )


def save_upload_file(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
    finally:
        try:
            upload.file.close()
        except Exception:
            pass


def tail_bytes(path: Path, max_bytes: int = 7000) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            chunk = f.read()
        return chunk.decode("utf-8", errors="replace")
    except Exception:
        return ""


def validate_month(month: str) -> None:
    if not MONTH_RE.match(month or ""):
        raise HTTPException(status_code=400, detail="Invalid month format. Expected YYYY-MM.")


def resolve_download_path(uploads_dir: Path, month: str, filename: str) -> Path:
    validate_month(month)

    if not filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    month_dir = (uploads_dir / month).resolve()
    candidate = (month_dir / filename).resolve()

    if candidate.parent != month_dir:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    return candidate


settings = get_settings()

app = FastAPI(title="Qlink Mediator API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

if os.environ.get("QLINK_SERVE_FRONTEND", "0") == "1":
    dist_dir = Path(__file__).resolve().parent / "Qlink" / "dist"
    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")


@app.get("/api/health")
@app.get("/health", include_in_schema=False)
def health():
    dt = now_kolkata()
    return {"status": "ok", "time": dt.isoformat(), "month": month_key(dt)}


@app.get("/api/history")
@app.get("/history", include_in_schema=False)
def history():
    uploads_root = settings.uploads_dir
    uploads_root.mkdir(parents=True, exist_ok=True)

    months = sorted(
        [p.name for p in uploads_root.iterdir() if p.is_dir() and MONTH_RE.match(p.name)],
        reverse=True,
    )

    data = []
    for month in months:
        month_dir = uploads_root / month
        files = []
        for entry in sorted(month_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not entry.is_file():
                continue
            stat = entry.stat()
            files.append(
                {
                    "name": entry.name,
                    "size": stat.st_size,
                    "modifiedAt": datetime.fromtimestamp(stat.st_mtime, tz=KOLKATA_TZ).isoformat(),
                }
            )

        data.append({"month": month, "files": files})

    return {"months": data}


@app.get("/api/download/{month}/{filename}")
@app.get("/download/{month}/{filename}", include_in_schema=False)
def download(month: str, filename: str):
    path = resolve_download_path(settings.uploads_dir, month, filename)
    return FileResponse(path=path, filename=path.name)


@app.post("/api/reconcile")
@app.post("/reconcile", include_in_schema=False)
def reconcile(
    erp: UploadFile = File(...),
    tallySheet9: UploadFile = File(...),
    gst05: UploadFile = File(...),
    gst25: UploadFile = File(...),
    gst9: UploadFile = File(...),
    agreementLedger: UploadFile = File(...),
    gst6: Optional[UploadFile] = File(None),
    otherDifferences: Optional[UploadFile] = File(None),
):
    if not settings.reconcile_script.is_file():
        raise HTTPException(
            status_code=500,
            detail=f"Reconcile script not found at: {settings.reconcile_script}",
        )

    dt = now_kolkata()
    month = month_key(dt)
    stamp = run_stamp(dt)

    uploads_root = settings.uploads_dir
    month_dir = uploads_root / month
    month_dir.mkdir(parents=True, exist_ok=True)

    uploads: dict[str, UploadFile] = {
        "erp": erp,
        "tallySheet9": tallySheet9,
        "gst05": gst05,
        "gst25": gst25,
        "gst9": gst9,
        "agreementLedger": agreementLedger,
    }
    if gst6 is not None:
        uploads["gst6"] = gst6
    if otherDifferences is not None:
        uploads["otherDifferences"] = otherDifferences

    saved_paths: dict[str, Path] = {}
    for key, upload in uploads.items():
        original_name = safe_filename(upload.filename or f"{key}.bin")
        ensure_allowed_extension(original_name)
        stored_name = f"{stamp}__{key}__{original_name}"
        destination = month_dir / stored_name
        save_upload_file(upload, destination)
        saved_paths[key] = destination

    output_name = f"{stamp}__output__gst_reconciliation.csv"
    output_path = month_dir / output_name
    log_path = month_dir / f"{stamp}__run.log"

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["QLINK_ERP_FILE"] = str(saved_paths["erp"])
    env["QLINK_TALLY_FILE"] = str(saved_paths["tallySheet9"])
    env["QLINK_GST_05_FILE"] = str(saved_paths["gst05"])
    env["QLINK_GST_25_FILE"] = str(saved_paths["gst25"])
    env["QLINK_GST_9_FILE"] = str(saved_paths["gst9"])
    env["QLINK_REG_AGREEMENT_FILE"] = str(saved_paths["agreementLedger"])
    if "gst6" in saved_paths:
        env["QLINK_GST_6_FILE"] = str(saved_paths["gst6"])
    else:
        env.pop("QLINK_GST_6_FILE", None)
    env["QLINK_OUTPUT_CSV"] = str(output_path)

    try:
        with log_path.open("wb") as log:
            completed = subprocess.run(
                [sys.executable, str(settings.reconcile_script)],
                cwd=Path(__file__).resolve().parent,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=settings.reconcile_timeout_seconds,
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail=f"Reconciliation timed out after {settings.reconcile_timeout_seconds}s.",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not run reconciliation: {exc}") from exc

    if completed.returncode != 0:
        tail = tail_bytes(log_path)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Reconciliation failed. See run log in history.",
                "logFile": log_path.name,
                "logTail": tail,
            },
        )

    if not output_path.is_file():
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Reconciliation finished but output CSV was not created.",
                "expectedOutput": output_path.name,
                "logFile": log_path.name,
            },
        )

    return FileResponse(path=output_path, filename=output_path.name, media_type="text/csv")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api_server:app",
        host=os.environ.get("QLINK_HOST", "127.0.0.1"),
        port=int(os.environ.get("QLINK_PORT", "8000")),
        reload=os.environ.get("QLINK_RELOAD", "1") == "1",
    )
