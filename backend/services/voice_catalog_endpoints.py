"""Voice Catalog API — browse, preview, compare, and manage voices.

Flask Blueprint exposing the stock voice catalog (``StockVoice`` model) with
filtering, pagination, preview generation, comparison, and voice-clone
management endpoints.

Registered at ``/api/voices``.
"""
from __future__ import annotations

import math
import os
import uuid
from typing import Any

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from auth import current_identity, require_auth
from db.voxengine_models import StockVoice, VoiceClone

voice_catalog_bp = Blueprint("voice_catalog", __name__, url_prefix="/api/voices")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _paginate(
    query,
    model,
    page: int,
    per_page: int,
) -> dict[str, Any]:
    """Apply offset/limit pagination and return the envelope dict."""
    page = max(1, page)
    per_page = max(1, min(per_page, 100))

    total: int = query.with_entities(func.count()).scalar() or 0
    pages = max(1, math.ceil(total / per_page))
    rows = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "voices": [_serialize_voice(v) for v in rows],
        "total": total,
        "page": page,
        "pages": pages,
    }


def _serialize_voice(voice: StockVoice) -> dict[str, Any]:
    """Serialize a ``StockVoice`` row into a catalog-friendly dict."""
    return {
        "id": voice.id,
        "slug": voice.slug,
        "display_name": voice.display_name,
        "gender": voice.gender,
        "accent": voice.accent,
        "age_range": voice.age_range,
        "style_tags": voice.style_tags or [],
        "description": voice.description,
        "provider": voice.provider,
        "provider_voice_id": voice.provider_voice_id,
        "sample_audio_url": voice.sample_audio_url,
        "languages": voice.languages or ["en"],
        "emotion_tags": voice.emotion_tags or [],
        "is_active": voice.is_active,
        "is_cloneable": voice.is_cloneable,
        "source": voice.source,
        "has_latent_embedding": voice.latent_s3_key is not None,
        "created_at": voice.created_at.isoformat() if voice.created_at else None,
    }


def _serialize_voice_detail(voice: StockVoice) -> dict[str, Any]:
    """Extended serialization for the single-voice detail endpoint."""
    data = _serialize_voice(voice)
    data["latent_s3_key"] = voice.latent_s3_key
    data["organization_id"] = voice.organization_id
    data["voice_city_voice_id"] = voice.voice_city_voice_id
    return data


def _serialize_clone(clone: VoiceClone) -> dict[str, Any]:
    """Serialize a ``VoiceClone`` row."""
    return {
        "id": clone.id,
        "name": clone.name,
        "status": clone.status,
        "provider": clone.provider,
        "reference_duration_seconds": (
            float(clone.reference_duration_seconds)
            if clone.reference_duration_seconds is not None
            else None
        ),
        "safety_similarity_score": clone.safety_similarity_score,
        "error": clone.error,
        "created_at": clone.created_at.isoformat() if clone.created_at else None,
    }


def _get_voice_or_404(voice_id: str, session: Session) -> StockVoice:
    """Fetch a stock voice by id or abort with 404."""
    voice = session.get(StockVoice, voice_id)
    if voice is None:
        return jsonify({"error": "Voice not found"}), 404
    return voice


# --------------------------------------------------------------------------- #
# 1. GET /api/voices — List voices with filtering & pagination
# --------------------------------------------------------------------------- #

