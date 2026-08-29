
# Privacy / PII Module

On-device privacy pipeline for the browser agent, per `docs/api.md`:

```
Detection → Redaction → Verification → Transmission
```

This module implements the first three stages, locally, with no
network calls. **Transmission is out of scope for this module** — the
extension (or whatever calls this module) is responsible for deciding
what to do with `privacy_verified` before sending anything to
`/server`.

## Files

| File | Stage | Responsibility |
|---|---|---|
| `schemas.py` | — | Shared data contracts: `TextRegion`, `PrivacyRegion`, error/verification response shapes. Matches `docs/api.md` sections 1, 4, 5, 6, 15, 16. |
| `detector.py` | Detection | Finds PII in OCR-style text regions, returns `{"regions": [...]}`. |
| `redactor.py` | Redaction | Applies `black` / `blur` / `mask` to an image, per-region, using Pillow. |
| `verifier.py` | Verification | Pixel-level check that redaction actually took effect; returns `{"privacy_verified": ...}`. |
| `requirements.txt` | — | Just `Pillow` — no other dependencies. |

No file here touches `/extension`, `/vision`, `/server`, `/agent`, or
`/tests`.

## Supported PII types (MVP)

`email`, `phone`, `otp`, `pan`, `aadhaar`, `credit_card`, `debit_card`
(reported as `credit_card` for now — see Limitations), `password`,
`cvv`, `account_number`, `date_of_birth`.

Each type has a default redaction technique assigned at detection time
(`schemas.DEFAULT_REDACTION_FOR_TYPE`):

- **black** — password, otp, cvv, pan, aadhaar, credit_card,
  debit_card, account_number (fully sensitive, must not remain visible)
- **mask** — email, phone, date_of_birth (partial visibility is
  acceptable per `docs/api.md` section 5)

## How the pipeline fits together

```python
from detector import detect_pii
from schemas import TextRegion, PrivacyRegion
from redactor import redact_image
from verifier import verify_redaction

# 1. Detection — input comes from OCR (the vision module) as
#    text + bounding box pairs.
regions = [
    TextRegion(text="Contact: user@example.com", bbox=(10, 10, 390, 40)),
    TextRegion(text="OTP is 483920, do not share", bbox=(10, 60, 390, 90)),
]
detection_result = detect_pii(regions)
# -> {"regions": [{"id": "privacy_001", "type": "email", "bbox": [...],
#                   "redaction": "mask", "confidence": 0.95}, ...]}

if "error" in detection_result:
    # detection_result["error"]["code"] is one of the shared error
    # codes from docs/api.md section 16 — stop here, do not transmit.
    ...

region_objs = [
    PrivacyRegion(id=r["id"], type=r["type"], bbox=tuple(r["bbox"]),
                  redaction=r["redaction"], confidence=r["confidence"])
    for r in detection_result["regions"]
]

# 2. Redaction — operates on the actual screenshot bytes.
redacted_bytes = redact_image(original_screenshot_bytes, region_objs)

# 3. Verification — must pass before anything is transmitted.
verification_result = verify_redaction(
    original_screenshot_bytes, redacted_bytes, region_objs
)
if verification_result["privacy_verified"]:
    # safe to hand `redacted_bytes` + sanitized context to the extension
    # for transmission (docs/api.md sections 7-8)
    ...
else:
    # docs/api.md section 6: "The screenshot must NOT be sent to the server."
    ...
```

## Running a local test

No test framework is required to sanity-check the module — Pillow is
the only dependency.

```bash
cd privacy
pip install -r requirements.txt
python3 detector.py     # runs the built-in detection smoke test
```

For a full pipeline check (detection → redaction → verification) with
no real screenshot needed, run this from inside `privacy/`:

```bash
python3 - <<'EOF'
from PIL import Image
import io
from detector import detect_pii
from schemas import TextRegion, PrivacyRegion
from redactor import redact_image
from verifier import verify_redaction

# A blank stand-in screenshot is enough: detection runs on OCR-style
# TextRegion objects (text + bbox), not on rendered pixels, so we don't
# need real rendered text in the image for this check.
img = Image.new("RGB", (400, 150), (255, 255, 255))
buf = io.BytesIO()
img.save(buf, format="PNG")
original_bytes = buf.getvalue()

regions = [
    TextRegion(text="Contact: user@example.com", bbox=(10, 10, 390, 40)),
    TextRegion(text="OTP is 483920, do not share", bbox=(10, 60, 390, 90)),
]

detection_result = detect_pii(regions)
print("DETECTION:", detection_result)

region_objs = [
    PrivacyRegion(id=r["id"], type=r["type"], bbox=tuple(r["bbox"]),
                  redaction=r["redaction"], confidence=r["confidence"])
    for r in detection_result["regions"]
]

redacted_bytes = redact_image(original_bytes, region_objs)
verification_result = verify_redaction(original_bytes, redacted_bytes, region_objs)
print("VERIFICATION:", verification_result)
EOF
```

Expected output: a `regions` list with `email` (mask) and `otp`
(black), and `{"privacy_verified": true, ...}`.

To see the failure path, skip the redaction step and call
`verify_redaction(original_bytes, original_bytes, region_objs)` instead
— it should return `{"privacy_verified": false, "error": {"code":
"PRIVACY_VERIFICATION_FAILED", ...}}`.

## Error handling

All public functions (`detect_pii`, `detect_pii_in_text`,
`verify_redaction`) return **structured JSON dicts** rather than
raising on expected failure paths (bad input, undecodable image,
failed redaction check), using only error codes already defined in
`docs/api.md` section 16 (`INVALID_REQUEST`,
`PRIVACY_DETECTION_FAILED`, `PRIVACY_VERIFICATION_FAILED`).

`redact_image` is the one exception: it raises `RedactionError` on
failure, since redaction happens strictly *before* verification in the
pipeline — any redaction failure should be caught by the pipeline
runner and treated as an automatic verification failure (nothing gets
transmitted either way).

## Security notes

- No detected value is ever stored in a `PrivacyRegion`, logged, or
  printed — only `id`, `type`, `bbox`, `redaction`, and `confidence`.
- `redactor.py` and `verifier.py` never see the original text at all —
  they only work with image bytes and bounding boxes.
- Nothing in this module makes a network call.
- Error messages never echo back raw input text.

## Limitations (MVP)

- **Regex/rule-based detection is not exhaustive.** It will miss
  obfuscated, handwritten, or non-standard-format PII, and free-form
  values like passwords are inherently hard to detect without fixed
  structure — the `password` rule here only fires next to a
  `password:`/`pwd:`-style label.
- **debit_card vs credit_card**: both are reported as `credit_card`.
  Telling them apart reliably needs the BIN/network range or an
  on-screen label, which is future work.
- **Bounding boxes from `detector.py` are approximate.** Without real
  OCR character-level boxes, character offsets are linearly
  interpolated across the region's width (assumes roughly uniform,
  single-line text). A minimum box size is enforced so short matches
  (e.g. an OTP) don't collapse to a zero-area box.
- **Verification is a pixel-statistics sanity check, not a proof of
  unreadability.** It confirms brightness dropped enough for `black`,
  variance dropped enough for `blur`, and enough pixels changed for
  `mask` — it does not re-run OCR to prove text is actually
  unrecoverable. A full guarantee would require the vision module to
  re-scan the redacted image, which is out of this module's scope.
- **No ML/OCR model is included.** `detector.py` is structured so a
  future classifier can be added as another rule source without
  changing `detect_pii()`'s signature or output shape.
