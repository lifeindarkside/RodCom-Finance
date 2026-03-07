import mimetypes
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

import s3_storage
from config import UPLOAD_DIR

router = APIRouter(tags=["uploads"])


@router.get("/uploads/{filename}")
async def serve_upload(filename: str):
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    local_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.isfile(local_path):
        return FileResponse(local_path, headers={"Cache-Control": "public, max-age=86400"})
    if s3_storage.is_configured():
        data = s3_storage.download(f"photos/{filename}") or s3_storage.download(filename)
        if data:
            ct = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            return Response(content=data, media_type=ct, headers={"Cache-Control": "public, max-age=86400"})
    raise HTTPException(status_code=404, detail="File not found")
