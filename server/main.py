"""
server/main.py

Backend / VLM stage of the pipeline (docs/api.md sections 8, 9, 18-19).

Responsibilities per docs/api.md section 20 ("Backend / VLM -> /server
-> Sanitized data processing and AI reasoning"):
    - Accept only sanitized context from the extension (never raw
      screenshots or sensitive values).
    - Reject any request where privacy_verified is false.
    - Return a single structured action (click/type/scroll/wait).

No proprietary AI API is called here -- action inference is a small
rule-based matcher (reasoning.py) standing in for a real local/VLM
model, so the module is runnable and testable today without any API
key or network dependency. Swapping in a real model later only means
changing `infer_action()`'s implementation, not this file's contract
surface.

Run locally:
    pip install -r requirements.txt
    uvicorn main:app --reload
"""

from __future__ import annotations

import pathlib
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from reasoning import ActionInferenceError, TargetNotFoundError, infer_action
from schemas import BackendRequest, BackendResponse, error_response

app = FastAPI(title="Privacy-Preserving AI Browser Agent - Backend (MVP stub)")

# Permissive CORS so the integration demo (demo/index.html, opened
# directly in a browser or served from a different local port) can
# call this server. This is NOT safe for a real deployment -- tighten
# `allow_origins` before shipping anything beyond this local demo.
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
        content=error_response("INVALID_REQUEST", "Request did not match the expected schema."),
    )


@app.post("/api/v1/action")
async def get_action(payload: BackendRequest):
    """Main entry point: sanitized context in, a structured action out.

    Mirrors docs/api.md sections 8 (request) and 9 (response). See
    schemas.py for the exact field-level contract.
    """
    # docs/api.md section 8: "The backend must reject requests where
    # privacy_verified is false."
    if not payload.privacy_verified:
        return JSONResponse(
            status_code=400,
            content=error_response(
                "INVALID_REQUEST",
                "Request rejected: privacy_verified is false. "
                "The screenshot/context must not be sent to the server "
                "unless privacy verification succeeded (docs/api.md section 6).",
            ),
        )

    try:
        action = infer_action(payload.instruction, payload.elements)
    except TargetNotFoundError as exc:
        return JSONResponse(
            status_code=404,
            content=error_response("TARGET_NOT_FOUND", str(exc)),
        )
    except ActionInferenceError as exc:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_REQUEST", str(exc)),
        )
    except Exception:  # pragma: no cover - defensive fallback
        return JSONResponse(
            status_code=500,
            content=error_response("SERVER_ERROR", "Unexpected error while inferring an action."),
        )

    response = BackendResponse(request_id=payload.request_id, action=action)
    return response.model_dump()


@app.get("/health")
async def health():
    """Simple liveness check -- not part of docs/api.md, just for local dev."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# DEMO-ONLY integration endpoint (not part of docs/api.md)
# ---------------------------------------------------------------------------
# Wraps the real /privacy detector so demo/index.html can show actual PII
# detection running end-to-end, not a mocked result. Requires the
# /privacy folder to be present as a sibling directory of /server --
# see demo/README.md. This does not replace or change /api/v1/action;
# it is purely additive for the integration demo.
#
# NOTE: /server and /privacy each have their own schemas.py. A plain
# `sys.path` insert would make privacy/detector.py's fallback
# `from schemas import ...` resolve to THIS server's schemas.py
# (already cached in sys.modules under the name "schemas"), not
# privacy's -- silently pulling in the wrong module. We load privacy's
# files by explicit file path instead, and only swap sys.modules
# briefly while detector.py's own import line runs.

import importlib.util

_detect_pii_in_text = None
_PRIVACY_MODULE_AVAILABLE = False


def _load_privacy_detector():
    global _detect_pii_in_text, _PRIVACY_MODULE_AVAILABLE

    privacy_dir = pathlib.Path(__file__).resolve().parent.parent / "privacy"
    schemas_path = privacy_dir / "schemas.py"
    detector_path = privacy_dir / "detector.py"
    if not schemas_path.exists() or not detector_path.exists():
        return  # /privacy not present alongside /server -- see demo/README.md

    schemas_spec = importlib.util.spec_from_file_location("privacy_schemas_demo", schemas_path)
    privacy_schemas = importlib.util.module_from_spec(schemas_spec)
    schemas_spec.loader.exec_module(privacy_schemas)

    previous_schemas_module = sys.modules.get("schemas")
    sys.modules["schemas"] = privacy_schemas
    try:
        detector_spec = importlib.util.spec_from_file_location("privacy_detector_demo", detector_path)
        privacy_detector = importlib.util.module_from_spec(detector_spec)
        detector_spec.loader.exec_module(privacy_detector)
    finally:
        # Restore whatever "schemas" pointed to before, so nothing else
        # in this process is affected by the temporary swap.
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
    """DEMO-ONLY: run the real privacy/detector.py over page text.

    Not part of docs/api.md -- added purely so the integration demo can
    show real PII detection (not a mock) triggered from the browser.
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
