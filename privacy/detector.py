"""
privacy/detector.py

Stage 1 of the privacy pipeline (docs/api.md sections 1.3 / 18):
    Detection -> Redaction -> Verification -> Transmission

Finds PII/sensitive text and reports WHERE it is (bbox) and WHAT type
it is, in the shape defined by docs/api.md section 4. Does not redact,
verify, or transmit anything -- see redactor.py and verifier.py for
the next stages.

This is a regex/rule-based MVP: fast, fully on-device, and a
reasonable first pass -- but it is NOT a complete PII detector.
Free-form fields like passwords have no fixed structure, so detection
there is inherently weak. This module is written so a future ML/OCR/
vision-based classifier can replace or sit alongside the rules below
without changing detect_pii()'s public signature or output shape.

Security notes
---------------
- The raw matched value is never included in a PrivacyRegion or logged.
- Detected substrings live only inside a single function call and are
  discarded once a Detection/PrivacyRegion is built.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

try:
    from .schemas import (
        BBox,
        DEFAULT_REDACTION_FOR_TYPE,
        PrivacyRegion,
        TextRegion,
        error_response,
    )
except ImportError:  # pragma: no cover - allows `python detector.py` standalone
    from schemas import (
        BBox,
        DEFAULT_REDACTION_FOR_TYPE,
        PrivacyRegion,
        TextRegion,
        error_response,
    )

_DEFAULT_BBOX: BBox = (0, 0, 0, 0)

# Minimum bbox width/height. Rounding during char-fraction interpolation
# can otherwise collapse a short match (e.g. a 4-digit OTP) into a
# zero-width/zero-height box, which is schema-valid but useless for
# redaction (a 0-area black box hides nothing).
_MIN_BBOX_SIZE = 4

_CONTEXT_WINDOW_CHARS = 25  # how far around a match to look for keywords


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    pii_type: str
    pattern: re.Pattern
    base_confidence: float
    # Optional extra check on the matched string (e.g. a checksum) to
    # reject false positives.
    validator: Optional[Callable[[str], bool]] = None


def _luhn_check(number: str) -> bool:
    """Luhn checksum, used to sanity-check card numbers."""
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 12:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, digit in enumerate(digits):
        if i % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


# Standalone regexes -- reliable enough on their own to not need
# nearby-keyword context.
_RULES: list[Rule] = [
    Rule("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), 0.95),
    Rule(
        "phone",
        # Indian mobile numbers: optional +91/0 prefix, 10 digits, 6-9 start.
        re.compile(r"(?<!\d)(?:\+91[\-\s]?|0)?[6-9]\d{9}(?!\d)"),
        0.85,
    ),
    Rule("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), 0.9),
    Rule(
        "aadhaar",
        # 12 digits, optionally grouped 4-4-4 with spaces/hyphens.
        re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
        0.7,
    ),
    Rule(
        "credit_card",
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        0.6,
        validator=_luhn_check,
    ),
    Rule(
        "date_of_birth",
        re.compile(r"\b(0?[1-9]|[12]\d|3[01])[/\-.](0?[1-9]|1[0-2])[/\-.](\d{4}|\d{2})\b"),
        0.6,
    ),
]

# NOTE on debit_card: at the MVP level a card-shaped, Luhn-valid 13-19
# digit number is reported as "credit_card". Reliably telling a debit
# card from a credit card needs the BIN/network range or an on-screen
# label ("Debit Card ending in ...") -- future work, see README.

# Categories only detected via nearby keyword context, because their
# raw pattern (a bare short/medium digit run) is too generic to use
# unconditionally without producing frequent false positives.
_CONTEXTUAL_KEYWORDS: dict[str, tuple[re.Pattern, list[str], float]] = {
    "otp": (
        re.compile(r"(?<!\d)\d{4,6}(?!\d)"),
        ["otp", "one time password", "verification code", "one-time password"],
        0.9,
    ),
    "cvv": (
        re.compile(r"(?<!\d)\d{3,4}(?!\d)"),
        ["cvv", "cvv2", "security code", "card verification"],
        0.85,
    ),
    "password": (
        # Passwords have no fixed structure at all -- this only fires
        # when a "password:"-style label sits directly before a token,
        # which is why it's the weakest category in this MVP.
        re.compile(r"(?<=[:=]\s)\S{4,64}"),
        ["password", "pwd", "passcode", "pass:"],
        0.5,
    ),
    "account_number": (
        # A bare 9-18 digit run is indistinguishable from Aadhaar,
        # phone numbers, order IDs, timestamps, etc, so this is
        # keyword-gated like OTP/CVV to keep false positives down.
        re.compile(r"(?<!\d)\d{9,18}(?!\d)"),
        ["account no", "account number", "a/c", "acc no", "bank account", "iban"],
        0.75,
    ),
}


# ---------------------------------------------------------------------------
# Core detection logic
# ---------------------------------------------------------------------------

def _find_regex_matches(rule: Rule, text: str) -> list[re.Match]:
    return [m for m in rule.pattern.finditer(text) if rule.validator is None or rule.validator(m.group())]


def _find_contextual_matches(
    keyword_pattern: re.Pattern,
    keywords: list[str],
    base_confidence: float,
    text: str,
) -> list[tuple[re.Match, float]]:
    lowered = text.lower()
    results: list[tuple[re.Match, float]] = []
    for m in keyword_pattern.finditer(text):
        start = max(0, m.start() - _CONTEXT_WINDOW_CHARS)
        end = min(len(text), m.end() + _CONTEXT_WINDOW_CHARS)
        window = lowered[start:end]
        if any(kw in window for kw in keywords):
            results.append((m, base_confidence))
    return results


def _char_span_to_bbox(region: TextRegion, start: int, end: int) -> BBox:
    """Map a character span within `region.text` to an approximate bbox.

    MVP approach: if the region has a bbox, linearly interpolate the
    horizontal extent based on character position (a reasonable first
    approximation for a single-line OCR word/line box). If no bbox is
    available, return the placeholder bbox. This is a clearly-marked
    seam for a future OCR-character-box-based implementation.
    """
    if region.bbox is None:
        return _DEFAULT_BBOX

    x1, y1, x2, y2 = region.bbox
    text_len = max(len(region.text), 1)
    width = x2 - x1

    frac_start = start / text_len
    frac_end = end / text_len

    new_x1 = round(x1 + width * frac_start)
    new_x2 = max(round(x1 + width * frac_end), new_x1)

    # Guard against degenerate zero-width boxes from rounding on short
    # matches, without escaping the parent bbox.
    if new_x2 - new_x1 < _MIN_BBOX_SIZE:
        pad = (_MIN_BBOX_SIZE - (new_x2 - new_x1) + 1) // 2
        new_x1 = max(x1, new_x1 - pad)
        new_x2 = min(x2, new_x1 + _MIN_BBOX_SIZE)
        new_x1 = min(new_x1, new_x2)

    new_y1, new_y2 = y1, y2
    if new_y2 - new_y1 < _MIN_BBOX_SIZE:
        new_y2 = new_y1 + _MIN_BBOX_SIZE

    return (new_x1, new_y1, new_x2, new_y2)


def detect_pii_in_region(region: TextRegion, start_id: int = 1) -> list[PrivacyRegion]:
    """Run all detection rules over a single TextRegion.

    Args:
        region: the text (plus optional bbox) to scan.
        start_id: numeric suffix to start id generation from, so
            callers batching multiple regions keep ids unique.

    Returns:
        A list of PrivacyRegion objects. Never contains the raw matched
        text.
    """
    text = region.text
    detections: list[PrivacyRegion] = []
    claimed_spans: list[tuple[int, int]] = []  # avoid double-reporting overlaps

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= s or start >= e) for s, e in claimed_spans)

    next_id = start_id

    for rule in _RULES:
        for match in _find_regex_matches(rule, text):
            span = match.span()
            if _overlaps(*span):
                continue
            claimed_spans.append(span)
            bbox = _char_span_to_bbox(region, *span)
            detections.append(
                PrivacyRegion(
                    id=f"privacy_{next_id:03d}",
                    type=rule.pii_type,
                    bbox=bbox,
                    redaction=DEFAULT_REDACTION_FOR_TYPE.get(rule.pii_type, "black"),
                    confidence=rule.base_confidence,
                )
            )
            next_id += 1

    for pii_type, (pattern, keywords, base_conf) in _CONTEXTUAL_KEYWORDS.items():
        for match, conf in _find_contextual_matches(pattern, keywords, base_conf, text):
            span = match.span()
            if _overlaps(*span):
                continue
            claimed_spans.append(span)
            bbox = _char_span_to_bbox(region, *span)
            detections.append(
                PrivacyRegion(
                    id=f"privacy_{next_id:03d}",
                    type=pii_type,
                    bbox=bbox,
                    redaction=DEFAULT_REDACTION_FOR_TYPE.get(pii_type, "black"),
                    confidence=conf,
                )
            )
            next_id += 1

    return detections


def detect_pii(regions: list[TextRegion]) -> dict:
    """Detect PII across multiple OCR-style text regions.

    This is the entry point the extension/OCR pipeline calls once OCR
    has produced TextRegion objects for a screenshot.

    Returns:
        On success, docs/api.md section 4 shape:
            {"regions": [{"id","type","bbox","redaction","confidence"}, ...]}
        On bad input, the generic error envelope (section 15) with code
        INVALID_REQUEST, instead of raising -- so callers across a
        module/IPC boundary always get JSON back, never an exception.
    """
    try:
        if not isinstance(regions, list):
            raise TypeError("regions must be a list of TextRegion")
        for region in regions:
            if not isinstance(region, TextRegion):
                raise TypeError("each region must be a TextRegion instance")

        all_detections: list[PrivacyRegion] = []
        next_id = 1
        for region in regions:
            region_detections = detect_pii_in_region(region, start_id=next_id)
            all_detections.extend(region_detections)
            next_id += len(region_detections)

        return {"regions": [d.to_dict() for d in all_detections]}

    except (TypeError, ValueError) as exc:
        # Never echo raw input text back in the error message -- it may
        # itself contain sensitive data.
        return error_response("INVALID_REQUEST", f"Invalid detector input ({exc.__class__.__name__}).")
    except Exception:  # pragma: no cover - defensive fallback
        return error_response("PRIVACY_DETECTION_FAILED", "Detection failed unexpectedly.")


def detect_pii_in_text(text: str) -> dict:
    """Convenience wrapper for plain text with no bbox info (CLI/testing).

    Detections will carry the placeholder bbox [0, 0, 0, 0].
    """
    if not isinstance(text, str):
        return error_response("INVALID_REQUEST", "text must be a string")
    return detect_pii([TextRegion(text=text)])


if __name__ == "__main__":
    sample_regions = [
        TextRegion(text="Contact me at user@example.com", bbox=(100, 200, 300, 230)),
        TextRegion(text="OTP is 483920, do not share", bbox=(50, 50, 250, 80)),
    ]
    result = detect_pii(sample_regions)
    # Safe to print: contains only type/bbox/redaction/confidence, never the value.
    for r in result.get("regions", []):
        print(r)
