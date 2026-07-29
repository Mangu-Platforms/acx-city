"""Pronunciation dictionary validation, snapshotting, and deterministic application.

Voice City stores pronunciation rules as durable rows
(``db.voice_models.VoiceCityPronunciationRule``), but a production worker never
reads mutable rows while rendering: ``serialize_rules`` produces the JSON-safe
shape captured inside a ``VoiceCityJobSnapshot`` and
``apply_pronunciation_rules`` consumes exactly that serialized shape.  Every
function here is deterministic -- identical text, rules, and strength always
produce identical rewritten text and identical evidence -- because rendered
audio must be reproducible from a snapshot alone.

Safety posture: user-supplied regular expressions are compiled with the
standard ``re`` module only, are length-capped, may not match empty text, and
may not use nested quantifiers (the classic catastrophic-backtracking shape).
A rule that fails to compile at apply time is skipped with evidence rather
than failing a production job.

This module imports only the standard library plus the sibling parameter
schema.  Rule rows are read with ``getattr`` so SQLAlchemy is never imported.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable, Mapping

from .parameter_schema import get_path

__all__ = [
    "PronunciationRuleError",
    "validate_rule",
    "serialize_rules",
    "apply_pronunciation_rules",
    "apply_text_interpretation",
]

RULE_TYPES = ("literal", "pattern")
#: Caps mirror the database columns (pattern String(500), replacement String(1000)).
MAX_PATTERN_LENGTH = 500
MAX_REPLACEMENT_LENGTH = 1000
MAX_LANGUAGE_LENGTH = 30
_PRIORITY_BOUND = 1_000_000

_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
# A quantifier applied directly to a quantified group ("(a+)+", "(x*){2}", ...)
# is the canonical catastrophic-backtracking construction.  The scan is
# intentionally conservative: rare legitimate patterns such as "a}+" are also
# rejected, with a clear message, rather than risking a stuck render worker.
_NESTED_QUANTIFIER_RE = re.compile(r"[+*}]\)?[+*{]")


class PronunciationRuleError(ValueError):
    """Raised with a human-readable message when a rule payload is invalid."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _coerce_bool(payload: Mapping[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise PronunciationRuleError(f"{key} must be true or false")


def _coerce_priority(payload: Mapping[str, Any]) -> int:
    value = payload.get("priority", 100)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PronunciationRuleError("priority must be an integer")
    if isinstance(value, float):
        if not value.is_integer():
            raise PronunciationRuleError("priority must be a whole number")
        value = int(value)
    if not -_PRIORITY_BOUND <= value <= _PRIORITY_BOUND:
        raise PronunciationRuleError(
            f"priority must be between {-_PRIORITY_BOUND} and {_PRIORITY_BOUND}"
        )
    return int(value)


def _compile_rule_pattern(pattern: str, case_sensitive: bool) -> re.Pattern[str]:
    """Compile a ``pattern``-type rule, raising a human message on unsafe input."""
    if _NESTED_QUANTIFIER_RE.search(pattern):
        raise PronunciationRuleError(
            "pattern uses a quantifier applied to another quantifier "
            "(for example \"(a+)+\"), which is not allowed"
        )
    flags = re.UNICODE | (0 if case_sensitive else re.IGNORECASE)
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        raise PronunciationRuleError(f"pattern is not a valid regular expression: {exc}") from exc
    if compiled.search("") is not None:
        raise PronunciationRuleError("pattern must not match empty text")
    return compiled


