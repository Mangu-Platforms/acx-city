"""Voice Catalog API — browse, preview, compare, and manage voices.

Flask Blueprint exposing the stock voice catalog (``StockVoice`` model) with
filtering, pagination, preview generation, comparison, and voice-clone
management endpoints.

Registered at ``/api/voices``.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import uuid
from typing import Any

from flask import Blueprint, Response, g, jsonify, redirect, request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from auth import current_identity, require_auth
from db.voxengine_models import StockVoice, VoiceClone

log = logging.getLogger("acx.voice_catalog")

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

    total: int = query.order_by(None).with_entities(func.count()).scalar() or 0
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

    if len(preview_text) > 2000:
        return jsonify({"error": "Preview text exceeds 2000 character limit"}), 400

    emotion = data.get("emotion")

    # Lazy-import to avoid circular deps at module level
    from services.providers import ProviderRegistry
    from storage import get_storage

    provider = ProviderRegistry().get(voice.provider)
    if provider is None or not provider.is_available():
        return jsonify({"error": f"TTS provider '{voice.provider}' is not available"}), 503

    provider_voice_id = voice.provider_voice_id or voice.slug
    try:
        try:
            if emotion:
                audio = provider.synthesize_with_options(
                    preview_text, provider_voice_id, style=emotion
                )
            else:
                audio = provider.synthesize_with_options(preview_text, provider_voice_id)
        except TypeError:
            audio = provider.synthesize(preview_text, provider_voice_id)
    except Exception as exc:
        return jsonify({"error": f"Preview generation failed: {exc}"}), 500

    key = (
        f"previews/{identity.org.id}/{voice.id}/"
        f"{hashlib.sha256((preview_text + str(emotion)).encode()).hexdigest()[:16]}.mp3"
    )
    storage = get_storage()
    storage.put_bytes(key, audio, content_type="audio/mpeg")
    signed = storage.signed_url(key, expires_in=600)

    return jsonify({
        "preview_url": signed.url,
        "expires_in": signed.expires_in,
        "voice_id": voice.id,
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
    if len(text) > 500:
        return jsonify({"error": "Comparison text exceeds 500 character limit"}), 400

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
    from storage import get_storage

    registry = ProviderRegistry()
    storage = get_storage()

    # Group voices by provider for efficiency
    providers_map: dict[str, Any] = {}
    for v in voices:
        if v.provider not in providers_map:
            p = registry.get(v.provider)
            if p is None or not p.is_available():
                return jsonify({"error": f"TTS provider '{v.provider}' is not available"}), 503
            providers_map[v.provider] = p

    clips: list[dict[str, Any]] = []
    labels = [chr(ord("A") + i) for i in range(len(voice_ids))]

    for idx, voice in enumerate(voices):
        provider = providers_map[voice.provider]
        provider_voice_id = voice.provider_voice_id or voice.slug
        try:
            audio = provider.synthesize(text, provider_voice_id)
        except Exception as exc:
            return jsonify({"error": f"Preview failed for voice '{voice_ids[idx]}': {exc}"}), 500

        key = (
            f"previews/{identity.org.id}/{voice.id}/"
            f"{hashlib.sha256(text.encode()).hexdigest()[:16]}.mp3"
        )
        storage.put_bytes(key, audio, content_type="audio/mpeg")
        signed = storage.signed_url(key, expires_in=600)

        clip: dict[str, Any] = {
            "index": idx,
            "audio_url": signed.url,
            "expires_in": signed.expires_in,
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
# 5b. GET /api/voices/<voice_id>/sample — Short audio sample
# --------------------------------------------------------------------------- #

@voice_catalog_bp.route("/<voice_id>/sample", methods=["GET"])
@require_auth
def get_voice_sample(voice_id: str):
    """Return a short audio sample for a voice.

    If the voice has a pre-recorded ``sample_audio_url``, redirects there (302).
    Otherwise synthesises a short intro line on the fly using the voice's
    provider and returns audio/mpeg bytes directly.
    """
    session: Session = g.db
    identity = current_identity()

    voice = session.get(StockVoice, voice_id)
    if voice is None:
        return jsonify({"error": "Voice not found"}), 404

    if voice.organization_id is not None and voice.organization_id != identity.org.id:
        return jsonify({"error": "Voice not found"}), 404

    if voice.sample_audio_url:
        return redirect(voice.sample_audio_url, code=302)

    # On-demand synthesis fallback.
    from services.providers import ProviderRegistry

    provider = ProviderRegistry().get(voice.provider)
    if provider is None or not provider.is_available():
        return jsonify({"error": f"Provider '{voice.provider}' not available"}), 503

    sample_text = f"Hello, I'm {voice.display_name}. I'd love to narrate your audiobook."
    try:
        audio = provider.synthesize(sample_text, voice.provider_voice_id or voice.slug)
    except Exception as exc:
        log.warning("voice sample synthesis failed for %s: %s", voice_id, exc)
        return jsonify({"error": "Sample synthesis failed"}), 500

    cache_directive = "private" if voice.organization_id else "public"
    return Response(
        audio,
        content_type="audio/mpeg",
        headers={"Cache-Control": f"{cache_directive}, max-age=86400"},
    )


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
        storage.put_bytes(audio_key, audio_bytes, content_type=audio_file.content_type or "audio/mpeg")
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
    session.commit()

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
    if clone is None or clone.organization_id != identity.org.id:
        return jsonify({"error": "Clone not found"}), 404

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
    session.commit()

    return jsonify({
        "clone_id": clone_id,
        "deleted": True,
    })
