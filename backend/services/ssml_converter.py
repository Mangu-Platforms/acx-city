"""
SSML Import Converter

Converts Audible/Apple SSML scripts to ACX City's tag format and vice versa.
Uses xml.etree.ElementTree for parsing with robust error handling for malformed SSML.
"""

import re
import xml.etree.ElementTree as ET
from typing import Optional


# ---------------------------------------------------------------------------
# Pitch-to-emotion mapping
# ---------------------------------------------------------------------------
PITCH_EMOTION_MAP = {
    "+10%": "excited",
    "+20%": "excited",
    "+30%": "surprised",
    "+40%": "surprised",
    "+50%": "shocked",
    "-10%": "sad",
    "-20%": "sad",
    "-30%": "dejected",
    "-40%": "dark",
    "-50%": "ominous",
}

RATE_MAP = {
    "slow": "slow",
    "x-slow": "slow",
    "medium": "normal",
    "fast": "fast",
    "x-fast": "fast",
}

_SSML_NS = "http://www.w3.org/2001/10/synthesis"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_ns(tag: str) -> str:
    """Remove XML namespace from a tag name."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _map_pitch(pitch_str: str) -> Optional[str]:
    """Map a SSML pitch attribute to an ACX emotion tag (best-effort)."""
    pitch_str = pitch_str.strip().lower()
    if pitch_str in PITCH_EMOTION_MAP:
        return PITCH_EMOTION_MAP[pitch_str]
    # Try numeric matching – grab the closest bucket
    m = re.match(r"([+-]?\d+)%", pitch_str)
    if m:
        val = int(m.group(1))
        if val >= 40:
            return "shocked"
        elif val >= 20:
            return "excited"
        elif val >= 5:
            return "happy"
        elif val <= -40:
            return "ominous"
        elif val <= -20:
            return "sad"
        elif val <= -5:
            return "melancholy"
    return None


def _expand_number(text: str) -> str:
    """Naive number expansion for <say-as interpret-as="number">."""
    # For now just return the text stripped; a full number-to-words
    # implementation is out of scope – callers can post-process.
    return text.strip()


# ---------------------------------------------------------------------------
# SSML → ACX
# ---------------------------------------------------------------------------

def _element_to_acx(elem: ET.Element) -> str:
    """Recursively convert an SSML element tree node to ACX-tagged text."""
    tag = _strip_ns(elem.tag)

    # elem.text is the text content INSIDE the element, before the first child.
    # child.tail is text after each child. Collect all inner content first.
    head_text = elem.text or ""
    tail_text = elem.tail or ""

    # Build full inner content: head_text + converted children (with their tails)
    children_parts: list[str] = [head_text]
    for child in elem:
        if isinstance(child, ET.Element):
            children_parts.append(_element_to_acx(child))
        else:
            children_parts.append(str(child))
    full_inner = "".join(children_parts)

    if tag == "speak":
        # Root wrapper – just pass through inner + tail
        return full_inner + tail_text

    if tag == "emphasis":
        return f"[emphasis]{full_inner}[/emphasis]{tail_text}"

    if tag == "break":
        time_attr = elem.get("time", "500ms")
        ms = time_attr.lower().replace("ms", "").strip()
        try:
            ms = int(ms)
        except ValueError:
            ms = 500
        return f"[pause:{ms}]{tail_text}"

    if tag == "prosody":
        rate = elem.get("rate", "")
        pitch = elem.get("pitch", "")

        if rate:
            mapped = RATE_MAP.get(rate.lower(), rate.lower())
            return f"[rate:{mapped}]{full_inner}{tail_text}"
        elif pitch:
            emotion = _map_pitch(pitch)
            if emotion:
                return f"[{emotion}]{full_inner}{tail_text}"
            return full_inner + tail_text
        return full_inner + tail_text

    if tag == "say-as":
        interpret_as = elem.get("interpret-as", "")
        if interpret_as == "number":
            return _expand_number(full_inner) + tail_text
        return full_inner + tail_text

    if tag == "lang":
        lang = elem.get("{http://www.w3.org/XML/1998/namespace}lang", elem.get("lang", "und"))
        return f"[lang:{lang}]{full_inner}[/lang]{tail_text}"

    if tag == "voice":
        name = elem.get("name", "unknown")
        return f"[SPEAKER:{name}]{full_inner}{tail_text}"

    if tag in ("p", "s"):
        return full_inner + tail_text

    if tag == "sub":
        alias = elem.get("alias", "")
        if alias:
            return alias + tail_text
        return full_inner + tail_text

    # Fallback: pass through inner content
    return full_inner + tail_text


def convert_ssml_to_acx(ssml_text: str) -> str:
    """
    Parse an SSML string and convert it to ACX City tag format.

    Supported conversions:
      - <emphasis level="strong"> → [emphasis]text[/emphasis]
      - <break time="500ms"/>     → [pause:500]
      - <prosody rate="slow">     → [rate:slow]text
      - <prosody rate="fast">     → [rate:fast]text
      - <prosody pitch="+10%">    → mapped emotion tag
      - <say-as interpret-as="number"> → expanded number text
      - <lang xml:lang="en-US">   → [lang:en-US]…[/lang] metadata
      - <voice name="X">          → [SPEAKER:X]

    Args:
        ssml_text: Raw SSML markup string.

    Returns:
        ACX-tagged plain text.

    Raises:
        ValueError: If the SSML cannot be parsed.
    """
    if not ssml_text or not ssml_text.strip():
        return ""

    # Normalise common SSML quirks
    text = ssml_text.strip()
    # Ensure root <speak> wrapper exists for ET
    if not text.startswith("<speak"):
        text = f"<speak>{text}</speak>"

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"Malformed SSML: {exc}") from exc

    result = _element_to_acx(root)
    # Collapse excessive whitespace
    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# ---------------------------------------------------------------------------
# ACX → SSML
# ---------------------------------------------------------------------------

# Emotion tags → prosody pitch
_EMOTION_PITCH = {
    "excited": "+20%",
    "happy": "+10%",
    "surprised": "+30%",
    "shocked": "+50%",
    "sad": "-20%",
    "melancholy": "-10%",
    "dejected": "-30%",
    "dark": "-40%",
    "ominous": "-50%",
}

# Unified tag tokenizer for ACX tags
_ACX_TAG_RE = re.compile(
    r"\[emphasis\]"
    r"|\[/emphasis\]"
    r"|\[pause:(\d+)\]"
    r"|\[rate:(\w+)\]"
    r"|\[SPEAKER:(\w+)\]"
    r"|\[lang:([\w-]+)\]"
    r"|\[/lang\]"
    r"|\[(" + "|".join(re.escape(k) for k in _EMOTION_PITCH) + r")\]"
)


def _tokenize_acx(acx_text: str) -> list:
    """Tokenize ACX text into a list of (type, value, content) tuples.

    Returns a flat list of tokens. Each token is one of:
      ('text', content, None)
      ('tag', tag_name, tag_attrs_dict)
    """
    tokens: list = []
    last_end = 0

    for m in _ACX_TAG_RE.finditer(acx_text):
        # Text before this tag
        if m.start() > last_end:
            tokens.append(("text", acx_text[last_end:m.start()], None))
        last_end = m.end()

        full = m.group(0)
        if full == "[emphasis]":
            tokens.append(("tag", "emphasis_open", {}))
        elif full == "[/emphasis]":
            tokens.append(("tag", "emphasis_close", {}))
        elif full.startswith("[pause:"):
            tokens.append(("tag", "pause", {"time": m.group(1)}))
        elif full.startswith("[rate:"):
            tokens.append(("tag", "rate", {"value": m.group(2)}))
        elif full.startswith("[SPEAKER:"):
            tokens.append(("tag", "speaker", {"name": m.group(3)}))
        elif full.startswith("[lang:"):
            tokens.append(("tag", "lang_open", {"lang": m.group(4)}))
        elif full == "[/lang]":
            tokens.append(("tag", "lang_close", {}))
        else:
            # Emotion tag
            for emotion in _EMOTION_PITCH:
                if full == f"[{emotion}]":
                    tokens.append(("tag", "emotion", {"emotion": emotion}))
                    break

    # Trailing text
    if last_end < len(acx_text):
        tokens.append(("text", acx_text[last_end:], None))

    return tokens


def convert_acx_to_ssml(acx_text: str) -> str:
    """
    Convert ACX City tagged text back to SSML.

    Uses a token-based approach: tokenizes the ACX text, then builds
    SSML by pairing open/close tags and wrapping content.

    Args:
        acx_text: Text with ACX tags.

    Returns:
        SSML string wrapped in <speak>.
    """
    if not acx_text or not acx_text.strip():
        return "<speak></speak>"

    tokens = _tokenize_acx(acx_text)
    parts: list[str] = []
    i = 0

    while i < len(tokens):
        kind, val, attrs = tokens[i]

        if kind == "text":
            parts.append(val)
            i += 1

        elif kind == "tag" and val == "pause":
            parts.append(f'<break time="{attrs["time"]}ms"/>')
            i += 1

        elif kind == "tag" and val == "emphasis_open":
            # Collect content until [/emphasis]
            inner_parts: list[str] = []
            i += 1
            while i < len(tokens):
                k2, v2, a2 = tokens[i]
                if k2 == "tag" and v2 == "emphasis_close":
                    i += 1
                    break
                if k2 == "text":
                    inner_parts.append(v2)
                elif k2 == "tag" and v2 == "pause":
                    inner_parts.append(f'<break time="{a2["time"]}ms"/>')
                i += 1
            parts.append(f'<emphasis level="strong">{"".join(inner_parts)}</emphasis>')

        elif kind == "tag" and val == "lang_open":
            inner_parts = []
            i += 1
            while i < len(tokens):
                k2, v2, a2 = tokens[i]
                if k2 == "tag" and v2 == "lang_close":
                    i += 1
                    break
                if k2 == "text":
                    inner_parts.append(v2)
                i += 1
            parts.append(f'<lang xml:lang="{attrs["lang"]}">{"".join(inner_parts)}</lang>')

        elif kind == "tag" and val == "rate":
            # Inline tag: content is text until next ACX tag
            inner_parts = []
            i += 1
            while i < len(tokens):
                k2, v2, _ = tokens[i]
                if k2 == "tag":
                    break
                inner_parts.append(v2)
                i += 1
            parts.append(f'<prosody rate="{attrs["value"]}">{"".join(inner_parts)}</prosody>')

        elif kind == "tag" and val == "speaker":
            inner_parts = []
            i += 1
            while i < len(tokens):
                k2, v2, _ = tokens[i]
                if k2 == "tag":
                    break
                inner_parts.append(v2)
                i += 1
            parts.append(f'<voice name="{attrs["name"]}">{"".join(inner_parts)}</voice>')

        elif kind == "tag" and val == "emotion":
            emotion = attrs["emotion"]
            pitch = _EMOTION_PITCH.get(emotion, "+0%")
            inner_parts = []
            i += 1
            while i < len(tokens):
                k2, v2, _ = tokens[i]
                if k2 == "tag":
                    break
                inner_parts.append(v2)
                i += 1
            parts.append(f'<prosody pitch="{pitch}">{"".join(inner_parts)}</prosody>')

        elif kind == "tag" and val == "emphasis_close":
            # Stray close tag – skip
            i += 1

        elif kind == "tag" and val == "lang_close":
            i += 1

        else:
            i += 1

    result = "".join(parts)
    if not result.strip().startswith("<speak"):
        result = f"<speak>{result}</speak>"
    return result


# ---------------------------------------------------------------------------
# SSML Validation
# ---------------------------------------------------------------------------

def validate_ssml(ssml_text: str) -> dict:
    """
    Validate SSML structure.

    Returns:
        dict with keys:
          - valid (bool)
          - errors (list[str])
          - warnings (list[str])
          - tag_count (dict[str, int])
    """
    result: dict = {
        "valid": False,
        "errors": [],
        "warnings": [],
        "tag_count": {},
    }

    if not ssml_text or not ssml_text.strip():
        result["errors"].append("Empty SSML input")
        return result

    text = ssml_text.strip()

    # Wrap if needed for parsing
    parse_text = text
    if not parse_text.startswith("<speak"):
        parse_text = f"<speak>{parse_text}</speak>"
        result["warnings"].append("Missing <speak> root element – wrapped automatically")

    try:
        root = ET.fromstring(parse_text)
    except ET.ParseError as exc:
        result["errors"].append(f"XML parse error: {exc}")
        return result

    # Check root is <speak>
    root_tag = _strip_ns(root.tag)
    if root_tag != "speak":
        result["errors"].append(f"Root element must be <speak>, got <{root_tag}>")

    # Walk tree and count tags
    tag_counts: dict[str, int] = {}
    for elem in root.iter():
        tag = _strip_ns(elem.tag)
        if tag == "speak":
            continue
        tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # Warn on unrecognised tags
        known = {
            "emphasis", "break", "prosody", "say-as", "lang",
            "voice", "p", "s", "sub", "phoneme", "audio",
        }
        if tag not in known:
            result["warnings"].append(f"Unrecognised SSML tag: <{tag}>")

    result["tag_count"] = tag_counts

    if not result["errors"]:
        result["valid"] = True

    return result


# ---------------------------------------------------------------------------
# Audible Script Import Pipeline
# ---------------------------------------------------------------------------

def import_audible_script(
    ssml_text: str,
    character_map: Optional[dict] = None,
) -> dict:
    """
    Full import pipeline for Audible / Apple SSML scripts.

    Args:
        ssml_text:      Raw SSML from Audible / Apple Books.
        character_map:  Optional mapping of voice names to character names.
                        e.g. {"Samantha": "Narrator", "Daniel": "John"}

    Returns:
        dict with keys:
          - text (str):               Converted ACX-tagged text.
          - characters_detected (list[str]): Voice names found.
          - warnings (list[str]):     Any issues encountered during import.
    """
    warnings: list[str] = []

    # 1. Validate
    validation = validate_ssml(ssml_text)
    if not validation["valid"]:
        # Attempt conversion anyway for best-effort, but flag errors
        warnings.extend(
            f"Validation error: {e}" for e in validation["errors"]
        )
    warnings.extend(validation.get("warnings", []))

    # 2. Detect characters (voices)
    characters_detected: list[str] = []
    voice_re = re.compile(r'<voice\s+[^>]*name="([^"]+)"', re.IGNORECASE)
    for m in voice_re.finditer(ssml_text):
        name = m.group(1)
        if name not in characters_detected:
            characters_detected.append(name)

    # 3. Apply character map if provided
    if character_map:
        for voice_name, char_name in character_map.items():
            ssml_text = ssml_text.replace(
                f'<voice name="{voice_name}"',
                f'<voice name="{char_name}"',
            )
            # Update detected list
            if voice_name in characters_detected:
                idx = characters_detected.index(voice_name)
                characters_detected[idx] = char_name

    # 4. Convert
    try:
        acx_text = convert_ssml_to_acx(ssml_text)
    except ValueError as exc:
        warnings.append(f"Conversion failed: {exc}")
        acx_text = ""

    # 5. Post-conversion sanity checks
    if not acx_text.strip():
        warnings.append("Conversion produced empty output")

    remaining_ssml = re.findall(r"<[a-z]+[\s>]", acx_text)
    if remaining_ssml:
        warnings.append(
            f"Possible unconverted SSML fragments: {remaining_ssml[:5]}"
        )

    return {
        "text": acx_text,
        "characters_detected": characters_detected,
        "warnings": warnings,
    }
