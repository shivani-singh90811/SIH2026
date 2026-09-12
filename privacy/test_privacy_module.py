"""
privacy/test_privacy_module.py

Module-level tests for the /privacy module (detector.py, redactor.py,
verifier.py, schemas.py). Uses only the standard library's `unittest`,
so no new dependency is needed beyond Pillow (already required by the
module itself).

Run with:
    cd privacy
    python3 -m unittest test_privacy_module.py -v

These are intentionally self-contained: every test builds its own
input (synthetic images, hand-written TextRegions) so the module can
be tested in isolation, without the extension, vision, server, or
agent modules.
"""

from __future__ import annotations

import io
import unittest

from PIL import Image

from detector import detect_pii, detect_pii_in_text
from redactor import RedactionError, redact_image
from schemas import PrivacyRegion, TextRegion
from verifier import verify_redaction


def _blank_image_bytes(width: int = 400, height: int = 150) -> bytes:
    """A plain white PNG, used as a stand-in screenshot in tests."""
    image = Image.new("RGB", (width, height), (255, 255, 255))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Detection stage
# ---------------------------------------------------------------------------

class TestDetector(unittest.TestCase):
    def test_email_is_detected_with_mask_redaction(self):
        result = detect_pii_in_text("Contact me at user@example.com")
        regions = result["regions"]
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["type"], "email")
        self.assertEqual(regions[0]["redaction"], "mask")
        self.assertTrue(0.0 <= regions[0]["confidence"] <= 1.0)

    def test_otp_requires_nearby_keyword(self):
        # A bare 6-digit number with no context must NOT be flagged.
        no_context = detect_pii_in_text("the meeting room number is 483920")
        self.assertEqual(no_context["regions"], [])

        with_context = detect_pii_in_text("your OTP is 483920, do not share")
        types = [r["type"] for r in with_context["regions"]]
        self.assertIn("otp", types)

    def test_account_number_requires_nearby_keyword(self):
        # Regression test: a bare 9-18 digit run must not be flagged as
        # account_number without a nearby keyword (previously a false
        # positive source). Uses a 14-digit number to avoid the
        # separate, documented overlap with the bare 12-digit Aadhaar
        # pattern (see README "Limitations").
        no_context = detect_pii_in_text("invoice id 12345678901234")
        types = [r["type"] for r in no_context["regions"]]
        self.assertNotIn("account_number", types)

        with_context = detect_pii_in_text("account no 12345678901234")
        types = [r["type"] for r in with_context["regions"]]
        self.assertIn("account_number", types)

    def test_credit_card_requires_luhn_validity(self):
        valid = detect_pii_in_text("Card number 4111111111111111")
        types = [r["type"] for r in valid["regions"]]
        self.assertIn("credit_card", types)

        invalid = detect_pii_in_text("Card number 1234567890123456")
        types = [r["type"] for r in invalid["regions"]]
        self.assertNotIn("credit_card", types)

    def test_no_raw_value_in_output(self):
        result = detect_pii_in_text("card 4111111111111111, otp is 483920")
        self.assertNotIn("4111111111111111", str(result))
        self.assertNotIn("483920", str(result))

    def test_bbox_never_degenerates_to_zero_width(self):
        region = TextRegion(text="otp 4839", bbox=(100, 200, 108, 212))
        result = detect_pii([region])
        for r in result["regions"]:
            x1, y1, x2, y2 = r["bbox"]
            self.assertGreater(x2, x1)
            self.assertGreater(y2, y1)

    def test_invalid_input_returns_structured_error_not_exception(self):
        result = detect_pii("not a list")  # type: ignore[arg-type]
        self.assertEqual(result["success"], False)
        self.assertEqual(result["error"]["code"], "INVALID_REQUEST")

        result2 = detect_pii_in_text(12345)  # type: ignore[arg-type]
        self.assertEqual(result2["success"], False)
        self.assertEqual(result2["error"]["code"], "INVALID_REQUEST")


# ---------------------------------------------------------------------------
# Redaction stage
# ---------------------------------------------------------------------------