def validate_rule(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one pronunciation-rule payload.

    Returns the canonical rule dict with exactly the keys the service layer
    writes to the database: ``pattern``, ``replacement``, ``language``,
    ``rule_type``, ``priority``, ``case_sensitive``, ``enabled``.  Extra keys
    (``id``, ``voice_id``, ``notes``...) are ignored so callers may pass full
    API payloads or merged row dicts.  Raises :class:`PronunciationRuleError`
    with a human-readable message on bad input.
    """
    if not isinstance(payload, Mapping):
        raise PronunciationRuleError("A pronunciation rule must be an object")

    rule_type = str(payload.get("rule_type") or "literal").strip().lower()
    if rule_type not in RULE_TYPES:
        raise PronunciationRuleError("rule_type must be 'literal' or 'pattern'")

    raw_pattern = payload.get("pattern")
    if not isinstance(raw_pattern, str):
        raise PronunciationRuleError("pattern is required and must be text")
    pattern = raw_pattern.strip()
    if not pattern:
        raise PronunciationRuleError("pattern must not be empty")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise PronunciationRuleError(f"pattern must be at most {MAX_PATTERN_LENGTH} characters")

    replacement = payload.get("replacement")
    if not isinstance(replacement, str):
        raise PronunciationRuleError("replacement is required and must be text")
    if len(replacement) > MAX_REPLACEMENT_LENGTH:
        raise PronunciationRuleError(
            f"replacement must be at most {MAX_REPLACEMENT_LENGTH} characters"
        )

    language = str(payload.get("language") or "en-US").strip() or "en-US"
    if len(language) > MAX_LANGUAGE_LENGTH or not _LANGUAGE_RE.match(language):
        raise PronunciationRuleError("language must be a locale tag such as 'en-US'")

    case_sensitive = _coerce_bool(payload, "case_sensitive", False)
    enabled = _coerce_bool(payload, "enabled", True)
    priority = _coerce_priority(payload)

    if rule_type == "pattern":
        compiled = _compile_rule_pattern(pattern, case_sensitive)
        try:
            # Parses the replacement template (group references, escapes)
            # without needing a match; the pattern cannot match empty text.
            compiled.sub(replacement, "")
        except re.error as exc:
            raise PronunciationRuleError(
                f"replacement is not a valid substitution for this pattern: {exc}"
            ) from exc

    return {
        "pattern": pattern,
        "replacement": replacement,
        "language": language,
        "rule_type": rule_type,
        "priority": priority,
        "case_sensitive": case_sensitive,
        "enabled": enabled,
    }


# ---------------------------------------------------------------------------
# Snapshot serialization
# ---------------------------------------------------------------------------

def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _int_or_default(value: Any, default: int) -> int:
    try:
        if isinstance(value, bool) or value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def serialize_rules(rows: Iterable[Any]) -> list[dict[str, Any]]:
    """Serialize ``VoiceCityPronunciationRule`` rows to the snapshot JSON shape.

    Only ``getattr`` is used, so any row-shaped object works and SQLAlchemy is
    not imported here.  The result is exactly what production snapshots store
    and what :func:`apply_pronunciation_rules` consumes; every value is
    JSON-serializable (datetimes become ISO-8601 strings).  Input ordering is
    preserved -- callers order rows deterministically.
    """
    serialized: list[dict[str, Any]] = []
    for row in rows:
        serialized.append(
            {
                "id": _text_or_none(getattr(row, "id", None)),
                "voice_id": _text_or_none(getattr(row, "voice_id", None)),
                "pattern": str(getattr(row, "pattern", "") or ""),
                "replacement": str(getattr(row, "replacement", "") or ""),
                "language": str(getattr(row, "language", "en-US") or "en-US"),
                "rule_type": str(getattr(row, "rule_type", "literal") or "literal"),
                "priority": _int_or_default(getattr(row, "priority", 100), 100),
                "case_sensitive": bool(getattr(row, "case_sensitive", False)),
                "enabled": bool(getattr(row, "enabled", True)),
                "notes": _text_or_none(getattr(row, "notes", None)),
                "created_at": _iso_or_none(getattr(row, "created_at", None)),
                "updated_at": _iso_or_none(getattr(row, "updated_at", None)),
            }
        )
    return serialized


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def _evidence(rule: Mapping[str, Any], replacements: int, error: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": rule.get("id"),
        "rule_type": str(rule.get("rule_type") or "literal"),
        "pattern": str(rule.get("pattern") or ""),
        "replacements": int(replacements),
    }
    if error:
        item["error"] = error
    return item


def _selected_rules(rules: Iterable[Mapping[str, Any]], strength: float) -> list[Mapping[str, Any]]:
    """Order enabled rules by priority (descending) and scale by strength.

    Strength rule (documented contract): strength is clamped to [0, 1];
    ``0`` applies no rules, ``1`` applies every enabled rule, and any value in
    between applies the first ``ceil(strength * n)`` rules of the
    priority-descending order, so the highest-priority rules survive the
    lowest strengths.  Ties keep the caller's input order (snapshots are
    already deterministically ordered), which keeps selection reproducible.
    """
    enabled = [
        rule for rule in rules
        if isinstance(rule, Mapping) and bool(rule.get("enabled", True))
    ]
    if not enabled:
        return []
    ordered = [
        rule for _, rule in sorted(
            enumerate(enabled),
            key=lambda pair: (-_int_or_default(pair[1].get("priority"), 100), pair[0]),
        )
    ]
    if not math.isfinite(strength):
        strength = 1.0
    strength = min(1.0, max(0.0, float(strength)))
    if strength <= 0.0:
        return []
    if strength >= 1.0:
        return ordered
    return ordered[: math.ceil(strength * len(ordered))]


def apply_pronunciation_rules(
    text: str, rules: list[dict[str, Any]], *, strength: float
) -> tuple[str, list[dict[str, Any]]]:
    """Apply serialized pronunciation rules to ``text`` deterministically.

    ``rules`` is the exact shape produced by :func:`serialize_rules` (the
    production snapshot format).  Rules run one at a time in priority order,
    so later rules observe earlier rewrites.  Literal rules match whole tokens
    (``(?<!\\w)...(?!\\w)`` semantics) and treat the replacement literally;
    pattern rules are regular expressions whose replacement may use group
    references.  Case-insensitive matching is the default unless a rule sets
    ``case_sensitive``.

    A pattern that is too long, matches empty text, uses nested quantifiers,
    or fails to compile or substitute is skipped and reported in the evidence
    list with ``replacements: 0`` and an ``error`` -- production renders must
    never crash on a stale snapshot rule.

    Returns ``(rewritten_text, evidence)`` where each evidence item carries the
    rule ``id`` and its ``replacements`` count; rules that matched nothing are
    omitted so per-segment evidence stays compact.
    """
    result = text if isinstance(text, str) else str(text or "")
    applied: list[dict[str, Any]] = []
    if not result or not rules:
        return result, applied

    for rule in _selected_rules(rules, strength):
        pattern_text = str(rule.get("pattern") or "")
        replacement = str(rule.get("replacement") or "")
        rule_type = str(rule.get("rule_type") or "literal").strip().lower()
        if not pattern_text:
            applied.append(_evidence(rule, 0, "empty pattern skipped"))
            continue
        if len(pattern_text) > MAX_PATTERN_LENGTH:
            applied.append(_evidence(rule, 0, "pattern exceeds the maximum length"))
            continue
        flags = re.UNICODE | (0 if bool(rule.get("case_sensitive")) else re.IGNORECASE)

        if rule_type == "pattern":
            if _NESTED_QUANTIFIER_RE.search(pattern_text):
                applied.append(_evidence(rule, 0, "nested quantifiers are not allowed"))
                continue
            try:
                compiled = re.compile(pattern_text, flags)
            except re.error as exc:
                applied.append(_evidence(rule, 0, f"invalid regular expression: {exc}"))
                continue
            if compiled.search("") is not None:
                applied.append(_evidence(rule, 0, "pattern matches empty text"))
                continue
            try:
                rewritten, count = compiled.subn(replacement, result)
            except (re.error, IndexError) as exc:
                applied.append(_evidence(rule, 0, f"invalid substitution: {exc}"))
                continue
        else:
            compiled = re.compile(
                rf"(?<!\w){re.escape(pattern_text)}(?!\w)", flags
            )
            rewritten, count = compiled.subn(lambda _match: replacement, result)

        if count:
            result = rewritten
            applied.append(_evidence(rule, count))
    return result, applied


# ---------------------------------------------------------------------------
# Text interpretation
# ---------------------------------------------------------------------------
# Numbers: standalone digit runs only.  The guards skip digits joined to more
# digits through punctuation (decimals "3.14", thousands "1,234", times
# "12:30", dates "2024-05-01"), percentages, currency amounts, and
# identifiers, while ordinary sentence punctuation after a number is fine.
_NUMBER_TOKEN_RE = re.compile(
    r"(?<!\w)(?<!\d[.,:/\-])(?<![$\u20ac\u00a3#%])(\d+)(?!\w)(?![.,:/\-]\d)(?!%)"
)
_ACRONYM_TOKEN_RE = re.compile(r"(?<![\w.])([A-Z]{2,8})(?!\w)")
_ROMAN_NUMERAL_RE = re.compile(r"^[IVXLCDM]+$")
_ASIDE_DASH_RE = re.compile(r"\s+[–—]\s+")
_ELLIPSIS_RE = re.compile(r"…")

_ONES = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
)
_TENS = (
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
)
_SCALES = ((10 ** 9, "billion"), (10 ** 6, "million"), (10 ** 3, "thousand"))


def _small_number_words(value: int) -> str:
    parts: list[str] = []
    hundreds, remainder = divmod(value, 100)
    if hundreds:
        parts.append(f"{_ONES[hundreds]} hundred")
    if remainder:
        if remainder < 20:
            parts.append(_ONES[remainder])
        else:
            tens, ones = divmod(remainder, 10)
            parts.append(_TENS[tens] + (f"-{_ONES[ones]}" if ones else ""))
    return " ".join(parts) if parts else _ONES[0]


def _number_to_words(value: int) -> str:
    if value < 1000:
        return _small_number_words(value)
    parts: list[str] = []
    remaining = value
    for scale, label in _SCALES:
        quotient, remaining = divmod(remaining, scale)
        if quotient:
            parts.append(f"{_small_number_words(quotient)} {label}")
    if remaining:
        parts.append(_small_number_words(remaining))
    return " ".join(parts)


def _expand_number_token(token: str, style: str) -> str:
    if style == "digit-by-digit":
        if len(token) < 2:
            return token
        return " ".join(token)
    # cardinal: leading zeros signal serial numbers or codes, so leave them.
    if token.startswith("0") and len(token) > 1:
        return token
    number = int(token)
    if number >= 10 ** 12:
        return token
    return _number_to_words(number)


def _spell_acronym(match: re.Match[str]) -> str:
    token = match.group(1)
    if _ROMAN_NUMERAL_RE.match(token):
        # "Chapter IV" should stay a numeral, not become "I.V.".
        return token
    dotted = ".".join(token)
    # Merge with an existing sentence period ("the FBI." -> "the F.B.I.").
    following = match.string[match.end():match.end() + 1]
    return dotted if following == "." else dotted + "."


def apply_text_interpretation(text: str, parameters: Any) -> str:
    """Conservatively rewrite ``text`` according to ``interpretation.*`` controls.

    The canonical schema defaults describe behavior providers already perform
    well on their own (contextual numbers, automatic acronyms, known
    abbreviations), so this function only rewrites when a control is set to a
    value that *demands* a textual transformation -- a neutral document is a
    guaranteed no-op.  Implemented transforms, applied in a fixed order:

    1. ``interpretation.number_style`` == ``"digit-by-digit"``: standalone
       integer tokens are spaced per digit ("8675309" -> "8 6 7 5 3 0 9").
    2. ``interpretation.number_style`` == ``"cardinal"``: standalone integers
       below one trillion become English words ("42" -> "forty-two").
    3. ``interpretation.acronym_style`` == ``"spell"``: uppercase tokens of
       two to eight letters become dotted letters ("NASA" -> "N.A.S.A.");
       Roman numerals are exempt.
    4. ``interpretation.punctuation_sensitivity`` >= 0.9 (default is 0.65):
       pause-oriented cleanup -- spaced en/em dashes become a comma pause and
       the single-character ellipsis becomes "..." for consistent provider
       pausing.

    Unknown, absent, or default-valued controls change nothing; the function
    never raises on odd input, it simply returns the text unchanged.
    """
    result = text if isinstance(text, str) else str(text or "")
    if not result:
        return result

    number_style = str(get_path(parameters, "interpretation.number_style", "contextual") or "contextual")
    if number_style in ("digit-by-digit", "cardinal"):
        result = _NUMBER_TOKEN_RE.sub(
            lambda match: _expand_number_token(match.group(1), number_style), result
        )

    acronym_style = str(get_path(parameters, "interpretation.acronym_style", "auto") or "auto")
    if acronym_style == "spell":
        result = _ACRONYM_TOKEN_RE.sub(_spell_acronym, result)

    try:
        punctuation_sensitivity = float(
            get_path(parameters, "interpretation.punctuation_sensitivity", 0.65)
        )
    except (TypeError, ValueError):
        punctuation_sensitivity = 0.65
    if punctuation_sensitivity >= 0.9:
        result = _ASIDE_DASH_RE.sub(", ", result)
        result = _ELLIPSIS_RE.sub("...", result)

    return result
