# Privacy-Preserving Browser Agent Backend

This service accepts privacy-verified, sanitized browser context and returns
one structured browser action. It is implemented with FastAPI and Pydantic and
does not require a network service, API key, or large AI model.

## Current architecture

```text
sanitized browser context
        -> FastAPI request validation
        -> privacy_verified check
        -> VLM provider interface (vlm.py)
        -> validated click/type/scroll/wait action
```

The configured provider currently defaults to `FallbackProvider`, which adapts
the existing safe rule-based implementation in `reasoning.py`. No real VLM is
running. The `image` field is accepted as optional sanitized context for future
providers, but the fallback does not inspect it and the server does not save or
log it.

## API

### `GET /health`

Returns:

```json
{"status": "ok"}
```

### `POST /api/v1/action`

The request contains `request_id`, `privacy_verified`, screen dimensions,
sanitized UI elements, privacy-region summaries, an optional sanitized image,
and an instruction. Requests with `privacy_verified: false` are rejected before
reasoning.

The response contains the request ID and exactly one validated action:

- `click`: target element
- `type`: target element and value
- `scroll`: direction and bounded pixel amount
- `wait`: bounded duration in milliseconds

The backend never returns arbitrary JavaScript or executable instructions.

## VLM provider boundary

`vlm.py` defines the `VLMProvider` interface, `VLMConfig`, and
`validate_action()`. A future local or open-source VLM can implement
`VLMProvider.infer()` and return one of the existing Pydantic action models.
The result must pass `validate_action()` before it can reach the browser agent.

Configuration is environment-based:

```text
MODEL_PROVIDER=fallback
MODEL_NAME=<optional future model name>
MODEL_ENDPOINT=<optional future local endpoint>
```

Only `fallback`, `rule-based`, and `rule_based` are implemented today. Other
providers fail clearly rather than pretending that a model is available.
No model dependencies were added.

## Run the backend

From the repository root:

```bash
cd server
pip install -r requirements.txt
uvicorn main:app --reload
```

The service runs at `http://127.0.0.1:8000`. FastAPI Swagger UI is available at
`http://127.0.0.1:8000/docs`.

## Run tests

```bash
cd server
pip install -r requirements.txt -r requirements-test.txt
python -m unittest test_server.py -v
```

The suite covers the health endpoint, all four actions, target lookup errors,
request validation, privacy rejection, capitalization preservation, safety
limits, provider selection, and invalid provider output. The current suite has
23 passing tests.

## Security and limitations

- The backend is designed to receive sanitized context only.
- Raw screenshots and sensitive values must be redacted on-device before the
  request is sent.
- The fallback uses instruction text and sanitized element metadata only; it is
  not visual understanding.
- No authentication, persistence, or request logging is implemented.
- A real local VLM provider still needs to be selected, implemented, and tested
  before image-based reasoning is available.