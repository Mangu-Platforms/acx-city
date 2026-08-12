"""Project pronunciation lexicon → synthesis text (P1.3).

The default (non-pipeline) worker path speaks exactly the text it is given,
so lexicon entries are applied as plain phonetic REPLACEMENT — "Nguyen" →
"NWIN" — using phonetic_spelling only. IPA-only entries are skipped here: a
plain-text TTS provider would read raw IPA aloud.

The flag-gated multi-agent pipeline keeps its own tag-based application
([pron:…]word[/pron]) in the TextNormalizer, because its output feeds a
synthesis layer that understands tags. Two consumers, two semantics — this
module is the one that changes shipped audio today.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.voxengine_models import PronunciationLexicon


def load_lexicon_entries(session: Session, project_id: str) -> List[Dict[str, Any]]:
    rows = session.execute(
        select(PronunciationLexicon)
        .where(PronunciationLexicon.project_id == project_id)
        .order_by(PronunciationLexicon.word)
    ).scalars().all()
    return [
        {"word": r.word, "ipa_phoneme": r.ipa_phoneme,
         "phonetic_spelling": r.phonetic_spelling}
        for r in rows
    ]


def apply_lexicon_plain(text: str, entries: List[Dict[str, Any]]) -> str:
    """Replace lexicon words with their speakable phonetic spelling.

    Whole-word, case-insensitive. Deterministic order (callers pass entries
    sorted by word) so identical inputs produce identical synthesis text —
    and therefore identical cache keys and audio.
    """
    for entry in entries:
        word = entry.get("word") or ""
        phonetic = entry.get("phonetic_spelling") or ""
        if word and phonetic:
            pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
            text = pattern.sub(phonetic, text)
    return text
