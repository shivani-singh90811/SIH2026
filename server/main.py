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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from reasoning import ActionInferenceError, TargetNotFoundError, infer_action
from schemas import BackendRequest, BackendResponse, error_response

app = FastAPI(title="Privacy-Preserving AI Browser Agent - Backend (MVP stub)")


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