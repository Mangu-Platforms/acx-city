"""Voice catalog service — browse, filter, preview, and compare voices.

Unifies the ``StockVoice`` (curated catalog with pre-computed metadata) and
``VoiceCityVoice`` (versioned, parameterized user-created voices) models into
a single browsing experience with pagination, caching, and embedding-based
similarity search.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from db.base import utcnow
from db.voice_models import VoiceCityPreview, VoiceCityVoice, VoiceCityVoiceVersion
from db.voxengine_models import StockVoice


# ---------------------------------------------------------------------------
# VoiceFilter — composable SQL filter builder
# ---------------------------------------------------------------------------

@dataclass
class VoiceFilter:
    """Declarative filter set that compiles to SQLAlchemy WHERE clauses.

    Every field is optional; ``None`` means "don't filter on this".
    """

    gender: Optional[str] = None
    accent: Optional[str] = None
    age_range: Optional[str] = None
    provider: Optional[str] = None
    style_tags: Optional[list[str]] = None
    language: Optional[str] = None
    is_cloneable: Optional[bool] = None
    search: Optional[str] = None
    source: Optional[str] = None
    organization_id: Optional[str] = None
    is_active: Optional[bool] = True  # default: only active voices

    # ------------------------------------------------------------------
    # SQLAlchemy clause builder for StockVoice
    # ------------------------------------------------------------------
    def apply_to_stock_query(self, query):
        """Return *query* with all non-None filters applied (StockVoice)."""
        if self.gender is not None:
            query = query.where(StockVoice.gender == self.gender)
        if self.accent is not None:
            query = query.where(StockVoice.accent == self.accent)
        if self.age_range is not None:
            query = query.where(StockVoice.age_range == self.age_range)
        if self.provider is not None:
            query = query.where(StockVoice.provider == self.provider)
        if self.style_tags:
            # JSONB array-contains: voice must have at least one matching tag
            for tag in self.style_tags:
                query = query.where(
                    func.json_contains(StockVoice.style_tags, f'"{tag}"')
                )
        if self.language is not None:
            query = query.where(
                func.json_contains(StockVoice.languages, f'"{self.language}"')
            )
        if self.is_cloneable is not None:
            query = query.where(StockVoice.is_cloneable == self.is_cloneable)
        if self.is_active is not None:
            query = query.where(StockVoice.is_active == self.is_active)
        if self.source is not None:
            query = query.where(StockVoice.source == self.source)
        if self.organization_id is not None:
            # Include global voices (NULL org) and org-scoped voices
            query = query.where(
                or_(
                    StockVoice.organization_id.is_(None),
                    StockVoice.organization_id == self.organization_id,
                )
            )
        if self.search:
            pattern = f"%{self.search}%"
            query = query.where(
                or_(
                    StockVoice.display_name.ilike(pattern),
                    StockVoice.description.ilike(pattern),
                    StockVoice.slug.ilike(pattern),
                )
            )
        return query

    # ------------------------------------------------------------------
    # SQLAlchemy clause builder for VoiceCityVoice
    # ------------------------------------------------------------------
    def apply_to_voice_city_query(self, query):
        """Return *query* with all non-None filters applied (VoiceCityVoice)."""
        if self.provider is not None:
            query = query.where(VoiceCityVoice.provider == self.provider)
        if self.organization_id is not None:
            query = query.where(
                VoiceCityVoice.organization_id == self.organization_id
            )
        if self.search:
            pattern = f"%{self.search}%"
            query = query.where(
                or_(
                    VoiceCityVoice.name.ilike(pattern),
                    VoiceCityVoice.description.ilike(pattern),
                )
            )
        # VoiceCityVoice doesn't have gender/accent/style_tags columns
        # directly — those live in canonical_parameters.  For simplicity we
        # only apply those filters to the StockVoice side of the union.
        return query


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _serialize_stock_voice(v: StockVoice) -> dict[str, Any]:
    return {
        "id": v.id,
        "source_table": "stock",
        "slug": v.slug,
        "name": v.display_name,
        "gender": v.gender,
        "accent": v.accent,
        "age_range": v.age_range,
        "style_tags": v.style_tags or [],
        "description": v.description,
        "provider": v.provider,
        "provider_voice_id": v.provider_voice_id,
        "sample_url": v.sample_audio_url,
        "languages": v.languages or ["en"],
        "emotion_tags": v.emotion_tags or [],
        "is_cloneable": v.is_cloneable,
        "is_active": v.is_active,
        "has_embedding": v.latent_s3_key is not None,
        "voice_city_voice_id": v.voice_city_voice_id,
        "source": v.source,
    }


def _serialize_voice_city_voice(
    v: VoiceCityVoice,
    version: VoiceCityVoiceVersion | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": v.id,
        "source_table": "voice_city",
        "slug": v.name,  # VoiceCityVoice uses name as slug equivalent
        "name": v.name,
        "gender": None,  # Not stored directly; could be in parameters
        "accent": None,
        "age_range": None,
        "style_tags": v.tags or [],
        "description": v.description,
        "provider": v.provider,
        "provider_voice_id": None,
        "sample_url": None,
        "languages": None,
        "emotion_tags": [],
        "is_cloneable": False,
        "is_active": v.status in ("ready", "published"),
        "has_embedding": False,
        "voice_city_voice_id": None,
        "source": "voice_city",
        "voice_type": v.voice_type,
        "status": v.status,
        "visibility": v.visibility,
        "default_use_cases": v.default_use_cases or [],
    }
    if version:
        result["provider_voice_id"] = version.provider_voice_id
        result["languages"] = version.supported_languages
        result["has_embedding"] = version.speaker_embedding_key is not None
        result["quality_score"] = version.quality_score
        result["consistency_score"] = version.consistency_score
    return result


# ---------------------------------------------------------------------------
# VoiceCatalogService
# ---------------------------------------------------------------------------

# Simple in-memory preview cache (voice_id:text_hash → cache entry).
# For production, swap with Redis/memcached keyed by the content hash.
_PREVIEW_CACHE_TTL_S = 3600  # 1 hour


class VoiceCatalogService:
    """Browse, filter, preview, and compare voices across both catalog models."""

    def __init__(
        self,
        session: Session,
        organization_id: str | None = None,
    ) -> None:
        self._session = session
        self._organization_id = organization_id
        # In-memory preview cache: content_hash → {result, expires_at}
        self._preview_cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # list_voices
    # ------------------------------------------------------------------
    def list_voices(
        self,
        filters: dict[str, Any] | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        """Paginated listing combining StockVoice and VoiceCityVoice.

        Returns ``{voices: [...], total: int, page: int, pages: int}``.
        """
        vf = VoiceFilter(
            **(filters or {}),
            organization_id=self._organization_id,
        )
        per_page = max(1, min(per_page, 200))
        page = max(1, page)
        offset = (page - 1) * per_page

        # --- Stock voices ---
        stock_q = select(StockVoice)
        stock_q = vf.apply_to_stock_query(stock_q)
        stock_count_q = select(func.count()).select_from(stock_q.subquery())
        stock_total = self._session.execute(stock_count_q).scalar_one()

        stock_rows = (
            self._session.execute(
                stock_q.order_by(StockVoice.display_name).offset(offset).limit(per_page)
            )
            .scalars()
            .all()
        )

        # --- Voice City voices ---
        vc_q = select(VoiceCityVoice).where(
            VoiceCityVoice.deleted_at.is_(None),
            VoiceCityVoice.visibility.in_(("public", "shared")),
        )
        if vf.organization_id:
            # Also include private voices owned by the requesting org
            vc_q = vc_q.where(
                or_(
                    VoiceCityVoice.visibility.in_(("public", "shared")),
                    VoiceCityVoice.organization_id == vf.organization_id,
                )
            )
        vc_q = vf.apply_to_voice_city_query(vc_q)
        vc_count_q = select(func.count()).select_from(vc_q.subquery())
        vc_total = self._session.execute(vc_count_q).scalar_one()

        vc_rows = (
            self._session.execute(
                vc_q.order_by(VoiceCityVoice.name).offset(offset).limit(per_page)
            )
            .scalars()
            .all()
        )

        # Merge results — stock voices first, then voice city voices
        voices: list[dict[str, Any]] = []
        for sv in stock_rows:
            voices.append(_serialize_stock_voice(sv))
        for vc in vc_rows:
            version = self._current_version(vc)
            voices.append(_serialize_voice_city_voice(vc, version))

        total = stock_total + vc_total
        pages = math.ceil(total / per_page) if per_page else 0

        return {
            "voices": voices,
            "total": total,
            "page": page,
            "pages": pages,
        }

    # ------------------------------------------------------------------
    # get_voice
    # ------------------------------------------------------------------
    def get_voice(self, voice_id: str) -> dict[str, Any]:
        """Return full voice detail with emotion tags, sample URL, and
        latent embedding availability.

        Raises ``ValueError`` if the voice is not found.
        """
        # Try StockVoice first
        stock = self._session.get(StockVoice, voice_id)
        if stock and stock.is_active:
            result = _serialize_stock_voice(stock)
            result["sample_audio_url"] = stock.sample_audio_url
            result["latent_embedding_available"] = stock.latent_s3_key is not None
            result["organization_id"] = stock.organization_id
            return result

        # Then VoiceCityVoice
        vc = self._session.get(VoiceCityVoice, voice_id)
        if vc and vc.deleted_at is None:
            version = self._current_version(vc)
            result = _serialize_voice_city_voice(vc, version)
            result["latent_embedding_available"] = (
                version.speaker_embedding_key is not None if version else False
            )
            # Fetch latest preview if available
            preview = self._latest_preview(vc.id)
            if preview and preview.audio_key:
                result["sample_audio_url"] = preview.audio_key
            return result

        raise ValueError(f"Voice {voice_id!r} not found")

    # ------------------------------------------------------------------
    # preview_voice
    # ------------------------------------------------------------------
    def preview_voice(
        self,
        voice_id: str,
        text: str | None = None,
        emotion: str | None = None,
    ) -> dict[str, Any]:
        """Generate (or return cached) 5-second preview audio.

        Returns ``{voice_id, text, emotion, audio_key, duration_s, cached}``.
        """
        default_text = (
            "The quick brown fox jumps over the lazy dog. "
            "This is a voice preview."
        )
        preview_text = text or default_text

        # Cache key: voice + text + emotion
        raw = f"{voice_id}:{preview_text}:{emotion or ''}"
        content_hash = hashlib.sha256(raw.encode()).hexdigest()

        cached = self._preview_cache.get(content_hash)
        if cached and cached["expires_at"] > utcnow():
            return {
                "voice_id": voice_id,
                "text": preview_text,
                "emotion": emotion,
                "audio_key": cached["audio_key"],
                "duration_s": cached["duration_s"],
                "cached": True,
            }

        # Resolve voice metadata
        provider_voice_id: str | None = None
        provider: str = "edge"
        overrides: dict[str, Any] = {}

        stock = self._session.get(StockVoice, voice_id)
        if stock and stock.is_active:
            provider_voice_id = stock.provider_voice_id
            provider = stock.provider
        else:
            vc = self._session.get(VoiceCityVoice, voice_id)
            if vc and vc.deleted_at is None:
                version = self._current_version(vc)
                if version:
                    provider_voice_id = version.provider_voice_id
                    provider = version.provider
                    overrides = version.default_style_parameters or {}

        if provider_voice_id is None:
            raise ValueError(f"Voice {voice_id!r} not found or has no provider mapping")

        # Apply emotion as a style parameter override
        if emotion:
            overrides["emotion"] = emotion

        # Delegate to the preview renderer (existing service)
        from services.voice_city.preview_renderer import render_preview

        preview_result = render_preview(
            session=self._session,
            organization_id=self._organization_id or "",
            text=preview_text,
            provider=provider,
            provider_voice_id=provider_voice_id,
            parameter_overrides=overrides,
        )

        audio_key = preview_result.get("audio_key", "")
        duration_s = preview_result.get("duration_s", 5.0)

        # Persist a VoiceCityPreview record for auditability
        if self._organization_id:
            pv = VoiceCityPreview(
                organization_id=self._organization_id,
                voice_version_id=None,
                candidate_id=None,
                text=preview_text,
                parameter_overrides=overrides,
                provider=provider,
                provider_voice_id=provider_voice_id,
                audio_key=audio_key,
                content_hash=content_hash,
                voice_fingerprint="",
                duration_s=duration_s,
                status="done",
            )
            self._session.add(pv)
            self._session.flush()

        # Update in-memory cache
        self._preview_cache[content_hash] = {
            "audio_key": audio_key,
            "duration_s": duration_s,
            "expires_at": datetime.now(timezone.utc).replace(
                second=0, microsecond=0
            ).timestamp()
            + _PREVIEW_CACHE_TTL_S,
        }
        # Convert expires_at back to datetime for comparison on next call
        self._preview_cache[content_hash]["expires_at"] = datetime.fromtimestamp(
            self._preview_cache[content_hash]["expires_at"], tz=timezone.utc
        )

        return {
            "voice_id": voice_id,
            "text": preview_text,
            "emotion": emotion,
            "audio_key": audio_key,
            "duration_s": duration_s,
            "cached": False,
        }

    # ------------------------------------------------------------------
    # compare_voices
    # ------------------------------------------------------------------
    def compare_voices(
        self,
        voice_ids: list[str],
        text: str,
        blind: bool = False,
    ) -> dict[str, Any]:
        """Generate side-by-side preview audio for multiple voices.

        When ``blind`` is true, voice metadata is redacted from the result
        so the caller can do a blind listening test.

        Returns ``{comparisons: [{voice_id?, text, audio_key, duration_s}]}``.
        """
        if not voice_ids:
            raise ValueError("At least one voice_id is required")
        if len(voice_ids) > 10:
            raise ValueError("Maximum 10 voices for comparison")

        comparisons: list[dict[str, Any]] = []
        for vid in voice_ids:
            try:
                result = self.preview_voice(voice_id=vid, text=text)
                entry: dict[str, Any] = {
                    "text": result["text"],
                    "audio_key": result["audio_key"],
                    "duration_s": result["duration_s"],
                    "cached": result["cached"],
                }
                if not blind:
                    entry["voice_id"] = vid
                else:
                    entry["voice_id"] = f"blind_{len(comparisons) + 1}"
                comparisons.append(entry)
            except ValueError:
                comparisons.append(
                    {
                        "voice_id": vid if not blind else f"blind_{len(comparisons) + 1}",
                        "text": text,
                        "audio_key": None,
                        "duration_s": None,
                        "error": "Voice not available",
                    }
                )

        return {"comparisons": comparisons}

    # ------------------------------------------------------------------
    # seed_from_provider
    # ------------------------------------------------------------------
    def seed_from_provider(
        self,
        provider: str,
        voices: list[dict[str, Any]],
    ) -> int:
        """Bulk upsert stock voices from a provider catalog.

        Each item in *voices* should contain at minimum:
        ``slug``, ``display_name``, ``gender``, ``accent``, ``provider_voice_id``.

        Optional keys: ``age_range``, ``style_tags``, ``description``,
        ``sample_audio_url``, ``languages``, ``emotion_tags``,
        ``is_cloneable``, ``source``.

        Returns the number of rows inserted or updated.
        """
        count = 0
        for voice_data in voices:
            slug = voice_data.get("slug")
            if not slug:
                continue

            existing = (
                self._session.execute(
                    select(StockVoice).where(StockVoice.slug == slug)
                )
                .scalars()
                .first()
            )

            if existing:
                # Update mutable fields
                existing.display_name = voice_data.get("display_name", existing.display_name)
                existing.gender = voice_data.get("gender", existing.gender)
                existing.accent = voice_data.get("accent", existing.accent)
                existing.age_range = voice_data.get("age_range", existing.age_range)
                existing.style_tags = voice_data.get("style_tags", existing.style_tags)
                existing.description = voice_data.get("description", existing.description)
                existing.provider = provider
                existing.provider_voice_id = voice_data.get(
                    "provider_voice_id", existing.provider_voice_id
                )
                existing.sample_audio_url = voice_data.get(
                    "sample_audio_url", existing.sample_audio_url
                )
                existing.languages = voice_data.get("languages", existing.languages)
                existing.emotion_tags = voice_data.get("emotion_tags", existing.emotion_tags)
                existing.is_cloneable = voice_data.get("is_cloneable", existing.is_cloneable)
                existing.source = voice_data.get("source", existing.source)
                existing.latent_s3_key = voice_data.get(
                    "latent_s3_key", existing.latent_s3_key
                )
            else:
                sv = StockVoice(
                    slug=slug,
                    display_name=voice_data["display_name"],
                    gender=voice_data["gender"],
                    accent=voice_data["accent"],
                    age_range=voice_data.get("age_range"),
                    style_tags=voice_data.get("style_tags", []),
                    description=voice_data.get("description"),
                    provider=provider,
                    provider_voice_id=voice_data.get("provider_voice_id"),
                    sample_audio_url=voice_data.get("sample_audio_url"),
                    languages=voice_data.get("languages", ["en"]),
                    emotion_tags=voice_data.get("emotion_tags", []),
                    is_cloneable=voice_data.get("is_cloneable", False),
                    source=voice_data.get("source", provider),
                    is_active=True,
                    latent_s3_key=voice_data.get("latent_s3_key"),
                    organization_id=voice_data.get("organization_id"),
                )
                self._session.add(sv)
            count += 1

        self._session.flush()
        return count

    # ------------------------------------------------------------------
    # get_emotion_tags
    # ------------------------------------------------------------------
    def get_emotion_tags(self, voice_id: str) -> list[str]:
        """Return the list of supported emotion tags for a voice."""
        stock = self._session.get(StockVoice, voice_id)
        if stock and stock.is_active:
            return list(stock.emotion_tags or [])

        vc = self._session.get(VoiceCityVoice, voice_id)
        if vc and vc.deleted_at is None:
            # Extract emotion capability from canonical_parameters
            version = self._current_version(vc)
            if version and version.canonical_parameters:
                params = version.canonical_parameters
                return list(params.get("emotion_tags", params.get("emotions", [])))
            return []

        raise ValueError(f"Voice {voice_id!r} not found")

    # ------------------------------------------------------------------
    # search_by_embedding
    # ------------------------------------------------------------------
    def search_by_embedding(
        self,
        embedding: np.ndarray,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Find the most similar voices by cosine similarity against stored
        speaker embeddings.

        Returns a list sorted by descending similarity (each entry includes
        the voice dict plus a ``similarity`` score in [0, 1]).
        """
        top_k = max(1, min(top_k, 50))

        # Fetch all voices that have a latent_s3_key (embedding stored in S3)
        stock_voices = (
            self._session.execute(
                select(StockVoice).where(
                    StockVoice.is_active.is_(True),
                    StockVoice.latent_s3_key.isnot(None),
                )
            )
            .scalars()
            .all()
        )

        # Also fetch VoiceCityVoiceVersions with speaker_embedding_key
        vc_versions = (
            self._session.execute(
                select(VoiceCityVoiceVersion).where(
                    VoiceCityVoiceVersion.speaker_embedding_key.isnot(None),
                    VoiceCityVoiceVersion.status.in_(("ready", "published")),
                )
            )
            .scalars()
            .all()
        )

        # Normalize the query embedding
        query_emb = np.asarray(embedding, dtype=np.float32).flatten()
        query_norm = np.linalg.norm(query_emb)
        if query_norm == 0:
            raise ValueError("Query embedding must be non-zero")
        query_emb = query_emb / query_norm

        scored: list[tuple[float, dict[str, Any]]] = []

        # Score stock voices
        for sv in stock_voices:
            stored = self._load_embedding(sv.latent_s3_key)
            if stored is None:
                continue
            sim = self._cosine_similarity(query_emb, stored)
            entry = _serialize_stock_voice(sv)
            entry["similarity"] = round(float(sim), 6)
            scored.append((sim, entry))

        # Score voice city versions
        for ver in vc_versions:
            stored = self._load_embedding(ver.speaker_embedding_key)
            if stored is None:
                continue
            sim = self._cosine_similarity(query_emb, stored)
            # Get the parent voice for serialization
            vc = self._session.get(VoiceCityVoice, ver.voice_id)
            if vc is None:
                continue
            entry = _serialize_voice_city_voice(vc, ver)
            entry["similarity"] = round(float(sim), 6)
            scored.append((sim, entry))

        # Sort descending by similarity and take top_k
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _current_version(
        self, voice: VoiceCityVoice
    ) -> VoiceCityVoiceVersion | None:
        """Return the current version of a VoiceCityVoice, or the latest."""
        if voice.current_version_id:
            ver = self._session.get(VoiceCityVoiceVersion, voice.current_version_id)
            if ver:
                return ver
        # Fallback: latest version by version_number
        return (
            self._session.execute(
                select(VoiceCityVoiceVersion)
                .where(VoiceCityVoiceVersion.voice_id == voice.id)
                .order_by(VoiceCityVoiceVersion.version_number.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )

    def _latest_preview(self, voice_id: str) -> VoiceCityPreview | None:
        """Return the most recent preview for a voice, if any."""
        # Previews are linked by voice_version_id, not voice_id directly.
        # We need to find the latest preview via the voice's versions.
        version_ids = [
            v.id
            for v in self._session.execute(
                select(VoiceCityVoiceVersion.id).where(
                    VoiceCityVoiceVersion.voice_id == voice_id
                )
            ).scalars()
        ]
        if not version_ids:
            return None
        return (
            self._session.execute(
                select(VoiceCityPreview)
                .where(VoiceCityPreview.voice_version_id.in_(version_ids))
                .order_by(VoiceCityPreview.created_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two 1-D vectors."""
        b = np.asarray(b, dtype=np.float32).flatten()
        if b.size != a.size:
            return 0.0
        b_norm = np.linalg.norm(b)
        if b_norm == 0:
            return 0.0
        return float(np.dot(a, b / b_norm))

    def _load_embedding(self, s3_key: str | None) -> np.ndarray | None:
        """Load a speaker embedding from object storage.

        Returns a normalized float32 1-D array, or ``None`` if the key is
        missing or the object cannot be read.
        """
        if not s3_key:
            return None
        try:
            from storage import get_storage

            data = get_storage().get_bytes(s3_key)
            emb = np.load(
                __import__("io").BytesIO(data)
            ).astype(np.float32).flatten()
            norm = np.linalg.norm(emb)
            if norm == 0:
                return None
            return emb / norm
        except Exception:
            return None