class TestRedactor(unittest.TestCase):
    def setUp(self):
        self.image_bytes = _blank_image_bytes()

    def test_black_redaction_blackens_region(self):
        region = PrivacyRegion(
            id="privacy_001", type="otp", bbox=(10, 10, 100, 40),
            redaction="black", confidence=0.9,
        )
        redacted_bytes = redact_image(self.image_bytes, [region])
        img = Image.open(io.BytesIO(redacted_bytes)).convert("RGB")
        pixel = img.getpixel((50, 25))
        self.assertEqual(pixel, (0, 0, 0))

    def test_mask_does_not_leave_majority_exposed_on_small_bbox(self):
        # Regression test for the mask-exposure fix: a narrow bbox must
        # still have the majority of its area blacked out.
        region = PrivacyRegion(
            id="privacy_002", type="email", bbox=(0, 0, 6, 20),
            redaction="mask", confidence=0.9,
        )
        redacted_bytes = redact_image(self.image_bytes, [region])
        img = Image.open(io.BytesIO(redacted_bytes)).convert("RGB")
        crop = img.crop((0, 0, 6, 20))
        pixels = list(crop.getdata())
        black_fraction = sum(1 for p in pixels if p == (0, 0, 0)) / len(pixels)
        self.assertGreaterEqual(black_fraction, 0.5)

    def test_zero_area_bbox_fails_closed(self):
        region = PrivacyRegion(
            id="privacy_003", type="otp", bbox=(50, 50, 50, 80),
            redaction="black", confidence=0.9,
        )
        with self.assertRaises(RedactionError):
            redact_image(self.image_bytes, [region])

    def test_out_of_bounds_bbox_fails_closed(self):
        region = PrivacyRegion(
            id="privacy_004", type="otp", bbox=(500, 500, 600, 600),
            redaction="black", confidence=0.9,
        )
        with self.assertRaises(RedactionError):
            redact_image(self.image_bytes, [region])

    def test_unknown_redaction_technique_raises(self):
        region = PrivacyRegion(
            id="privacy_005", type="email", bbox=(10, 10, 100, 40),
            redaction="black", confidence=0.9,
        )
        object.__setattr__(region, "redaction", "shred")
        with self.assertRaises(RedactionError):
            redact_image(self.image_bytes, [region])

    def test_corrupt_image_raises(self):
        region = PrivacyRegion(
            id="privacy_006", type="otp", bbox=(10, 10, 40, 40),
            redaction="black", confidence=0.9,
        )
        with self.assertRaises(RedactionError):
            redact_image(b"not-an-image", [region])


# ---------------------------------------------------------------------------
# Verification stage
# ---------------------------------------------------------------------------

class TestVerifier(unittest.TestCase):
    def setUp(self):
        self.image_bytes = _blank_image_bytes()

    def test_full_pipeline_passes_verification(self):
        regions = [
            PrivacyRegion(id="privacy_001", type="email", bbox=(10, 10, 200, 40), redaction="mask", confidence=0.9),
            PrivacyRegion(id="privacy_002", type="otp", bbox=(10, 60, 100, 90), redaction="black", confidence=0.9),
        ]
        redacted_bytes = redact_image(self.image_bytes, regions)
        result = verify_redaction(self.image_bytes, redacted_bytes, regions)
        self.assertTrue(result["privacy_verified"])
        self.assertEqual(len(result["regions"]), 2)

    def test_unredacted_region_fails_verification(self):
        region = PrivacyRegion(
            id="privacy_001", type="otp", bbox=(10, 10, 100, 40),
            redaction="black", confidence=0.9,
        )
        # Pretend redaction never happened.
        result = verify_redaction(self.image_bytes, self.image_bytes, [region])
        self.assertFalse(result["privacy_verified"])
        self.assertEqual(result["error"]["code"], "PRIVACY_VERIFICATION_FAILED")

    def test_corrupt_image_fails_verification_not_exception(self):
        region = PrivacyRegion(
            id="privacy_001", type="otp", bbox=(10, 10, 40, 40),
            redaction="black", confidence=0.9,
        )
        result = verify_redaction(b"not-an-image", b"not-an-image", [region])
        self.assertFalse(result["privacy_verified"])
        self.assertEqual(result["error"]["code"], "PRIVACY_VERIFICATION_FAILED")

    def test_mismatched_dimensions_fail_verification(self):
        region = PrivacyRegion(
            id="privacy_001", type="otp", bbox=(10, 10, 40, 40),
            redaction="black", confidence=0.9,
        )
        smaller_image = _blank_image_bytes(width=100, height=50)
        result = verify_redaction(self.image_bytes, smaller_image, [region])
        self.assertFalse(result["privacy_verified"])


if __name__ == "__main__":
    unittest.main()