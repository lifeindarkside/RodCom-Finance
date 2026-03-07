import os
import uuid
import mimetypes

from fastapi import HTTPException, UploadFile

import s3_storage
from config import UPLOAD_DIR


async def save_upload(photo: UploadFile) -> str | None:
    if not photo or not photo.filename:
        return None
    ext = os.path.splitext(photo.filename)[1] or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    content = await photo.read()
    if s3_storage.is_configured():
        content_type = photo.content_type or mimetypes.guess_type(filename)[0] or 'image/jpeg'
        s3_key = f"photos/{filename}"
        if s3_storage.upload(content, s3_key, content_type):
            return filename
        raise HTTPException(status_code=500, detail="Ошибка загрузки файла в хранилище")
    else:
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as fb:
            fb.write(content)
        return filename


def delete_upload(filename: str):
    if s3_storage.is_configured():
        s3_storage.delete(f"photos/{filename}")
        s3_storage.delete(filename)
    local_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(local_path):
        os.remove(local_path)
