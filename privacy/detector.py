"""
privacy/detector.py

Detection stage of the privacy pipeline:
    Detection -> Redaction -> Verification -> Transmission

This module is responsible ONLY for detecting PII / sensitive
information in text and reporting *where* it is (bounding box) and
*what type* it is, along with a confidence score.

It deliberately does NOT:
    - redact anything
    - verify redaction
    - send anything over the network
    - depend on the browser extension, the FastAPI server, or any VLM

Design notes
------------
The MVP uses regex/rule-based classifiers. Regex is fast and fully
on-device, which fits the "on-device visual perception" goal, but it
is NOT a complete PII detector -- especially for free-form fields
like passwords, which have no fixed structure. This module is built
so a future ML/OCR/vision-based classifier can be swapped in or added
alongside the rule-based one without changing the public API.

The detector works over "text regions" -- pieces of text that already
have an associated bounding box (as would come from an OCR pass over
a screenshot). If no bounding box is available (e.g. detecting over
raw page text with no visual layout yet), a placeholder bbox of
[0, 0, 0, 0] is used so the output schema stays consistent; callers
should replace it with real coordinates once OCR/layout info exists.

Security notes
---------------
- The actual sensitive substring is NEVER included in the returned
  detection objects.
- Nothing in this module calls print()/logging with sensitive text.
- Detected values are used only transiently (within a function call)
  and are not stored on any object that outlives detection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

BBox = tuple[int, int, int, int]  # (x1, y1, x2, y2)

_DEFAULT_BBOX: BBox = (0, 0, 0, 0)

# Minimum bbox width/height (in the same units as input bboxes, e.g.
# pixels). Rounding during char-fraction interpolation can otherwise
# collapse a short match (e.g. a 4-digit OTP) into a zero-width or
# zero-height box, which is schema-valid but useless downstream --
# the redaction stage cannot black out a box with no area. Detected
# spans are always widened to at least this size, clamped to stay
# inside the region's own bbox.
_MIN_BBOX_SIZE = 4


@dataclass(frozen=True)
class TextRegion:
    """A piece of text with an optional bounding box, e.g. from OCR.

    This is the input unit the detector works on. `bbox` is optional
    because the MVP may run on plain text before any OCR/layout stage
    exists; when omitted, detections from this region get a
    placeholder bbox.
    """

    text: str
    bbox: Optional[BBox] = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("TextRegion.text must be a string")
        if self.bbox is not None:
            if len(self.bbox) != 4:
                raise ValueError("bbox must be a 4-tuple (x1, y1, x2, y2)")
            x1, y1, x2, y2 = self.bbox
            if x2 < x1 or y2 < y1:
                raise ValueError("bbox coordinates must satisfy x2>=x1 and y2>=y1")


@dataclass(frozen=True)
class Detection:
    """A single detected sensitive-information region.

    Note: this object intentionally has no field for the raw matched
    value. Only type/location/confidence are kept.
    """

    id: str
    type: str
    bbox: BBox
    confidence: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "bbox": list(self.bbox),
            "confidence": round(self.confidence, 4),
        }


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------
#
# Each rule maps a PII category to a compiled regex and a base
# confidence score. Confidence is a rough, static estimate of how
# reliable that pattern is for the MVP -- not a statistically
# calibrated probability. Regexes are intentionally conservative
# (favor fewer false positives) but MVP-level, not exhaustive.

@dataclass(frozen=True)
class Rule:
    pii_type: str
    pattern: re.Pattern
    base_confidence: float
    # Optional extra check run on the matched string (e.g. checksum,
    # keyword context) to refine confidence or reject false positives.
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


def _pan_validator(value: str) -> bool:
    # Indian PAN: 5 letters, 4 digits, 1 letter. Regex already enforces
    # the shape; this only exists as an extension point (e.g. checking
    # the 4th letter category code) for later.
    return True


_RULES: list[Rule] = [
    Rule(
        pii_type="email",
        pattern=re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        base_confidence=0.95,
    ),
    Rule(
        pii_type="phone",
        # Indian mobile numbers: optional +91 / 0 prefix, then a 10-digit
        # number starting 6-9. Also allows common separators.
        pattern=re.compile(
            r"(?<!\d)(?:\+91[\-\s]?|0)?[6-9]\d{9}(?!\d)"
        ),
        base_confidence=0.85,
    ),
    Rule(
        pii_type="otp",
        # Heuristic: a 4-6 digit standalone number near the word "OTP"
        # is handled in `_detect_contextual_otp`; this pattern alone is
        # too ambiguous (matches any short number), so it is deliberately
        # NOT registered as a standalone high-confidence rule. See below.
        pattern=re.compile(r"(?<!\d)\d{4,6}(?!\d)"),
        base_confidence=0.30,  # low on its own; boosted by context
    ),
    Rule(
        pii_type="pan",
        pattern=re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
        base_confidence=0.9,
        validator=_pan_validator,
    ),
    Rule(
        pii_type="aadhaar",
        # 12 digits, optionally grouped as 4-4-4 with spaces/hyphens.
        pattern=re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
        base_confidence=0.7,
    ),
    Rule(
        pii_type="credit_card",
        pattern=re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        base_confidence=0.6,
        validator=_luhn_check,
    ),
    Rule(
        pii_type="cvv",
        # Only matched via context (near "CVV"); see `_detect_contextual`.
        pattern=re.compile(r"(?<!\d)\d{3,4}(?!\d)"),
        base_confidence=0.3,
    ),
    Rule(
        pii_type="date_of_birth",
        pattern=re.compile(
            r"\b(0?[1-9]|[12]\d|3[01])[/\-.](0?[1-9]|1[0-2])[/\-.](\d{4}|\d{2})\b"
        ),
        base_confidence=0.6,
    ),
]

# Categories that are only ever detected via nearby keyword context,
# not a standalone regex, because their raw pattern is too generic.
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
        # Password values have no fixed structure at all, so this is
        # the weakest category in the MVP -- it only fires when a
        # "password:"-style label is directly adjacent to a token.
        re.compile(r"(?<=[:=]\s)\S{4,64}"),
        ["password", "pwd", "passcode", "pass:"],
        0.5,
    ),
    "account_number": (
        # Bank account numbers have no fixed structure or checksum, and
        # a bare 9-18 digit run is indistinguishable from Aadhaar, phone
        # numbers, order IDs, timestamps, etc. Previously this was an
        # unconditional rule and produced frequent false positives
        # (e.g. matching before the Aadhaar rule could claim the span).
        # Now, like OTP/CVV, it only fires near an explicit keyword.
        re.compile(r"(?<!\d)\d{9,18}(?!\d)"),
        ["account no", "account number", "a/c", "acc no", "bank account", "iban"],
        0.75,
    ),
}

_CONTEXT_WINDOW_CHARS = 25  # how far around a match to look for keywords


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
    """Find matches of `keyword_pattern` that occur near one of `keywords`.

    Returns (match, confidence) pairs. Confidence is boosted when a
    keyword is found immediately before/around the match.
    """
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
    horizontal extent based on character position (assumes a single
    line of roughly monospaced text, which is a reasonable first
    approximation for OCR word/line boxes). If no bbox is available,
    return the placeholder bbox.

    This is a clearly-marked seam for a future, more accurate
    OCR-character-box-based implementation.
    """
    if region.bbox is None:
        return _DEFAULT_BBOX

    x1, y1, x2, y2 = region.bbox
    text_len = max(len(region.text), 1)
    width = x2 - x1

    frac_start = start / text_len
    frac_end = end / text_len

    new_x1 = round(x1 + width * frac_start)
    new_x2 = round(x1 + width * frac_end)
    new_x2 = max(new_x2, new_x1)

    # Guard against degenerate zero-width boxes from rounding on short
    # matches. Widen symmetrically but never escape the parent bbox
    # [x1, x2], so the approximation still stays "inside" the region
    # it was interpolated from.
    if new_x2 - new_x1 < _MIN_BBOX_SIZE:
        pad = (_MIN_BBOX_SIZE - (new_x2 - new_x1) + 1) // 2
        new_x1 = max(x1, new_x1 - pad)
        new_x2 = min(x2, new_x1 + _MIN_BBOX_SIZE)
        new_x1 = min(new_x1, new_x2)  # safety if region itself is < MIN size

    # Same guard on the vertical axis: a region bbox that is itself
    # very thin (e.g. a tightly-cropped OCR line box) should not be
    # returned as zero-height either.
    new_y1, new_y2 = y1, y2
    if new_y2 - new_y1 < _MIN_BBOX_SIZE:
        new_y2 = new_y1 + _MIN_BBOX_SIZE

    return (new_x1, new_y1, new_x2, new_y2)


