"""
privacy/schemas.py

Shared data contracts for the privacy module, kept consistent with
docs/api.md (sections 1, 4, 5, 6, 15, 16).

Every other file in this module (detector.py, redactor.py, verifier.py)
imports its request/response shapes from here, so there is exactly one
place that defines what a "PrivacyRegion", a "redaction type", or an
"error response" looks like. If the contract changes, this is the only
file that should need to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# Geometry (docs/api.md section 1.1)
# ---------------------------------------------------------------------------

BBox = tuple[int, int, int, int]  # (x1, y1, x2, y2) -- left, top, right, bottom


def validate_bbox(bbox: BBox) -> None:
    if len(bbox) != 4:
        raise ValueError("bbox must be a 4-tuple (x1, y1, x2, y2)")
    x1, y1, x2, y2 = bbox
    if x2 < x1 or y2 < y1:
        raise ValueError("bbox must satisfy x2 >= x1 and y2 >= y1")


def validate_confidence(confidence: float) -> None:
    if not (0.0 <= confidence <= 1.0):
        raise ValueError("confidence must be between 0 and 1")


# ---------------------------------------------------------------------------
# Enums (docs/api.md sections 4 & 5)
# ---------------------------------------------------------------------------

# Sensitive types this MVP can actually detect. The full contract list
# (docs/api.md section 4) is larger (passport, driving_license, face,
# personal_text, pin, other) -- "face" belongs to the vision module,
# and the rest are left as future detector work; this module does not
# claim to cover them.
PIIType = Literal[
    "email",
    "phone",
    "otp",
    "pan",
    "aadhaar",
    "credit_card",
    "debit_card",
    "password",
    "cvv",
    "account_number",
    "date_of_birth",
]

RedactionType = Literal["black", "blur", "mask"]

# Default redaction technique per PII type (docs/api.md section 5):
# - "black": highly sensitive values that must never remain visible.
# - "mask":  partial visibility is treated as an acceptable trade-off
#            for these types by default (e.g. showing enough of an
#            email/phone to recognize which one it is), NOT a claim
#            that partial exposure is safe in every context -- a
#            masked email/phone can still be sensitive (e.g. linkable
#            to an identity, or itself confidential in some contexts),
#            so this default should be revisited per use case rather
#            than assumed safe.
# These are MVP defaults, attached at detection time, and can be
# overridden per-region later (e.g. by a user setting) without any
# schema change.
DEFAULT_REDACTION_FOR_TYPE: dict[str, RedactionType] = {
    "password": "black",
    "otp": "black",
    "cvv": "black",
    "pan": "black",
    "aadhaar": "black",
    "credit_card": "black",
    "debit_card": "black",
    "account_number": "black",
    "email": "mask",
    "phone": "mask",
    "date_of_birth": "mask",
}


# ---------------------------------------------------------------------------
# Input: OCR-style text regions (what the detector consumes)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TextRegion:
    """A piece of text with an optional bounding box, e.g. from OCR.

    This is the detector's input unit. bbox is optional so the MVP can
    also run over plain text before any OCR/layout stage exists; when
    omitted, detections from this region get a placeholder bbox.
    """

    text: str
    bbox: Optional[BBox] = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("TextRegion.text must be a string")
        if self.bbox is not None:
            validate_bbox(self.bbox)


# ---------------------------------------------------------------------------
# Output: privacy regions (docs/api.md section 4)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrivacyRegion:
    """One sensitive region, matching docs/api.md section 4.

    Never carries the raw sensitive value -- only its location,
    category, planned redaction technique, and detector confidence.
    """

    id: str
    type: PIIType
    bbox: BBox
    redaction: RedactionType
    confidence: float

    def __post_init__(self) -> None:
        validate_bbox(self.bbox)
        validate_confidence(self.confidence)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "bbox": list(self.bbox),
            "redaction": self.redaction,
            "confidence": round(self.confidence, 4),
        }


# ---------------------------------------------------------------------------
# Errors (docs/api.md sections 15 & 16)
# ---------------------------------------------------------------------------

# Only codes already defined in the shared contract are used here, so
# no other module or the integration lead has to learn a new one.
ErrorCode = Literal[
    "PRIVACY_DETECTION_FAILED",
    "PRIVACY_VERIFICATION_FAILED",
    "INVALID_REQUEST",
]


@dataclass(frozen=True)
class ErrorDetail:
    code: ErrorCode
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


def error_response(code: ErrorCode, message: str) -> dict:
    """Standard error envelope (docs/api.md section 15)."""
    return {"success": False, "error": ErrorDetail(code, message).to_dict()}


# ---------------------------------------------------------------------------
# Output: verification result (docs/api.md section 6)
# ---------------------------------------------------------------------------

def verification_success(regions: list[PrivacyRegion]) -> dict:
    return {
        "privacy_verified": True,
        "regions": [r.to_dict() for r in regions],
    }


def verification_failure(message: str) -> dict:
    return {
        "privacy_verified": False,
        "error": ErrorDetail("PRIVACY_VERIFICATION_FAILED", message).to_dict(),
    }
