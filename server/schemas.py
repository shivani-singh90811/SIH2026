"""
server/schemas.py

Request/response contracts for the backend API.

The optional `instruction` field carries the user's natural-language
request to the reasoning layer. Existing request fields remain unchanged.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared request building blocks
# ---------------------------------------------------------------------------

BBox = tuple[int, int, int, int]  # [x1, y1, x2, y2]

ElementType = Literal[
    "button", "input", "textarea", "select", "link",
    "checkbox", "radio", "image", "heading", "text", "form", "other",
]


class Element(BaseModel):
    id: str
    type: ElementType
    label: Optional[str] = None
    bbox: BBox
    visible: bool = True
    interactive: bool = True


PIIType = Literal[
    "password", "email", "phone", "otp", "pin", "cvv", "credit_card",
    "debit_card", "aadhaar", "pan", "passport", "driving_license",
    "account_number", "date_of_birth", "face", "personal_text", "other",
]

RedactionType = Literal["black", "blur", "mask"]


class PrivacyRegionSummary(BaseModel):
    """Sanitized region metadata without confidence or raw values."""

    type: PIIType
    bbox: BBox
    redaction: RedactionType


class ScreenSize(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


# ---------------------------------------------------------------------------
# Backend request
# ---------------------------------------------------------------------------

class BackendRequest(BaseModel):
    request_id: str
    privacy_verified: bool
    screen: ScreenSize
    elements: list[Element] = []
    privacy_regions: list[PrivacyRegionSummary] = []
    image: Optional[str] = None  # opaque sanitized image; unused by fallback reasoning

    # Additive field -- see module docstring. Optional so a strictly
    # contract-shaped request still validates; without it the stub
    # cannot infer any action and returns TARGET_NOT_FOUND.
    instruction: Optional[str] = None


# ---------------------------------------------------------------------------
# Supported actions
# ---------------------------------------------------------------------------

class ClickAction(BaseModel):
    type: Literal["click"] = "click"
    target: str


class TypeAction(BaseModel):
    type: Literal["type"] = "type"
    target: str
    value: str


class ScrollAction(BaseModel):
    type: Literal["scroll"] = "scroll"
    direction: Literal["up", "down", "left", "right"]
    amount: int = Field(gt=0)


class WaitAction(BaseModel):
    type: Literal["wait"] = "wait"
    duration: int = Field(gt=0)  # milliseconds


Action = ClickAction | TypeAction | ScrollAction | WaitAction


# ---------------------------------------------------------------------------
# Backend response
# ---------------------------------------------------------------------------

class BackendResponse(BaseModel):
    request_id: str
    success: Literal[True] = True
    action: Action


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

ErrorCode = Literal[
    "MODEL_LOAD_FAILED",
    "VISION_INFERENCE_FAILED",
    "PRIVACY_DETECTION_FAILED",
    "PRIVACY_VERIFICATION_FAILED",
    "INVALID_REQUEST",
    "INVALID_ACTION",
    "TARGET_NOT_FOUND",
    "ACTION_EXECUTION_FAILED",
    "NETWORK_ERROR",
    "SERVER_ERROR",
]


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorDetail


def error_response(code: ErrorCode, message: str) -> dict:
    return ErrorResponse(error=ErrorDetail(code=code, message=message)).model_dump()