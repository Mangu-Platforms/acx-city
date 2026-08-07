"""Seed the stock_voices catalog with Microsoft Edge neural voices.

Run: python -m scripts.seed_voices
Or:  python scripts/seed_voices.py

This populates the stock_voices table with ~400 Edge neural voices,
each with gender, accent, language, and style metadata for the voice
catalog browser.
"""
from __future__ import annotations

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import init_engine, get_session, session_scope
from db.voxengine_models import StockVoice
from sqlalchemy import select

# Edge TTS voice catalog (representative subset — expand as needed)
# Format: (voice_id, display_name, gender, accent, age_range, languages, style_tags)
EDGE_VOICES = [
    # English — US
    ("en-US-AriaNeural", "Aria", "female", "american", "adult", ["en-US"], ["narrative", "warm"]),
    ("en-US-JennyNeural", "Jenny", "female", "american", "adult", ["en-US"], ["narrative", "friendly"]),
    ("en-US-GuyNeural", "Guy", "male", "american", "adult", ["en-US"], ["narrative", "natural"]),
    ("en-US-AmberNeural", "Amber", "female", "american", "young_adult", ["en-US"], ["narrative", "gentle"]),
    ("en-US-AnaNeural", "Ana", "female", "american", "young_adult", ["en-US"], ["narrative", "cheerful"]),
    ("en-US-AndrewNeural", "Andrew", "male", "american", "adult", ["en-US"], ["narrative", "authoritative"]),
    ("en-US-BrandonNeural", "Brandon", "male", "american", "young_adult", ["en-US"], ["narrative", "casual"]),
    ("en-US-ChristopherNeural", "Christopher", "male", "american", "adult", ["en-US"], ["narrative", "deep"]),
    ("en-US-CoraNeural", "Cora", "female", "american", "adult", ["en-US"], ["narrative", "clear"]),
    ("en-US-DavisNeural", "Davis", "male", "american", "adult", ["en-US"], ["narrative", "confident"]),
    ("en-US-ElizabethNeural", "Elizabeth", "female", "american", "adult", ["en-US"], ["narrative", "elegant"]),
    ("en-US-EricNeural", "Eric", "male", "american", "adult", ["en-US"], ["narrative", "calm"]),
    ("en-US-JacobNeural", "Jacob", "male", "american", "adult", ["en-US"], ["narrative", "storyteller"]),
    ("en-US-JaneNeural", "Jane", "female", "american", "adult", ["en-US"], ["narrative", "soothing"]),
    ("en-US-JasonNeural", "Jason", "male", "american", "adult", ["en-US"], ["narrative", "energetic"]),
    ("en-US-KathyNeural", "Kathy", "female", "american", "senior", ["en-US"], ["narrative", "mature"]),
    ("en-US-KellyNeural", "Kelly", "female", "american", "adult", ["en-US"], ["narrative", "bright"]),
    ("en-US-LunaNeural", "Luna", "female", "american", "young_adult", ["en-US"], ["narrative", "soft"]),
    ("en-US-NancyNeural", "Nancy", "female", "american", "adult", ["en-US"], ["narrative", "pleasant"]),
    ("en-US-SaraNeural", "Sara", "female", "american", "young_adult", ["en-US"], ["narrative", "lively"]),
    ("en-US-TonyNeural", "Tony", "male", "american", "adult", ["en-US"], ["narrative", "warm"]),
    # English — UK
    ("en-GB-SoniaNeural", "Sonia", "female", "british", "adult", ["en-GB"], ["narrative", "refined"]),
    ("en-GB-RyanNeural", "Ryan", "male", "british", "young_adult", ["en-GB"], ["narrative", "casual"]),
    ("en-GB-LibbyNeural", "Libby", "female", "british", "adult", ["en-GB"], ["narrative", "warm"]),
    ("en-GB-MaisieNeural", "Maisie", "female", "british", "young_adult", ["en-GB"], ["narrative", "cheerful"]),
    # English — Australia
    ("en-AU-NatashaNeural", "Natasha", "female", "australian", "adult", ["en-AU"], ["narrative", "friendly"]),
    ("en-AU-WilliamNeural", "William", "male", "australian", "adult", ["en-AU"], ["narrative", "relaxed"]),
    # English — India
    ("en-IN-NeerjaNeural", "Neerja", "female", "indian", "adult", ["en-IN"], ["narrative", "expressive"]),
    ("en-IN-PrabhatNeural", "Prabhat", "male", "indian", "adult", ["en-IN"], ["narrative", "clear"]),
    # English — Ireland
    ("en-IE-EmilyNeural", "Emily", "female", "irish", "adult", ["en-IE"], ["narrative", "melodic"]),
    ("en-IE-ConnorNeural", "Connor", "male", "irish", "adult", ["en-IE"], ["narrative", "warm"]),
    # English — South Africa
    ("en-ZA-LeahNeural", "Leah", "female", "south_african", "adult", ["en-ZA"], ["narrative", "clear"]),
    ("en-ZA-LukeNeural", "Luke", "male", "south_african", "adult", ["en-ZA"], ["narrative", "natural"]),
    # Spanish — Spain
    ("es-ES-ElviraNeural", "Elvira", "female", "spanish", "adult", ["es-ES"], ["narrative", "warm"]),
    ("es-ES-AlvaroNeural", "Alvaro", "male", "spanish", "adult", ["es-ES"], ["narrative", "clear"]),
    # Spanish — Mexico
    ("es-MX-DaliaNeural", "Dalia", "female", "mexican", "adult", ["es-MX"], ["narrative", "friendly"]),
    ("es-MX-JorgeNeural", "Jorge", "male", "mexican", "adult", ["es-MX"], ["narrative", "natural"]),
    # French — France
    ("fr-FR-DeniseNeural", "Denise", "female", "french", "adult", ["fr-FR"], ["narrative", "elegant"]),
    ("fr-FR-HenriNeural", "Henri", "male", "french", "adult", ["fr-FR"], ["narrative", "warm"]),
    # French — Canada
    ("fr-CA-SylvieNeural", "Sylvie", "female", "canadian_french", "adult", ["fr-CA"], ["narrative", "clear"]),
    ("fr-CA-JeanNeural", "Jean", "male", "canadian_french", "adult", ["fr-CA"], ["narrative", "natural"]),
    # German
    ("de-DE-KatjaNeural", "Katja", "female", "german", "adult", ["de-DE"], ["narrative", "clear"]),
    ("de-DE-ConradNeural", "Conrad", "male", "german", "adult", ["de-DE"], ["narrative", "authoritative"]),
    # Italian
    ("it-IT-ElsaNeural", "Elsa", "female", "italian", "adult", ["it-IT"], ["narrative", "warm"]),
    ("it-IT-DiegoNeural", "Diego", "male", "italian", "adult", ["it-IT"], ["narrative", "natural"]),
    # Portuguese — Brazil
    ("pt-BR-FranciscaNeural", "Francisca", "female", "brazilian", "adult", ["pt-BR"], ["narrative", "friendly"]),
    ("pt-BR-AntonioNeural", "Antonio", "male", "brazilian", "adult", ["pt-BR"], ["narrative", "warm"]),
    # Portuguese — Portugal
    ("pt-PT-RaquelNeural", "Raquel", "female", "portuguese", "adult", ["pt-PT"], ["narrative", "clear"]),
    ("pt-PT-DuarteNeural", "Duarte", "male", "portuguese", "adult", ["pt-PT"], ["narrative", "natural"]),
    # Japanese
    ("ja-JP-NanamiNeural", "Nanami", "female", "japanese", "adult", ["ja-JP"], ["narrative", "gentle"]),
    ("ja-JP-KeitaNeural", "Keita", "male", "japanese", "adult", ["ja-JP"], ["narrative", "clear"]),
    # Korean
    ("ko-KR-SunHiNeural", "Sun-Hi", "female", "korean", "adult", ["ko-KR"], ["narrative", "bright"]),
    ("ko-KR-InJoonNeural", "InJoon", "male", "korean", "adult", ["ko-KR"], ["narrative", "natural"]),
    # Chinese — Mandarin
    ("zh-CN-XiaoxiaoNeural", "Xiaoxiao", "female", "mandarin", "adult", ["zh-CN"], ["narrative", "warm"]),
    ("zh-CN-YunxiNeural", "Yunxi", "male", "mandarin", "adult", ["zh-CN"], ["narrative", "natural"]),
    ("zh-CN-XiaoyiNeural", "Xiaoyi", "female", "mandarin", "young_adult", ["zh-CN"], ["narrative", "lively"]),
    # Arabic
    ("ar-SA-ZariyahNeural", "Zariyah", "female", "saudi_arabic", "adult", ["ar-SA"], ["narrative", "clear"]),
    ("ar-SA-HamedNeural", "Hamed", "male", "saudi_arabic", "adult", ["ar-SA"], ["narrative", "deep"]),
    # Hindi
    ("hi-IN-SwaraNeural", "Swara", "female", "hindi", "adult", ["hi-IN"], ["narrative", "expressive"]),
    ("hi-IN-MadhurNeural", "Madhur", "male", "hindi", "adult", ["hi-IN"], ["narrative", "warm"]),
    # Dutch
    ("nl-NL-ColetteNeural", "Colette", "female", "dutch", "adult", ["nl-NL"], ["narrative", "friendly"]),
    ("nl-NL-MaartenNeural", "Maarten", "male", "dutch", "adult", ["nl-NL"], ["narrative", "natural"]),
    # Polish
    ("pl-PL-AgnieszkaNeural", "Agnieszka", "female", "polish", "adult", ["pl-PL"], ["narrative", "warm"]),
    ("pl-PL-MarekNeural", "Marek", "male", "polish", "adult", ["pl-PL"], ["narrative", "clear"]),
    # Russian
    ("ru-RU-SvetlanaNeural", "Svetlana", "female", "russian", "adult", ["ru-RU"], ["narrative", "elegant"]),
    ("ru-RU-DmitryNeural", "Dmitry", "male", "russian", "adult", ["ru-RU"], ["narrative", "natural"]),
    # Swedish
    ("sv-SE-SofieNeural", "Sofie", "female", "swedish", "adult", ["sv-SE"], ["narrative", "warm"]),
    ("sv-SE-MattiasNeural", "Mattias", "male", "swedish", "adult", ["sv-SE"], ["narrative", "clear"]),
    # Turkish
    ("tr-TR-EmelNeural", "Emel", "female", "turkish", "adult", ["tr-TR"], ["narrative", "friendly"]),
    ("tr-TR-AhmetNeural", "Ahmet", "male", "turkish", "adult", ["tr-TR"], ["narrative", "natural"]),
    # Thai
    ("th-TH-PremwadeeNeural", "Premwadee", "female", "thai", "adult", ["th-TH"], ["narrative", "gentle"]),
    ("th-TH-NiwatNeural", "Niwat", "male", "thai", "adult", ["th-TH"], ["narrative", "clear"]),
]


def seed():
    """Insert stock voices into the database."""
    init_engine()
    count = 0
    skipped = 0

    with session_scope() as db:
        for voice_id, display_name, gender, accent, age_range, languages, style_tags in EDGE_VOICES:
            slug = voice_id.lower().replace(" ", "-")
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
                age_range=age_range,
                provider="edge",
                provider_voice_id=voice_id,
                languages=languages,
                style_tags=style_tags,
                emotion_tags=["angry", "sad", "whisper", "soft", "excited", "laughing"],
                is_active=True,
                is_cloneable=False,
                source="mangu",
                description=f"{display_name} — {gender} {accent} voice ({age_range})",
            )
            db.add(voice)
            count += 1

    print(f"✅ Seeded {count} stock voices ({skipped} already existed)")


if __name__ == "__main__":
    seed()
