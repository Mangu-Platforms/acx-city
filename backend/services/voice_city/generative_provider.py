"""Provider contract for persistent synthetic Voice City identities.

Phase-one catalog voices use semantic parameter recipes directly.  Providers
that can materialize a stable speaker identity implement this richer contract.
The default remote implementation speaks a small, vendor-neutral HTTP protocol
so a locally hosted or managed controllable TTS stack can be swapped without
changing the product, database, or production pipeline.
"""
from __future__ import annotations

import base64
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import quote, urlparse

import requests


class GenerativeProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class VoiceArtifact:
    artifact_id: str
    provider: str
    model_family: str
    model_revision: str
    provider_voice_id: str
    supported_languages: list[str] = field(default_factory=lambda: ["en-US"])
    speaker_embedding: bytes | None = None
    model_artifact: bytes | None = None
    speaker_embedding_key: str | None = None
    model_artifact_key: str | None = None
    quality_score: float | None = None
    consistency_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class GenerativeVoiceProvider(ABC):
    """Persistent-identity provider contract described by the Voice City spec."""

    name: str = "base-generative"
    display_name: str = "Base generative provider"

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def create_voice(
        self,
        *,
        identity_parameters: Mapping[str, Any],
        style_parameters: Mapping[str, Any],
        seed: int,
        metadata: Mapping[str, Any] | None = None,
    ) -> VoiceArtifact:
        ...

    @abstractmethod
    def preview_voice(
        self,
        *,
        voice_artifact_id: str,
        text: str,
        performance_parameters: Mapping[str, Any],
    ) -> bytes:
        ...

    @abstractmethod
    def synthesize(
        self,
        *,
        text: str,
        voice_artifact_id: str,
        performance_parameters: Mapping[str, Any],
    ) -> bytes:
        ...


class RemoteGenerativeVoiceProvider(GenerativeVoiceProvider):
    """HTTP client for a controllable TTS/model sidecar.

    Protocol:
      POST /v1/voices
      POST /v1/voices/{artifact_id}/preview
      POST /v1/voices/{artifact_id}/synthesize

    The sidecar must create novel synthetic identities from parameters only.  No
    reference-audio field is sent by this client.  Audio endpoints may return
    raw audio bytes or JSON containing ``audio_base64``.
    """

    name = "voice-city"
    display_name = "Voice City Model Server"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout_s: float | None = None,
        session: requests.Session | None = None,
    ):
        self.base_url = (base_url or os.getenv("VOICE_CITY_MODEL_SERVER_URL", "")).strip().rstrip("/")
        self.token = token if token is not None else os.getenv("VOICE_CITY_MODEL_SERVER_TOKEN", "")
        self.timeout_s = float(timeout_s or os.getenv("VOICE_CITY_MODEL_SERVER_TIMEOUT_SECONDS", "120"))
        self._session = session or requests.Session()
        if self.base_url:
            parsed = urlparse(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise GenerativeProviderError("VOICE_CITY_MODEL_SERVER_URL must be an absolute http(s) URL")

    def is_available(self) -> bool:
        return bool(self.base_url)

    def _headers(self, *, accept_audio: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "audio/mpeg, application/json" if accept_audio else "application/json",
            "Content-Type": "application/json",
            "User-Agent": "acx-city-voice-city/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, *, payload: Mapping[str, Any], accept_audio: bool = False):
        if not self.is_available():
            raise GenerativeProviderError("Voice City model server is not configured")
        try:
            response = self._session.request(
                method,
                f"{self.base_url}{path}",
                json=dict(payload),
                headers=self._headers(accept_audio=accept_audio),
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise GenerativeProviderError(f"Voice City model server request failed: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else response.reason
            raise GenerativeProviderError(
                f"Voice City model server returned HTTP {response.status_code}: {detail}"
            )
        return response

    @staticmethod
    def _decode_optional(value: Any, field_name: str) -> bytes | None:
        if value in (None, ""):
            return None
        if not isinstance(value, str):
            raise GenerativeProviderError(f"Model server field {field_name} must be base64 text")
        try:
            return base64.b64decode(value, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise GenerativeProviderError(f"Model server field {field_name} is not valid base64") from exc

    @staticmethod
    def _audio_bytes(response) -> bytes:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type.startswith("audio/") or content_type == "application/octet-stream":
            audio = response.content
        else:
            try:
                payload = response.json()
                audio = base64.b64decode(str(payload.get("audio_base64") or ""), validate=True)
            except Exception as exc:  # noqa: BLE001
                raise GenerativeProviderError("Model server did not return audio bytes or audio_base64") from exc
        if not audio:
            raise GenerativeProviderError("Model server returned empty audio")
        return audio

    def create_voice(
        self,
        *,
        identity_parameters: Mapping[str, Any],
        style_parameters: Mapping[str, Any],
        seed: int,
        metadata: Mapping[str, Any] | None = None,
    ) -> VoiceArtifact:
        response = self._request(
            "POST",
            "/v1/voices",
            payload={
                "identity_parameters": dict(identity_parameters),
                "style_parameters": dict(style_parameters),
                "seed": int(seed),
                "metadata": dict(metadata or {}),
                "reference_audio": None,
            },
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GenerativeProviderError("Model server returned invalid voice-artifact JSON") from exc
        if not isinstance(payload, Mapping):
            raise GenerativeProviderError("Model server voice-artifact response must be a JSON object")
        artifact_id = str(payload.get("artifact_id") or payload.get("id") or "").strip()
        if not artifact_id:
            raise GenerativeProviderError("Model server response is missing artifact_id")
        return VoiceArtifact(
            artifact_id=artifact_id,
            provider=self.name,
            model_family=str(payload.get("model_family") or "controllable-tts"),
            model_revision=str(payload.get("model_revision") or "unknown"),
            provider_voice_id=str(payload.get("provider_voice_id") or artifact_id),
            supported_languages=(
                [str(payload.get("supported_languages"))]
                if isinstance(payload.get("supported_languages"), str)
                else [str(item) for item in payload.get("supported_languages") or ["en-US"]]
            ),
            speaker_embedding=self._decode_optional(payload.get("speaker_embedding_base64"), "speaker_embedding_base64"),
            model_artifact=self._decode_optional(payload.get("model_artifact_base64"), "model_artifact_base64"),
            speaker_embedding_key=str(payload.get("speaker_embedding_key") or "") or None,
            model_artifact_key=str(payload.get("model_artifact_key") or "") or None,
            quality_score=float(payload["quality_score"]) if payload.get("quality_score") is not None else None,
            consistency_score=float(payload["consistency_score"]) if payload.get("consistency_score") is not None else None,
            metadata=dict(payload.get("metadata") or {}),
        )

    def preview_voice(
        self,
        *,
        voice_artifact_id: str,
        text: str,
        performance_parameters: Mapping[str, Any],
    ) -> bytes:
        response = self._request(
            "POST",
            f"/v1/voices/{quote(str(voice_artifact_id), safe='')}/preview",
            payload={"text": text, "performance_parameters": dict(performance_parameters)},
            accept_audio=True,
        )
        return self._audio_bytes(response)

    def synthesize(
        self,
        *,
        text: str,
        voice_artifact_id: str,
        performance_parameters: Mapping[str, Any],
    ) -> bytes:
        response = self._request(
            "POST",
            f"/v1/voices/{quote(str(voice_artifact_id), safe='')}/synthesize",
            payload={"text": text, "performance_parameters": dict(performance_parameters)},
            accept_audio=True,
        )
        return self._audio_bytes(response)
