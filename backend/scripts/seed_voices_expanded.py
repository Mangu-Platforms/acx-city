"""
Seed the stock_voices catalog with AWS Polly Neural + Standard voices,
plus re-seed Edge voices.

Run: python -m scripts.seed_voices_expanded
Or:  python scripts/seed_voices_expanded.py

Adds ~100 Polly voices (Neural & Standard) to the stock_voices table
and calls the Edge voice seeder for completeness.  Fully idempotent —
existing slugs are skipped.
"""
from __future__ import annotations

import os
import sys

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import init_engine, session_scope
from db.voxengine_models import StockVoice
from sqlalchemy import select

# ---------------------------------------------------------------------------
# AWS Polly Neural + Standard voice catalog
# ---------------------------------------------------------------------------
# Format: (provider_voice_id, display_name, gender, accent, languages,
#          engine, style_tags)
# engine: "neural" or "standard"

POLLY_VOICES: list[tuple[str, str, str, str, list[str], str, list[str]]] = [
    # ── English — US (Neural) ──────────────────────────────────────────────
    ("Joanna", "Joanna", "female", "american", ["en-US"], "neural", ["narrative", "warm", "conversational"]),
    ("Matthew", "Matthew", "male", "american", ["en-US"], "neural", ["narrative", "natural"]),
    ("Ruth", "Ruth", "female", "american", ["en-US"], "neural", ["narrative", "storyteller", "expressive"]),
    ("Stephen", "Stephen", "male", "american", ["en-US"], "neural", ["narrative", "deep", "authoritative"]),
    ("Ivy", "Ivy", "female", "american", ["en-US"], "neural", ["narrative", "child", "bright"]),
    ("Kendra", "Kendra", "female", "american", ["en-US"], "neural", ["narrative", "clear"]),
    ("Kimberly", "Kimberly", "female", "american", ["en-US"], "neural", ["narrative", "gentle"]),
    ("Salli", "Salli", "female", "american", ["en-US"], "neural", ["narrative", "cheerful"]),
    ("Joey", "Joey", "male", "american", ["en-US"], "neural", ["narrative", "casual"]),
    ("Justin", "Justin", "male", "american", ["en-US"], "neural", ["narrative", "young", "lively"]),
    ("Kevin", "Kevin", "male", "american", ["en-US"], "neural", ["narrative", "child"]),
    # ── English — US (Standard) ────────────────────────────────────────────
    ("Ivy-std", "Ivy (Standard)", "female", "american", ["en-US"], "standard", ["narrative"]),
    ("Joanna-std", "Joanna (Standard)", "female", "american", ["en-US"], "standard", ["narrative"]),
    ("Joey-std", "Joey (Standard)", "male", "american", ["en-US"], "standard", ["narrative"]),
    ("Justin-std", "Justin (Standard)", "male", "american", ["en-US"], "standard", ["narrative"]),
    ("Kendra-std", "Kendra (Standard)", "female", "american", ["en-US"], "standard", ["narrative"]),
    ("Kimberly-std", "Kimberly (Standard)", "female", "american", ["en-US"], "standard", ["narrative"]),
    ("Matthew-std", "Matthew (Standard)", "male", "american", ["en-US"], "standard", ["narrative"]),
    ("Salli-std", "Salli (Standard)", "female", "american", ["en-US"], "standard", ["narrative"]),

    # ── English — UK (Neural) ──────────────────────────────────────────────
    ("Amy", "Amy", "female", "british", ["en-GB"], "neural", ["narrative", "refined"]),
    ("Emma", "Emma", "female", "british", ["en-GB"], "neural", ["narrative", "bright"]),
    ("Brian", "Brian", "male", "british", ["en-GB"], "neural", ["narrative", "warm", "natural"]),
    ("Arthur", "Arthur", "male", "british", ["en-GB"], "neural", ["narrative", "authoritative"]),
    # ── English — UK (Standard) ────────────────────────────────────────────
    ("Amy-std", "Amy (Standard)", "female", "british", ["en-GB"], "standard", ["narrative"]),
    ("Brian-std", "Brian (Standard)", "male", "british", ["en-GB"], "standard", ["narrative"]),
    ("Emma-std", "Emma (Standard)", "female", "british", ["en-GB"], "standard", ["narrative"]),

    # ── English — Australia (Neural) ───────────────────────────────────────
    ("Olivia", "Olivia", "female", "australian", ["en-AU"], "neural", ["narrative", "warm"]),
    ("Russell", "Russell", "male", "australian", ["en-AU"], "neural", ["narrative", "casual"]),
    # ── English — Australia (Standard) ─────────────────────────────────────
    ("Nicole-std", "Nicole (Standard)", "female", "australian", ["en-AU"], "standard", ["narrative"]),
    ("Russell-std", "Russell (Standard)", "male", "australian", ["en-AU"], "standard", ["narrative"]),

    # ── English — India (Neural) ───────────────────────────────────────────
    ("Kajal", "Kajal", "female", "indian", ["en-IN"], "neural", ["narrative", "expressive"]),
    # ── English — India (Standard) ─────────────────────────────────────────
    ("Aditi-std", "Aditi (Standard)", "female", "indian", ["en-IN"], "standard", ["narrative"]),
    ("Raveena-std", "Raveena (Standard)", "female", "indian", ["en-IN"], "standard", ["narrative"]),

    # ── English — South Africa (Standard) ──────────────────────────────────
    ("Ayanda", "Ayanda", "female", "south_african", ["en-ZA"], "neural", ["narrative", "warm"]),

    # ── English — New Zealand (Standard) ───────────────────────────────────
    ("Aria", "Aria", "female", "new_zealand", ["en-NZ"], "neural", ["narrative", "natural"]),

    # ── English — Welsh (Neural) ───────────────────────────────────────────
    ("Nia", "Nia", "female", "welsh", ["en-GB-WLS"], "neural", ["narrative", "melodic"]),

    # ── French — France (Neural) ───────────────────────────────────────────
    ("Lea", "Léa", "female", "french", ["fr-FR"], "neural", ["narrative", "elegant"]),
    ("Remi", "Rémi", "male", "french", ["fr-FR"], "neural", ["narrative", "warm"]),
    # ── French — France (Standard) ─────────────────────────────────────────
    ("Celine-std", "Céline (Standard)", "female", "french", ["fr-FR"], "standard", ["narrative"]),
    ("Mathieu-std", "Mathieu (Standard)", "male", "french", ["fr-FR"], "standard", ["narrative"]),

    # ── French — Canada (Neural) ───────────────────────────────────────────
    ("Gabrielle", "Gabrielle", "female", "canadian_french", ["fr-CA"], "neural", ["narrative", "warm"]),
    ("Liam", "Liam", "male", "canadian_french", ["fr-CA"], "neural", ["narrative", "natural"]),
    # ── French — Canada (Standard) ─────────────────────────────────────────
    ("Chantal-std", "Chantal (Standard)", "female", "canadian_french", ["fr-CA"], "standard", ["narrative"]),

    # ── German (Neural) ────────────────────────────────────────────────────
    ("Vicki", "Vicki", "female", "german", ["de-DE"], "neural", ["narrative", "clear"]),
    ("Daniel", "Daniel", "male", "german", ["de-DE"], "neural", ["narrative", "authoritative"]),
    # ── German (Standard) ──────────────────────────────────────────────────
    ("Hans-std", "Hans (Standard)", "male", "german", ["de-DE"], "standard", ["narrative"]),
    ("Marlene-std", "Marlene (Standard)", "female", "german", ["de-DE"], "standard", ["narrative"]),
    ("Vicki-std", "Vicki (Standard)", "female", "german", ["de-DE"], "standard", ["narrative"]),

    # ── Italian (Neural) ───────────────────────────────────────────────────
    ("Bianca", "Bianca", "female", "italian", ["it-IT"], "neural", ["narrative", "warm"]),
    ("Adriano", "Adriano", "male", "italian", ["it-IT"], "neural", ["narrative", "natural"]),
    # ── Italian (Standard) ─────────────────────────────────────────────────
    ("Carla-std", "Carla (Standard)", "female", "italian", ["it-IT"], "standard", ["narrative"]),
    ("Giorgio-std", "Giorgio (Standard)", "male", "italian", ["it-IT"], "standard", ["narrative"]),

    # ── Spanish — Spain (Neural) ───────────────────────────────────────────
    ("Lucia", "Lucia", "female", "spanish", ["es-ES"], "neural", ["narrative", "elegant"]),
    ("Sergio", "Sergio", "male", "spanish", ["es-ES"], "neural", ["narrative", "warm"]),
    # ── Spanish — Spain (Standard) ─────────────────────────────────────────
    ("Conchita-std", "Conchita (Standard)", "female", "spanish", ["es-ES"], "standard", ["narrative"]),
    ("Enrique-std", "Enrique (Standard)", "male", "spanish", ["es-ES"], "standard", ["narrative"]),

    # ── Spanish — US (Neural) ──────────────────────────────────────────────
    ("Lupe", "Lupe", "female", "american_spanish", ["es-US"], "neural", ["narrative", "expressive"]),
    ("Pedro", "Pedro", "male", "american_spanish", ["es-US"], "neural", ["narrative", "natural"]),

    # ── Spanish — Mexico (Standard) ────────────────────────────────────────
    ("Mia-std", "Mia (Standard)", "female", "mexican", ["es-MX"], "standard", ["narrative"]),

    # ── Portuguese — Brazil (Neural) ───────────────────────────────────────
    ("Camila", "Camila", "female", "brazilian", ["pt-BR"], "neural", ["narrative", "warm"]),
    ("Thiago", "Thiago", "male", "brazilian", ["pt-BR"], "neural", ["narrative", "natural"]),
    # ── Portuguese — Brazil (Standard) ─────────────────────────────────────
    ("Ricardo-std", "Ricardo (Standard)", "male", "brazilian", ["pt-BR"], "standard", ["narrative"]),
    ("Vitoria-std", "Vitória (Standard)", "female", "brazilian", ["pt-BR"], "standard", ["narrative"]),

    # ── Portuguese — Portugal (Standard) ───────────────────────────────────
    ("Ines-std", "Inês (Standard)", "female", "portuguese", ["pt-PT"], "standard", ["narrative"]),
    ("Cristiano-std", "Cristiano (Standard)", "male", "portuguese", ["pt-PT"], "standard", ["narrative"]),

    # ── Japanese (Neural) ──────────────────────────────────────────────────
    ("Takumi", "Takumi", "male", "japanese", ["ja-JP"], "neural", ["narrative", "natural"]),
    ("Kazuha", "Kazuha", "female", "japanese", ["ja-JP"], "neural", ["narrative", "gentle"]),
    # ── Japanese (Standard) ────────────────────────────────────────────────
    ("Mizuki-std", "Mizuki (Standard)", "female", "japanese", ["ja-JP"], "standard", ["narrative"]),
    ("Takumi-std", "Takumi (Standard)", "male", "japanese", ["ja-JP"], "standard", ["narrative"]),

    # ── Korean (Neural) ────────────────────────────────────────────────────
    ("Seoyeon", "Seoyeon", "female", "korean", ["ko-KR"], "neural", ["narrative", "bright"]),
    # ── Korean (Standard) ──────────────────────────────────────────────────
    ("Seoyeon-std", "Seoyeon (Standard)", "female", "korean", ["ko-KR"], "standard", ["narrative"]),

    # ── Chinese — Mandarin (Neural) ────────────────────────────────────────
    ("Zhiyu", "Zhiyu", "female", "mandarin", ["cmn-CN"], "neural", ["narrative", "warm"]),
    # ── Chinese — Mandarin (Standard) ──────────────────────────────────────
    ("Zhiyu-std", "Zhiyu (Standard)", "female", "mandarin", ["cmn-CN"], "standard", ["narrative"]),

    # ── Hindi (Neural) ─────────────────────────────────────────────────────
    ("Kajal", "Kajal", "female", "hindi", ["hi-IN"], "neural", ["narrative", "expressive"]),
    # ── Hindi (Standard) ───────────────────────────────────────────────────
    ("Aditi-std", "Aditi (Standard)", "female", "hindi", ["hi-IN"], "standard", ["narrative"]),

    # ── Arabic (Standard) ──────────────────────────────────────────────────
    ("Zeina-std", "Zeina (Standard)", "female", "arabic", ["arb"], "standard", ["narrative"]),

    # ── Dutch (Standard) ───────────────────────────────────────────────────
    ("Lotte-std", "Lotte (Standard)", "female", "dutch", ["nl-NL"], "standard", ["narrative"]),
    ("Ruben-std", "Ruben (Standard)", "male", "dutch", ["nl-NL"], "standard", ["narrative"]),

    # ── Polish (Standard) ──────────────────────────────────────────────────
    ("Ewa-std", "Ewa (Standard)", "female", "polish", ["pl-PL"], "standard", ["narrative"]),
    ("Jacek-std", "Jacek (Standard)", "male", "polish", ["pl-PL"], "standard", ["narrative"]),
    ("Jan-std", "Jan (Standard)", "male", "polish", ["pl-PL"], "standard", ["narrative"]),
    ("Maja-std", "Maja (Standard)", "female", "polish", ["pl-PL"], "standard", ["narrative"]),

    # ── Romanian (Standard) ────────────────────────────────────────────────
    ("Carmen-std", "Carmen (Standard)", "female", "romanian", ["ro-RO"], "standard", ["narrative"]),

    # ── Russian (Standard) ─────────────────────────────────────────────────
    ("Maxim-std", "Maxim (Standard)", "male", "russian", ["ru-RU"], "standard", ["narrative"]),
    ("Tatyana-std", "Tatyana (Standard)", "female", "russian", ["ru-RU"], "standard", ["narrative"]),

    # ── Swedish (Standard) ─────────────────────────────────────────────────
    ("Astrid-std", "Astrid (Standard)", "female", "swedish", ["sv-SE"], "standard", ["narrative"]),
    ("Karl-std", "Karl (Standard)", "male", "swedish", ["sv-SE"], "standard", ["narrative"]),

    # ── Turkish (Standard) ─────────────────────────────────────────────────
    ("Filiz-std", "Filiz (Standard)", "female", "turkish", ["tr-TR"], "standard", ["narrative"]),

    # ── Welsh (Standard) ───────────────────────────────────────────────────
    ("Gwyneth-std", "Gwyneth (Standard)", "female", "welsh", ["cy-GB"], "standard", ["narrative"]),

    # ── Danish (Standard) ──────────────────────────────────────────────────
    ("Naja-std", "Naja (Standard)", "female", "danish", ["da-DK"], "standard", ["narrative"]),
    ("Mads-std", "Mads (Standard)", "male", "danish", ["da-DK"], "standard", ["narrative"]),

    # ── Finnish (Standard) ─────────────────────────────────────────────────
    ("Suvi-std", "Suvi (Standard)", "female", "finnish", ["fi-FI"], "standard", ["narrative"]),

    # ── Icelandic (Standard) ───────────────────────────────────────────────
    ("Dora-std", "Dóra (Standard)", "female", "icelandic", ["is-IS"], "standard", ["narrative"]),
    ("Karl-std", "Karl (Standard)", "male", "icelandic", ["is-IS"], "standard", ["narrative"]),

    # ── Norwegian (Standard) ───────────────────────────────────────────────
    ("Liv-std", "Liv (Standard)", "female", "norwegian", ["nb-NO"], "standard", ["narrative"]),

    # ── Tagalog (Standard) ─────────────────────────────────────────────────
    # no native Tagalog voice in Polly; keeping placeholder comment

    # ── Ukrainian (Standard) ───────────────────────────────────────────────
    # Polly does not yet have Ukrainian; placeholder for future expansion

    # ── Indonesian (Standard) ──────────────────────────────────────────────
    # no native Indonesian voice in Polly; placeholder for future expansion
]


