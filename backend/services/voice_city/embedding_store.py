"""Durable persistence for optimized speaker identities.

When a persistent-identity optimization succeeds, the resulting speaker
embedding and model artifact must outlive the model server that produced
them: production jobs, exports, and audits all reference them by storage
key. This module owns that persistence so ``voice_optimizer`` never talks
to the storage backend directly.

Two cases are supported, mirroring ``GenerativeVoiceArtifact``:

* The model server returned raw bytes (``speaker_embedding`` /
  ``model_artifact``) — we store them ourselves and mint org-scoped keys.
* The model server already persisted its own artifacts and returned keys —
  we trust and record those keys instead of duplicating the payload.

A JSON manifest is always written so every optimized identity has a
self-describing provenance record containing hashes, never audio or
manuscript text.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from storage import get_storage

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers
    from .generative_provider import GenerativeVoiceArtifact


@dataclass(frozen=True)
class PersistedIdentityKeys:
    """Storage keys recorded on the optimized voice version."""

    speaker_embedding_key: str | None
    model_artifact_key: str | None
    manifest_key: str


class EmbeddingStore:
    """Persist speaker-identity artifacts under the owning organization."""

    def __init__(self, storage=None):
        self._storage = storage

    def _backend(self):
        return self._storage or get_storage()

    @staticmethod
    def _prefix(organization_id: str, voice_id: str, version_id: str) -> str:
        return f"org/{organization_id}/voice-city/voices/{voice_id}/versions/{version_id}"

    def persist(
        self,
        *,
        organization_id: str,
        voice_id: str,
        version_id: str,
        artifact: "GenerativeVoiceArtifact",
    ) -> PersistedIdentityKeys:
        storage = self._backend()
        prefix = self._prefix(organization_id, voice_id, version_id)

        embedding_key = artifact.speaker_embedding_key
        embedding_sha = None
        if artifact.speaker_embedding is not None:
            embedding_key = f"{prefix}/speaker-embedding.bin"
            embedding_sha = hashlib.sha256(artifact.speaker_embedding).hexdigest()
            storage.put_bytes(
                embedding_key,
                artifact.speaker_embedding,
                content_type="application/octet-stream",
            )

        model_key = artifact.model_artifact_key
        model_sha = None
        if artifact.model_artifact is not None:
            model_key = f"{prefix}/model-artifact.bin"
            model_sha = hashlib.sha256(artifact.model_artifact).hexdigest()
            storage.put_bytes(
                model_key,
                artifact.model_artifact,
                content_type="application/octet-stream",
            )

        manifest_key = f"{prefix}/identity-manifest.json"
        manifest = {
            "schema": "voice-city/identity-manifest/v1",
            "organization_id": organization_id,
            "voice_id": voice_id,
            "voice_version_id": version_id,
            "artifact_id": artifact.artifact_id,
            "provider": artifact.provider,
            "model_family": artifact.model_family,
            "model_revision": artifact.model_revision,
            "provider_voice_id": artifact.provider_voice_id,
            "supported_languages": list(artifact.supported_languages),
            "speaker_embedding_key": embedding_key,
            "speaker_embedding_sha256": embedding_sha,
            "model_artifact_key": model_key,
            "model_artifact_sha256": model_sha,
            "reference_audio": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        storage.put_bytes(
            manifest_key,
            json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8"),
            content_type="application/json",
        )
        return PersistedIdentityKeys(
            speaker_embedding_key=embedding_key,
            model_artifact_key=model_key,
            manifest_key=manifest_key,
        )
