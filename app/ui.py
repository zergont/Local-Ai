from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
import secrets
import shutil

router = APIRouter(tags=["ui"])

BASE_FILES = Path("files")
BASE_FILES.mkdir(parents=True, exist_ok=True)


@router.post("/ui/upload")
async def ui_upload(file: UploadFile = File(...)):
    # простая защита имени и расширения
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".txt"}:
        raise HTTPException(400, "unsupported file type")
    name = f"{secrets.token_hex(8)}{suffix}"
    dest = (BASE_FILES / name).resolve()
    # сохраняем
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"url": f"/file/{name}"}


@router.get("/", response_class=HTMLResponse)
async def ui_index():
    html = (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)