def _make_slug(provider_voice_id: str, engine: str) -> str:
    """Build a unique slug for a Polly voice.

    Slugs follow the pattern ``polly-{id}-{engine}`` to avoid collisions
    with Edge voices (which use the raw voice_id as slug).
    """
    safe_id = provider_voice_id.lower().replace(" ", "-")
    return f"polly-{safe_id}-{engine}"


def seed_polly_voices() -> tuple[int, int]:
    """
    Insert all AWS Polly voices into the ``stock_voices`` table.

    Returns:
        ``(inserted, skipped)`` counts.
    """
    init_engine()
    inserted = 0
    skipped = 0

    with session_scope() as db:
        for (
            provider_voice_id,
            display_name,
            gender,
            accent,
            languages,
            engine,
            style_tags,
        ) in POLLY_VOICES:
            slug = _make_slug(provider_voice_id, engine)
            existing = db.execute(
                select(StockVoice).where(StockVoice.slug == slug)
            ).scalar_one_or_none()

            if existing:
                skipped += 1
                continue

            voice = StockVoice(
                slug=slug,
                display_name=display_name,
                gender=gender,
                accent=accent,
                age_range="adult",
                provider="polly",
                provider_voice_id=provider_voice_id,
                languages=languages,
                style_tags=[*style_tags, engine],  # tag with "neural" or "standard"
                emotion_tags=["angry", "sad", "whisper", "soft", "excited", "laughing"]
                if engine == "neural"
                else [],
                is_active=True,
                is_cloneable=False,
                source="mangu",
                description=(
                    f"{display_name} — AWS Polly {engine.title()} voice, "
                    f"{gender} {accent}"
                ),
            )
            db.add(voice)
            inserted += 1

    print(f"✅ Polly: seeded {inserted} voices ({skipped} already existed)")
    return inserted, skipped


def seed_all() -> None:
    """
    Seed the full expanded voice catalog.

    1. Seed Edge voices (from ``seed_voices``).
    2. Seed AWS Polly voices (from this module).
    """
    # Edge voices
    from scripts.seed_voices import seed as seed_edge  # type: ignore[import-untyped]

    print("── Seeding Edge voices ──")
    seed_edge()

    print("\n── Seeding AWS Polly voices ──")
    seed_polly_voices()

    print("\n🎉 All voice providers seeded.")


if __name__ == "__main__":
    seed_all()