def detect_pii_in_region(region: TextRegion, start_id: int = 1) -> list[Detection]:
    """Run all detection rules over a single TextRegion.

    Args:
        region: the text (plus optional bbox) to scan.
        start_id: numeric suffix to start id generation from, so callers
            batching multiple regions can keep ids unique across calls.

    Returns:
        A list of Detection objects. Never contains the raw matched text.
    """
    text = region.text
    detections: list[Detection] = []
    claimed_spans: list[tuple[int, int]] = []  # avoid double-reporting overlaps

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= s or start >= e) for s, e in claimed_spans)

    next_id = start_id

    # 1. Plain regex rules (skip the two purely-contextual placeholder
    #    entries "otp"/"cvv" registered in _RULES -- they are handled
    #    only through _CONTEXTUAL_KEYWORDS to avoid noisy standalone hits).
    for rule in _RULES:
        if rule.pii_type in _CONTEXTUAL_KEYWORDS:
            continue
        for match in _find_regex_matches(rule, text):
            span = match.span()
            if _overlaps(*span):
                continue
            claimed_spans.append(span)
            bbox = _char_span_to_bbox(region, *span)
            detections.append(
                Detection(
                    id=f"privacy_{next_id:03d}",
                    type=rule.pii_type,
                    bbox=bbox,
                    confidence=rule.base_confidence,
                )
            )
            next_id += 1

    # 2. Contextual rules (otp, cvv, password) -- only fire near a keyword.
    for pii_type, (pattern, keywords, base_conf) in _CONTEXTUAL_KEYWORDS.items():
        for match, conf in _find_contextual_matches(pattern, keywords, base_conf, text):
            span = match.span()
            if _overlaps(*span):
                continue
            claimed_spans.append(span)
            bbox = _char_span_to_bbox(region, *span)
            detections.append(
                Detection(
                    id=f"privacy_{next_id:03d}",
                    type=pii_type,
                    bbox=bbox,
                    confidence=conf,
                )
            )
            next_id += 1

    return detections