@voice_catalog_bp.route("", methods=["GET"])
@require_auth
def list_voices():
    """List stock voices with optional filters and pagination.

    Query params:
        provider, gender, accent, age_range, style_tag, language,
        is_cloneable, search, page (default 1), per_page (default 20).
    """
    session: Session = g.db
    identity = current_identity()

    query = session.query(StockVoice).filter(StockVoice.is_active.is_(True))

    # --- Filters ---
    provider = request.args.get("provider")
    if provider:
        query = query.filter(StockVoice.provider == provider)

    gender = request.args.get("gender")
    if gender:
        query = query.filter(StockVoice.gender == gender)

    accent = request.args.get("accent")
    if accent:
        query = query.filter(StockVoice.accent == accent)

    age_range = request.args.get("age_range")
    if age_range:
        query = query.filter(StockVoice.age_range == age_range)

    style_tag = request.args.get("style_tag")
    if style_tag:
        # JSON column — filter by containment
        query = query.filter(StockVoice.style_tags.contains(style_tag))

    language = request.args.get("language")
    if language:
        query = query.filter(StockVoice.languages.contains(language))

    is_cloneable = request.args.get("is_cloneable")
    if is_cloneable is not None:
        query = query.filter(StockVoice.is_cloneable == (is_cloneable.lower() in ("true", "1", "yes")))

    search = request.args.get("search")
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                StockVoice.display_name.ilike(pattern),
                StockVoice.description.ilike(pattern),
                StockVoice.slug.ilike(pattern),
            )
        )

    # Org-scoped voices + global voices
    query = query.filter(
        or_(
            StockVoice.organization_id.is_(None),
            StockVoice.organization_id == identity.org.id,
        )
    )

    # --- Ordering & pagination ---
    query = query.order_by(StockVoice.display_name.asc())

    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))

    return jsonify(_paginate(query, StockVoice, page, per_page))


# --------------------------------------------------------------------------- #
# 2. GET /api/voices/<voice_id> — Voice detail
# --------------------------------------------------------------------------- #

@voice_catalog_bp.route("/<voice_id>", methods=["GET"])
@require_auth
def get_voice(voice_id: str):
    """Return detailed metadata for a single voice, including emotion tags,
    sample URL, and latent-embedding availability."""
    session: Session = g.db
    identity = current_identity()

    voice = session.get(StockVoice, voice_id)
    if voice is None:
        return jsonify({"error": "Voice not found"}), 404

    # Org-scope check: only show global or own-org voices
    if voice.organization_id is not None and voice.organization_id != identity.org.id:
        return jsonify({"error": "Voice not found"}), 404

    return jsonify(_serialize_voice_detail(voice))


# --------------------------------------------------------------------------- #
# 3. POST /api/voices/<voice_id>/preview — Generate 5-second preview
# --------------------------------------------------------------------------- #

@voice_catalog_bp.route("/<voice_id>/preview", methods=["POST"])
@require_auth
def preview_voice(voice_id: str):
    """Synthesise a short (~5 s) preview clip and return the audio URL.

    Request body (JSON, optional):
        text: Custom preview text (uses a default if omitted).
        emotion: Emotion/style hint.
    """
    session: Session = g.db
    identity = current_identity()

    voice = session.get(StockVoice, voice_id)
    if voice is None:
        return jsonify({"error": "Voice not found"}), 404

    if voice.organization_id is not None and voice.organization_id != identity.org.id:
        return jsonify({"error": "Voice not found"}), 404

    data = request.get_json(silent=True) or {}
    preview_text = data.get("text") or (
        "The morning light filtered through the blinds, painting golden "
        "stripes across the wooden floor. She took a deep breath and began."
    )
    emotion = data.get("emotion")

    # Lazy-import to avoid circular deps at module level
    from services.voice_preview import VoicePreviewService
    from storage import get_storage

    storage = get_storage()
    # Build a minimal provider registry — we only need the voice's provider.
    from services.providers import ProviderRegistry

    registry = ProviderRegistry()
    provider = registry.get(voice.provider)
    if provider is None:
        return jsonify({"error": f"TTS provider '{voice.provider}' is not available"}), 503

    service = VoicePreviewService(
        storage_backend=storage,
        provider_registry={voice.provider: provider},
    )

    try:
        result = service.preview_voice(
            text=preview_text,
            voice_id=voice.provider_voice_id or voice.slug,
            provider=voice.provider,
            emotion=emotion,
        )
    except Exception as exc:
        return jsonify({"error": f"Preview generation failed: {exc}"}), 500

    # The preview service is async in spirit but the existing codebase uses
    # sync Flask; if the service returns a coroutine, run it.
    import asyncio

    if asyncio.iscoroutine(result):
        result = asyncio.get_event_loop().run_until_complete(result)

    return jsonify({
        "audio_url": result.get("url", ""),
        "duration_s": result.get("duration_s", 5.0),
    })


