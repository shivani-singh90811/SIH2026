"""
privacy/verifier.py

Stage 3 of the privacy pipeline (docs/api.md sections 1.3 / 18):
    Detection -> Redaction -> Verification -> Transmission

Confirms redaction actually took visible effect before the extension
is allowed to transmit anything (docs/api.md section 6). This is a
lightweight, on-device pixel-level sanity check -- it does NOT re-run
OCR/vision to prove the underlying text is unreadable (that overlaps
with /vision, a separate module and separate concern). It checks that
each region's assigned technique measurably changed the image inside
that bbox, which catches the common failure modes (a region silently
skipped, a wrong bbox, a redaction step that raised partway through)
without ever inspecting or logging the original sensitive content --
this module only ever looks at pixel statistics, never text.
"""

from __future__ import annotations

import io
from typing import Iterable

from PIL import Image, ImageStat

try:
    from .schemas import PrivacyRegion, verification_failure, verification_success
except ImportError:  # pragma: no cover - allows `python verifier.py` standalone
    from schemas import PrivacyRegion, verification_failure, verification_success

# Thresholds are intentionally conservative for the MVP -- see README
# for exactly what this check does and does not guarantee.
_BLACK_MAX_MEAN_BRIGHTNESS = 20.0  # out of 255, per RGB channel
_BLUR_MIN_VARIANCE_DROP_RATIO = 0.35  # required drop in pixel stddev
_MASK_MIN_CHANGED_FRACTION = 0.15  # fraction of pixels that must differ


def _crop_or_raise(image: Image.Image, bbox) -> Image.Image:
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        raise ValueError("bbox has no area")
    return image.crop((x1, y1, x2, y2))


def _check_black(original: Image.Image, redacted: Image.Image, bbox) -> bool:
    stat = ImageStat.Stat(_crop_or_raise(redacted, bbox))
    return max(stat.mean) <= _BLACK_MAX_MEAN_BRIGHTNESS


def _check_blur(original: Image.Image, redacted: Image.Image, bbox) -> bool:
    orig_stat = ImageStat.Stat(_crop_or_raise(original, bbox))
    red_stat = ImageStat.Stat(_crop_or_raise(redacted, bbox))
    orig_variance = sum(orig_stat.stddev) or 1e-6
    red_variance = sum(red_stat.stddev)
    return (red_variance / orig_variance) <= (1 - _BLUR_MIN_VARIANCE_DROP_RATIO)


def _check_mask(original: Image.Image, redacted: Image.Image, bbox) -> bool:
    orig_crop = _crop_or_raise(original, bbox)
    red_crop = _crop_or_raise(redacted, bbox)
    if orig_crop.size != red_crop.size:
        return False
    total_pixels = orig_crop.size[0] * orig_crop.size[1]
    if total_pixels == 0:
        return False
    diff_pixels = sum(1 for a, b in zip(orig_crop.getdata(), red_crop.getdata()) if a != b)
    return (diff_pixels / total_pixels) >= _MASK_MIN_CHANGED_FRACTION


_CHECKS = {
    "black": _check_black,
    "blur": _check_blur,
    "mask": _check_mask,
}


def verify_redaction(
    original_image_bytes: bytes,
    redacted_image_bytes: bytes,
    regions: Iterable[PrivacyRegion],
) -> dict:
    """Verify every region was actually redacted in the output image.

    Returns:
        On success, docs/api.md section 6 shape:
            {"privacy_verified": true, "regions": [...]}
        On failure (bad images, size mismatch, or any region that does
        not appear redacted):
            {"privacy_verified": false, "error": {"code": "PRIVACY_VERIFICATION_FAILED", ...}}

    Never raises: any internal problem is reported as
    privacy_verified=false so the caller's "do not transmit on
    failure" rule (docs/api.md section 6) has one JSON signal to check.
    """
    try:
        original = Image.open(io.BytesIO(original_image_bytes)).convert("RGB")
        redacted = Image.open(io.BytesIO(redacted_image_bytes)).convert("RGB")
    except Exception:
        return verification_failure("Could not decode image(s) for verification.")

    if original.size != redacted.size:
        return verification_failure("Redacted image dimensions do not match the original.")

    regions = list(regions)
    for region in regions:
        check = _CHECKS.get(region.redaction)
        if check is None:
            return verification_failure(f"Unknown redaction technique: {region.redaction!r}")
        try:
            passed = check(original, redacted, region.bbox)
        except ValueError:
            # Degenerate/empty bbox -- treat as failure rather than
            # silently skipping a region that was supposed to be
            # protected.
            passed = False
        if not passed:
            return verification_failure(
                f"Region {region.id} ({region.type}) does not appear to be redacted."
            )

    return verification_success(regions)
