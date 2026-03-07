import logging
import mimetypes
import boto3
from botocore.client import Config
from config import S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET, S3_REGION

_client = None


def _get_client():
    global _client
    if _client is None and S3_ACCESS_KEY and S3_SECRET_KEY and S3_ENDPOINT:
        _client = boto3.client(
            's3',
            endpoint_url=f"https://{S3_ENDPOINT}",
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name=S3_REGION,
            config=Config(s3={'addressing_style': 'path'})
        )
    return _client


def is_configured():
    return bool(S3_ACCESS_KEY and S3_SECRET_KEY and S3_ENDPOINT and S3_BUCKET)


def upload(content: bytes, key: str, content_type: str = 'image/jpeg') -> bool:
    client = _get_client()
    if not client:
        return False
    try:
        client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        return True
    except Exception as e:
        logging.error(f"S3 upload error: {e}")
        return False


def download(key: str) -> bytes | None:
    client = _get_client()
    if not client:
        return None
    try:
        response = client.get_object(Bucket=S3_BUCKET, Key=key)
        return response['Body'].read()
    except Exception as e:
        logging.error(f"S3 download error for {key}: {e}")
        return None


def delete(key: str) -> bool:
    client = _get_client()
    if not client:
        return False
    try:
        client.delete_object(Bucket=S3_BUCKET, Key=key)
        return True
    except Exception as e:
        logging.error(f"S3 delete error: {e}")
        return False
