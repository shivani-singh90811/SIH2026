"""
privacy/redactor.py

Stage 2 of the privacy pipeline (docs/api.md sections 1.3 / 18):
    Detection -> Redaction -> Verification -> Transmission

Applies the redaction technique assigned to each PrivacyRegion (black,
blur, mask -- docs/api.md section 5) directly on image pixels, using
Pillow. Runs entirely on-device; never sends image bytes anywhere and
never logs pixel data or the sensitive text a region represents (this
module never even sees the sensitive text -- only its bbox and type).

Input images are treated as opaque byte blobs (e.g. a PNG screenshot
captured by the extension), so this module has no dependency on the
browser extension, the vision module, or any specific capture format
beyond "something Pillow can open".
"""

from __future__ import annotations

import io
from typing import Iterable

from PIL import Image, ImageFilter

try:
    from .schemas import BBox, PrivacyRegion
except ImportError:  # pragma: no cover - allows `python redactor.py` standalone
    from schemas import BBox, PrivacyRegion


class RedactionError(Exception):
    """Raised when an image or region cannot be processed for redaction.

    Callers (e.g. a pipeline runner) should catch this and treat it as
    a failed pipeline run -- per docs/api.md section 6, nothing should
    be transmitted unless verification later reports success, and a
    redaction failure can never lead to a successful verification.
    """


def _clamp_bbox(bbox: BBox, width: int, height: int) -> BBox:
    """Validate and clamp a region's bbox to the image bounds.

    Fails closed: a region whose bbox has zero/negative area (schemas.py
    permits x2 == x1 or y2 == y1) or that lies entirely outside the
    image bounds cannot be safely redacted, and is never silently
    skipped. Instead this raises RedactionError so the pipeline stops
    and nothing gets transmitted (docs/api.md section 6).

    Raises:
        RedactionError: if the bbox has no area, either before or
            after clamping to the image bounds.
    """
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        raise RedactionError(
            f"Region bbox {bbox} has zero or negative area; cannot redact safely."
        )

    clamped_x1 = max(0, min(x1, width))
    clamped_y1 = max(0, min(y1, height))
    clamped_x2 = max(0, min(x2, width))
    clamped_y2 = max(0, min(y2, height))

    if clamped_x2 <= clamped_x1 or clamped_y2 <= clamped_y1:
        raise RedactionError(
            f"Region bbox {bbox} lies outside the image bounds "
            f"({width}x{height}); cannot redact safely."
        )

    return (clamped_x1, clamped_y1, clamped_x2, clamped_y2)


def _apply_black(image: Image.Image, bbox: BBox) -> None:
    x1, y1, x2, y2 = bbox
    black_box = Image.new("RGB", (x2 - x1, y2 - y1), (0, 0, 0))
    image.paste(black_box, (x1, y1))


def _apply_blur(image: Image.Image, bbox: BBox) -> None:
    x1, y1, x2, y2 = bbox
    region = image.crop((x1, y1, x2, y2))
    # Blur radius scales with region size so small crops (e.g. an
    # OTP-sized box) are still fully obscured, not just softened.
    radius = max(6, min(x2 - x1, y2 - y1) // 2)
    blurred = region.filter(ImageFilter.GaussianBlur(radius=radius))
    image.paste(blurred, (x1, y1))


# Minimum fraction of a masked region's width that must always be
# blacked out, regardless of how the nominal edge margin below works
# out. Without this floor, a small bbox (short OTP/date-shaped value
# in a tight crop) could end up with most or nearly all of its width
# left visible -- effectively exposing the complete sensitive value
# through what was supposed to be a partial mask.
_MASK_MIN_BLACKED_FRACTION = 0.6


def _apply_mask(image: Image.Image, bbox: BBox) -> None:
    """Partially obscure: black out the middle, leave small edge strips.

    Used where partial visibility is acceptable (docs/api.md section
    5) -- e.g. an email or phone number, where keeping a sliver visible
    at each end can help a user recognize *which* value it is without
    exposing the whole thing.

    The nominal margin (~1/6 of the width on each side) is capped so
    that at least `_MASK_MIN_BLACKED_FRACTION` of the width is always
    blacked out -- this stops small/narrow regions from having most of
    their content left exposed, which would defeat the point of
    masking. If even that can't be honored (a degenerate, near-zero
    width region), the whole bbox is fully blacked instead of leaving
    it exposed.
    """
    x1, y1, x2, y2 = bbox
    width = x2 - x1

    nominal_margin = max(2, width // 6)  # roughly 1/6 visible on each side
    max_safe_margin = int(width * (1 - _MASK_MIN_BLACKED_FRACTION) // 2)
    margin = min(nominal_margin, max_safe_margin)

    inner_x1 = x1 + margin
    inner_x2 = x2 - margin
    if inner_x2 <= inner_x1:
        # Region too small (or too safety-constrained) to partially
        # mask meaningfully -- fully black it out rather than leave
        # most/all of it exposed.
        _apply_black(image, bbox)
        return
    _apply_black(image, (inner_x1, y1, inner_x2, y2))


_REDACTORS = {
    "black": _apply_black,
    "blur": _apply_blur,
    "mask": _apply_mask,
}


def redact_image(image_bytes: bytes, regions: Iterable[PrivacyRegion]) -> bytes:
    """Apply redaction to every region and return new image bytes.

    Args:
        image_bytes: raw bytes of the source screenshot (PNG/JPEG/etc).
        regions: PrivacyRegion objects from detector.py, each carrying
            its own `redaction` technique.

    Returns:
        PNG-encoded bytes of the redacted image.

    Raises:
        RedactionError: if the image cannot be decoded, a region
            specifies an unrecognized redaction technique, or a
            region's bbox has no area (either as given, or after
            clamping to the image bounds). This module fails closed:
            a region that cannot be safely redacted stops the whole
            call rather than being silently skipped, so the pipeline
            runner can prevent transmission (docs/api.md section 6).
    """
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise RedactionError("Could not decode image for redaction.") from exc

    width, height = image.size

    for region in regions:
        technique = _REDACTORS.get(region.redaction)
        if technique is None:
            raise RedactionError(f"Unknown redaction technique: {region.redaction!r}")
        bbox = _clamp_bbox(region.bbox, width, height)
        technique(image, bbox)

    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
