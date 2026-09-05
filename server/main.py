"""
server/main.py

Backend / VLM stage of the pipeline.

Responsibilities:
    - Accept only sanitized context from the extension.
    - Reject any request where privacy_verified is false.
    - Return a single structured action (click/type/scroll/wait).

The VLM boundary currently selects the safe rule-based fallback from
vlm.py. A future local provider can implement that boundary without
changing this file's API contract.

Run locally:
    pip install -r requirements.txt
    uvicorn main:app --reload
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from reasoning import ActionInferenceError, TargetNotFoundError
from schemas import BackendRequest, BackendResponse, error_response
from vlm import VLMError, infer_action


app = FastAPI(title="Privacy-Preserving AI Browser Agent - Backend")


# Permissive CORS so the integration demo can call this server.
# This is NOT safe for a real deployment -- tighten allow_origins
# before shipping anything beyond this local demo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=400,
        content=error_response(
            "INVALID_REQUEST",
            "Request did not match the expected schema.",
        ),
    )


@app.post("/api/v1/action")
async def get_action(payload: BackendRequest):
    """Convert verified sanitized context into one structured action."""

    if not payload.privacy_verified:
        return JSONResponse(
            status_code=400,
            content=error_response(
                "INVALID_REQUEST",
                "Request rejected: privacy_verified is false. "
                "The screenshot/context must not be sent to the server "
                "unless privacy verification succeeded.",
            ),
        )

    try:
        action = infer_action(
            payload.instruction,
            payload.elements,
            payload.image,
            payload.privacy_regions,
        )

    except TargetNotFoundError as exc:
        return JSONResponse(
            status_code=404,
            content=error_response(
                "TARGET_NOT_FOUND",
                str(exc),
            ),
        )

    except ActionInferenceError as exc:
        return JSONResponse(
            status_code=400,
            content=error_response(
                "INVALID_REQUEST",
                str(exc),
            ),
        )

    except VLMError as exc:
        return JSONResponse(
            status_code=500,
            content=error_response(
                "VISION_INFERENCE_FAILED",
                str(exc),
            ),
        )

    except Exception:  # pragma: no cover - defensive fallback
        return JSONResponse(
            status_code=500,
            content=error_response(
                "SERVER_ERROR",
                "Unexpected error while inferring an action.",
            ),
        )

    response = BackendResponse(
        request_id=payload.request_id,
        action=action,
    )

    return response.model_dump()


@app.get("/health")
async def health():
    """Simple liveness check for local development and monitoring."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# DEMO-ONLY integration endpoint
# ---------------------------------------------------------------------------
# Wraps the real /privacy detector so demo/index.html can show actual PII
# detection running end-to-end, not a mocked result.
#
# This does not replace or change /api/v1/action;
# it is purely additive for the integration demo.
#
# NOTE:
# /server and /privacy each have their own schemas.py.
# A plain sys.path insert could cause privacy/detector.py's
# "from schemas import ..." to resolve to this server's schemas.py.
#
# Therefore, privacy's files are loaded by explicit file path and
# sys.modules["schemas"] is temporarily swapped while detector.py loads.


_detect_pii_in_text = None
_PRIVACY_MODULE_AVAILABLE = False


def _load_privacy_detector():
    global _detect_pii_in_text, _PRIVACY_MODULE_AVAILABLE

    privacy_dir = (
        pathlib.Path(__file__).resolve().parent.parent / "privacy"
    )

    schemas_path = privacy_dir / "schemas.py"
    detector_path = privacy_dir / "detector.py"

    if not schemas_path.exists() or not detector_path.exists():
        return

    schemas_spec = importlib.util.spec_from_file_location(
        "privacy_schemas_demo",
        schemas_path,
    )

    privacy_schemas = importlib.util.module_from_spec(schemas_spec)

    if schemas_spec.loader is None:
        return

    schemas_spec.loader.exec_module(privacy_schemas)

    previous_schemas_module = sys.modules.get("schemas")

    sys.modules["schemas"] = privacy_schemas

    try:
        detector_spec = importlib.util.spec_from_file_location(
            "privacy_detector_demo",
            detector_path,
        )

        privacy_detector = importlib.util.module_from_spec(detector_spec)

        if detector_spec.loader is None:
            return

        detector_spec.loader.exec_module(privacy_detector)

    finally:
        # Restore whatever "schemas" pointed to before.
        if previous_schemas_module is not None:
            sys.modules["schemas"] = previous_schemas_module
        else:
            sys.modules.pop("schemas", None)

    _detect_pii_in_text = privacy_detector.detect_pii_in_text
    _PRIVACY_MODULE_AVAILABLE = True


try:
    _load_privacy_detector()
except Exception:
    _PRIVACY_MODULE_AVAILABLE = False


class PrivacyCheckRequest(BaseModel):
    text: str


@app.post("/api/v1/privacy-check")
async def privacy_check(payload: PrivacyCheckRequest):
    """
    DEMO-ONLY: run the real privacy/detector.py over page text.

    Not part of the main API contract. Added purely so the integration
    demo can show real PII detection triggered from the browser.
    """

    if not _PRIVACY_MODULE_AVAILABLE:
        return JSONResponse(
            status_code=500,
            content=error_response(
                "SERVER_ERROR",
                "The /privacy module was not found alongside /server. "
                "See demo/README.md for the required folder layout.",
            ),
        )

    return _detect_pii_in_text(payload.text)