"""S3-compatible storage backend.

Works with Supabase Storage (via its S3 gateway), AWS S3, Cloudflare R2, and
MinIO — anything that speaks the S3 API — configured entirely by env:

    STORAGE_S3_ENDPOINT   e.g. https://<project>.supabase.co/storage/v1/s3
    STORAGE_S3_REGION     e.g. us-east-1  (Supabase: any value, required by SDK)
    STORAGE_S3_BUCKET     bucket / Supabase storage bucket name
    STORAGE_S3_ACCESS_KEY / STORAGE_S3_SECRET_KEY

boto3 is imported lazily so the module loads without the dependency present.
"""
from __future__ import annotations

import os
from typing import Optional

from .base import SignedURL, StorageBackend, StorageError


class S3Storage(StorageBackend):
    def __init__(
        self,
        bucket: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        region: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        self.bucket = bucket or os.getenv("STORAGE_S3_BUCKET")
        self.endpoint_url = endpoint_url or os.getenv("STORAGE_S3_ENDPOINT")
        self.region = region or os.getenv("STORAGE_S3_REGION", "us-east-1")
        self._access_key = access_key or os.getenv("STORAGE_S3_ACCESS_KEY")
        self._secret_key = secret_key or os.getenv("STORAGE_S3_SECRET_KEY")
        if not self.bucket:
            raise StorageError("STORAGE_S3_BUCKET is required for the s3 backend")
        self._client = None

    def _c(self):
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as e:  # pragma: no cover
                raise StorageError("boto3 is required for the s3 storage backend") from e
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name=self.region,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                config=Config(signature_version="s3v4"),
            )
        return self._client

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        try:
            self._c().put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        except Exception as e:  # noqa: BLE001
            raise StorageError(f"put_bytes failed for {key}: {e}") from e
        return key

    def put_file(self, key: str, local_path: str, content_type: str = "application/octet-stream") -> str:
        try:
            self._c().upload_file(local_path, self.bucket, key, ExtraArgs={"ContentType": content_type})
        except Exception as e:  # noqa: BLE001
            raise StorageError(f"put_file failed for {key}: {e}") from e
        return key

    def get_bytes(self, key: str) -> bytes:
        try:
            obj = self._c().get_object(Bucket=self.bucket, Key=key)
            return obj["Body"].read()
        except Exception as e:  # noqa: BLE001
            raise StorageError(f"Object not found: {key} ({e})") from e

    def exists(self, key: str) -> bool:
        try:
            self._c().head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001
            return False

    def delete(self, key: str) -> None:
        try:
            self._c().delete_object(Bucket=self.bucket, Key=key)
        except Exception as e:  # noqa: BLE001
            raise StorageError(f"delete failed for {key}: {e}") from e

    def signed_url(self, key: str, expires_in: int = 3600, download_name: Optional[str] = None) -> SignedURL:
        params = {"Bucket": self.bucket, "Key": key}
        if download_name:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
        try:
            url = self._c().generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in)
        except Exception as e:  # noqa: BLE001
            raise StorageError(f"signing failed for {key}: {e}") from e
        return SignedURL(url=url, expires_in=expires_in)