def detect_pii(regions: list[TextRegion]) -> dict:
    """Public entry point: detect PII across multiple text regions.

    This is what the browser extension / OCR pipeline is expected to
    call once OCR has produced a list of TextRegion objects for a
    screenshot.

    Args:
        regions: list of TextRegion (text + optional bbox), e.g. from OCR.

    Returns:
        A dict matching docs/api.md section 4 ("Privacy Detection
        Output"):
            {"regions": [{"id": ..., "type": ..., "bbox": [...], "confidence": ...}, ...]}

        Per the mandatory pipeline order (docs/api.md section 1.3 /
        section 18), this module only performs Detection. The contract's
        example region objects also carry a "redaction" field, but that
        is assigned by the Redaction stage, not here -- callers should
        add it after this module's output, not expect it from
        detect_pii().
    """
    if not isinstance(regions, list):
        raise TypeError("regions must be a list of TextRegion")

    all_detections: list[Detection] = []
    next_id = 1
    for region in regions:
        if not isinstance(region, TextRegion):
            raise TypeError("each region must be a TextRegion instance")
        region_detections = detect_pii_in_region(region, start_id=next_id)
        all_detections.extend(region_detections)
        next_id += len(region_detections)

    return {"regions": [d.to_dict() for d in all_detections]}


def detect_pii_in_text(text: str) -> dict:
    """Convenience wrapper for plain text with no bounding box info yet.

    Useful for quick/CLI testing before an OCR stage exists. Detections
    will have the placeholder bbox [0, 0, 0, 0]. Returned shape matches
    detect_pii(): {"regions": [...]}.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return detect_pii([TextRegion(text=text)])


# ---------------------------------------------------------------------------
# Manual smoke test (does not print sensitive values)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample_regions = [
        TextRegion(text="Contact me at user@example.com", bbox=(100, 200, 300, 230)),
        TextRegion(text="OTP is 483920, do not share", bbox=(50, 50, 250, 80)),
    ]
    results = detect_pii(sample_regions)
    # Safe to print: this only contains type/bbox/confidence, never the value.
    for r in results["regions"]:
        print(r)
