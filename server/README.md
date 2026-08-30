# Backend / VLM Module (`/server`)

MVP FastAPI backend for the Privacy-Preserving AI Browser Agent, per
`docs/api.md` sections 8, 9, and 18-21.

**No proprietary AI API is used** (per project rules — no Gemini,
Claude, ChatGPT, Grok, etc.). Action inference is a small rule-based
matcher (`reasoning.py`) standing in for a real local/VLM model, so
this module is fully runnable and testable today, with **zero API
keys and zero network dependency**.

## ⚠️ Flag for the integration lead

`docs/api.md` section 8's example Backend Request does **not** include
a field for the user's natural-language instruction (e.g. "Click the
Submit button") — without it, nothing (real VLM or this stub) can know
what action to infer. This module adds `instruction` as an **additive,
optional** field on the request (see `schemas.py` docstring) so the
first end-to-end demo (section 21) is possible. Every field already in
the contract is unchanged. **This should be confirmed with the team**
per Integration Rule #1 ("Do not change the API format without
discussing it with the integration lead") — it's implemented here so
work isn't blocked, not as a unilateral final decision.

## Files

| File | Purpose |
|---|---|
| `schemas.py` | Pydantic request/response models, matching `docs/api.md` sections 2, 4, 5, 7-9, 15-16 |
| `reasoning.py` | Rule-based instruction → action matcher (the VLM stand-in) |
| `main.py` | FastAPI app: one endpoint, wires reasoning + schemas together |
| `requirements.txt` | `fastapi`, `uvicorn` — needed to run the server |
| `requirements-test.txt` | `httpx` — needed only to run the tests (FastAPI's `TestClient`) |
| `test_server.py` | 10 tests covering the demo scenario, all four action types, and error paths |

## Running it

```bash
cd server
pip install -r requirements.txt
uvicorn main:app --reload
```

Server runs at `http://127.0.0.1:8000`. Try the exact demo scenario
from `docs/api.md` section 21:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/action \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "req_001",
    "privacy_verified": true,
    "screen": {"width": 1920, "height": 1080},
    "elements": [
      {"id": "element_001", "type": "button", "label": "Submit",
       "bbox": [100, 200, 180, 240], "visible": true, "interactive": true}
    ],
    "privacy_regions": [],
    "instruction": "Click the Submit button."
  }'
```

Expected response (matches section 9 exactly):
```json
{"request_id": "req_001", "success": true, "action": {"type": "click", "target": "Submit"}}
```

## Running the tests

```bash
cd server
pip install -r requirements.txt -r requirements-test.txt
python3 -m unittest test_server.py -v
```

All 10 tests should pass. They cover:
- The exact section 21 demo scenario (click)
- `type`, `scroll`, `wait` actions
- Rejecting `privacy_verified: false` (section 8's mandatory rule)
- `TARGET_NOT_FOUND` when no element matches
- `INVALID_REQUEST` for missing/unparseable instructions and malformed requests

## What this module does NOT do

- **No real AI/VLM reasoning.** `reasoning.py` is pattern-matching on
  the instruction text, not visual/language understanding. It's
  structured so a real model can replace `infer_action()` without
  touching `main.py`, `schemas.py`, or any other module.
- **No image processing.** The `image` field is accepted (per the
  contract) but currently unused by the stub reasoning — a real VLM
  would use it.
- **No persistence, auth, or logging of requests.** Out of scope for
  the MVP; `docs/api.md` also forbids logging sensitive values, so any
  future logging must stay at the level of action type / target label,
  never raw instruction text that might contain something sensitive.

## Security notes

- Requests with `privacy_verified: false` are rejected before any
  reasoning happens (`docs/api.md` section 8).
- This module never receives raw screenshots or raw PII — only
  `elements` (safe DOM/UI labels) and `privacy_regions` summaries
  (type/bbox/redaction only, no confidence or raw value — section 7).
- No API keys or secrets anywhere in this module.