# --------------------------------------------------------------------------- #
# 4. POST /api/voices/compare — Side-by-side voice comparison
# --------------------------------------------------------------------------- #

@voice_catalog_bp.route("/compare", methods=["POST"])
@require_auth
def compare_voices():
    """Compare multiple voices reading the same text.

    Body:
        voice_ids: list[str] — 2–10 voice IDs.
        text: str — shared script text.
        blind: bool — anonymise labels (default false).
    """
    data = request.get_json(silent=True) or {}
    voice_ids: list[str] = data.get("voice_ids") or []
    text: str = data.get("text") or ""
    blind: bool = bool(data.get("blind", False))

    if not isinstance(voice_ids, list) or len(voice_ids) < 2:
        return jsonify({"error": "Provide at least two voice_ids"}), 400
    if len(voice_ids) > 10:
        return jsonify({"error": "Comparison is limited to 10 voices"}), 400
    if not text.strip():
        return jsonify({"error": "Text is required"}), 400

    session: Session = g.db
    identity = current_identity()

    # Validate all voices exist and are accessible
    voices: list[StockVoice] = []
    for vid in voice_ids:
        voice = session.get(StockVoice, vid)
        if voice is None:
            return jsonify({"error": f"Voice '{vid}' not found"}), 404
        if voice.organization_id is not None and voice.organization_id != identity.org.id:
            return jsonify({"error": f"Voice '{vid}' not found"}), 404
        voices.append(voice)

    # Generate previews for each voice
    from services.providers import ProviderRegistry
    from services.voice_preview import VoicePreviewService
    from storage import get_storage

    registry = ProviderRegistry()
    storage = get_storage()

    # Group voices by provider for efficiency
    providers_map: dict[str, Any] = {}
    for v in voices:
        if v.provider not in providers_map:
            p = registry.get(v.provider)
            if p is None:
                return jsonify({"error": f"TTS provider '{v.provider}' is not available"}), 503
            providers_map[v.provider] = p

    service = VoicePreviewService(
        storage_backend=storage,
        provider_registry=providers_map,
    )

    import asyncio

    clips: list[dict[str, Any]] = []
    labels = [chr(ord("A") + i) for i in range(len(voice_ids))]

    for idx, voice in enumerate(voices):
        try:
            result = service.preview_voice(
                text=text,
                voice_id=voice.provider_voice_id or voice.slug,
                provider=voice.provider,
            )
            if asyncio.iscoroutine(result):
                result = asyncio.get_event_loop().run_until_complete(result)
        except Exception as exc:
            return jsonify({"error": f"Preview failed for voice '{voice_ids[idx]}': {exc}"}), 500

        clip: dict[str, Any] = {
            "index": idx,
            "audio_url": result.get("url", ""),
            "duration_s": result.get("duration_s", 5.0),
        }
        if blind:
            clip["label"] = labels[idx]
            clip["voice_id"] = f"blind_{labels[idx]}"
        else:
            clip["voice_id"] = voice.id
            clip["display_name"] = voice.display_name
        clips.append(clip)

    comparison_id = uuid.uuid4().hex[:12]

    return jsonify({
        "comparison_id": comparison_id,
        "blind": blind,
        "clips": clips,
    })


# --------------------------------------------------------------------------- #
# 5. GET /api/voices/<voice_id>/emotions — Supported emotion tags
# --------------------------------------------------------------------------- #

@voice_catalog_bp.route("/<voice_id>/emotions", methods=["GET"])
@require_auth
def list_emotions(voice_id: str):
    """Return the list of supported emotion/style tags for a voice."""
    session: Session = g.db
    identity = current_identity()

    voice = session.get(StockVoice, voice_id)
    if voice is None:
        return jsonify({"error": "Voice not found"}), 404

    if voice.organization_id is not None and voice.organization_id != identity.org.id:
        return jsonify({"error": "Voice not found"}), 404

    return jsonify({
        "voice_id": voice.id,
        "emotion_tags": voice.emotion_tags or [],
    })


