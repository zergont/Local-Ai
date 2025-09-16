from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from fastapi.responses import HTMLResponse
from pathlib import Path
import secrets
import hashlib

from .logging_utils import log_error, log_info
from .config import settings

router = APIRouter(tags=["ui"])

BASE_FILES = Path(settings.files_dir).resolve()
BASE_FILES.mkdir(parents=True, exist_ok=True)


def _is_allowed_mime(mime: str) -> bool:
    if not mime:
        return False
    if mime.startswith("image/"):
        return True
    return mime in {"application/pdf", "text/plain"}


@router.post("/ui/upload")
async def ui_upload(file: UploadFile = File(...), request: Request = None):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in settings.allowed_exts:
        raise HTTPException(400, f"unsupported file type: {suffix}")
    if not _is_allowed_mime(file.content_type or ""):
        raise HTTPException(400, f"unsupported mime: {file.content_type}")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    h = hashlib.sha256()
    tmp = (BASE_FILES / f".upload-{secrets.token_hex(8)}{suffix}").resolve()
    if BASE_FILES not in tmp.parents:
        raise HTTPException(400, "bad path")

    size = 0
    try:
        with tmp.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    out.close()
                    tmp.unlink(missing_ok=True)
                    raise HTTPException(413, f"file too large (>{settings.max_upload_mb} MB)")
                h.update(chunk)
                out.write(chunk)
        digest = h.hexdigest()
        final_path = (BASE_FILES / f"{digest}{suffix}").resolve()
        if BASE_FILES not in final_path.parents:
            tmp.unlink(missing_ok=True)
            raise HTTPException(400, "bad path")
        if final_path.exists():
            tmp.unlink(missing_ok=True)
            exists = True
        else:
            tmp.replace(final_path)
            exists = False
        log_info("ui_upload", size=size, mime=file.content_type, name=final_path.name, status="ok", dedup=exists)
        # Prefer request.base_url to generate URL behind reverse proxies; fallback to settings.app_base_url
        try:
            base_url = str(request.base_url).rstrip("/") if request is not None else settings.app_base_url
        except Exception:
            base_url = settings.app_base_url
        abs_url = f"{base_url}/file/{final_path.name}"
        return {"url": abs_url, "size": size}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log_error("ui_upload_error", error=str(e))
        tmp.unlink(missing_ok=True)
        raise HTTPException(500, "internal error")


@router.get("/", response_class=HTMLResponse)
async def ui_index():
    html = (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)