# --------------------------------------------------------------------------- #
# 6. POST /api/voices/clone — Upload reference audio for cloning
# --------------------------------------------------------------------------- #

@voice_catalog_bp.route("/clone", methods=["POST"])
@require_auth
def create_clone():
    """Create a voice clone from uploaded reference audio.

    Multipart form fields:
        audio: The reference audio file (10–30 s recommended).
        name: Display name for the clone.
    """
    session: Session = g.db
    identity = current_identity()

    # Validate multipart upload
    if "audio" not in request.files:
        return jsonify({"error": "Audio file is required (field name: 'audio')"}), 400

    audio_file = request.files["audio"]
    if not audio_file.filename:
        return jsonify({"error": "No file selected"}), 400

    name = request.form.get("name", "").strip()
    if not name:
        return jsonify({"error": "Clone name is required (field name: 'name')"}), 400

    # Validate file extension
    allowed_extensions = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".webm"}
    ext = os.path.splitext(audio_file.filename.lower())[1]
    if ext not in allowed_extensions:
        return jsonify({
            "error": f"Unsupported audio format '{ext or 'unknown'}'. "
                     f"Allowed: {', '.join(sorted(allowed_extensions))}"
        }), 400

    # Upload reference audio to storage
    from storage import get_storage

    storage = get_storage()
    clone_id = uuid.uuid4().hex
    audio_key = f"clones/{identity.org.id}/{clone_id}/reference{ext}"

    try:
        audio_bytes = audio_file.read()
        storage.upload_bytes(audio_bytes, audio_key, content_type=audio_file.content_type or "audio/mpeg")
    except Exception as exc:
        return jsonify({"error": f"Failed to store audio: {exc}"}), 500

    # Create the clone record
    clone = VoiceClone(
        id=clone_id,
        organization_id=identity.org.id,
        created_by=identity.user.id,
        name=name,
        reference_audio_s3_key=audio_key,
        status="processing",
        provider="fish_speech",
    )
    session.add(clone)
    session.flush()

    # TODO: Enqueue async job to compute latent embedding via Fish Speech S2.
    # For now the clone stays in "processing" until a worker picks it up.

    return jsonify({
        "clone_id": clone.id,
        "name": clone.name,
        "status": clone.status,
        "message": "Voice clone created. Embedding extraction will begin shortly.",
    }), 201


# --------------------------------------------------------------------------- #
# 7. GET /api/voices/clones — List org's voice clones
# --------------------------------------------------------------------------- #

@voice_catalog_bp.route("/clones", methods=["GET"])
@require_auth
def list_clones():
    """List all voice clones belonging to the current user's organization."""
    session: Session = g.db
    identity = current_identity()

    clones = (
        session.query(VoiceClone)
        .filter(VoiceClone.organization_id == identity.org.id)
        .order_by(VoiceClone.created_at.desc())
        .all()
    )

    return jsonify({
        "clones": [_serialize_clone(c) for c in clones],
        "total": len(clones),
    })


# --------------------------------------------------------------------------- #
# 8. DELETE /api/voices/clones/<clone_id> — Delete a voice clone
# --------------------------------------------------------------------------- #

@voice_catalog_bp.route("/clones/<clone_id>", methods=["DELETE"])
@require_auth
def delete_clone(clone_id: str):
    """Delete a voice clone owned by the caller's organization.

    Also removes the stored reference audio and latent embedding from storage.
    """
    session: Session = g.db
    identity = current_identity()

    clone = session.get(VoiceClone, clone_id)
    if clone is None:
        return jsonify({"error": "Clone not found"}), 404

    if clone.organization_id != identity.org.id:
        return jsonify({"error": "Clone not found"}), 403

    # Clean up storage objects
    from storage import get_storage

    storage = get_storage()
    keys_to_delete = [clone.reference_audio_s3_key]
    if clone.latent_s3_key:
        keys_to_delete.append(clone.latent_s3_key)

    for key in keys_to_delete:
        try:
            storage.delete(key)
        except Exception:
            pass  # Best-effort cleanup

    session.delete(clone)

    return jsonify({
        "clone_id": clone_id,
        "deleted": True,
    })
