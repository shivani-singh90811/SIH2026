"""
server/groq_provider.py

A real VLMProvider implementation (see vlm.py) that calls an open-weight
vision-language model hosted on Groq. This satisfies the SIH26171
requirement: "Participants are free to use any offline deployable
(open-source/open-weights) model on server side. During SIH they can
use cloud hosted version of these."

Llama 3.2 Vision is Meta's open-weight model -- Groq only *hosts* it
(same relationship as using a cloud GPU to run an open-source model
yourself). This is not a proprietary-API call in the sense the project
rules forbid (no Claude/GPT/Gemini/Grok): the model weights themselves
are open, Groq is just the (fast, free-tier) hosting layer, exactly as
the problem statement anticipates for the hackathon phase.

No new third-party dependency is added -- this uses only Python's
standard library (`urllib.request`, `json`), matching the project's
"no unnecessary dependencies" rule.

Setup:
    1. Get a free API key from https://console.groq.com/keys
    2. Set environment variables before starting the server:
         set MODEL_PROVIDER=groq          (Windows cmd)
         set GROQ_API_KEY=your_key_here
    3. Run: uvicorn main:app --reload

If GROQ_API_KEY is missing, or the API call fails for any reason, this
raises VLMError -- main.py already maps that to a clean SERVER_ERROR
response (see docs/api.md section 16). It never silently falls back to
the rule-based reasoner, so it's always clear which path actually ran.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Sequence

from vlm import InvalidModelOutputError, VLMError, validate_action
from schemas import Action, Element, PrivacyRegionSummary

_GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_MODEL = "llama-3.2-11b-vision-preview"
_REQUEST_TIMEOUT_SECONDS = 20

_SYSTEM_PROMPT = """You are a browser action planner for a privacy-preserving browser agent.
You receive a screenshot (any sensitive regions have already been redacted locally
before reaching you -- you will never see real passwords, OTPs, card numbers, etc.)
and a list of UI elements detected on the page (id, type, label, bounding box).

Decide the SINGLE next browser action that fulfils the user's instruction.
Respond with ONLY a raw JSON object (no markdown, no code fences, no explanation)
matching exactly one of these shapes:

{"type": "click", "target": "<element label or id>"}
{"type": "type", "target": "<element label or id>", "value": "<text to type>"}
{"type": "scroll", "direction": "up" | "down" | "left" | "right", "amount": <positive integer>}
{"type": "wait", "duration": <positive integer, milliseconds>}

Only ever use "target" values that exactly match an id or label from the
elements list you were given. Never invent an element that isn't listed."""


def _build_messages(
    instruction: str | None,
    elements: Sequence[Element],
    image: str | None,
    privacy_regions: Sequence[PrivacyRegionSummary],
) -> list[dict]:
    elements_json = json.dumps(
        [
            {"id": e.id, "type": e.type, "label": e.label, "bbox": list(e.bbox)}
            for e in elements
        ]
    )
    redacted_summary = json.dumps(
        [{"type": r.type, "redaction": r.redaction} for r in privacy_regions]
    )

    user_text = (
        f"Instruction: {instruction!r}\n\n"
        f"Elements on screen: {elements_json}\n\n"
        f"Redacted regions already protected before this reached you: {redacted_summary}\n\n"
        "Respond with only the JSON action object."
    )

    content: list[dict] = [{"type": "text", "text": user_text}]

    if image:
        # `image` is expected to already be base64-encoded (docs/api.md
        # section 8's sanitized-context "image" field). We only add the
        # data-URI prefix here; we never decode or persist it.
        data_uri = image if image.startswith("data:") else f"data:image/png;base64,{image}"
        content.append({"type": "image_url", "image_url": {"url": data_uri}})

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[len("json"):]
    return text.strip()


class GroqVisionProvider:
    """Calls a Groq-hosted, open-weight vision-language model."""

    def __init__(self, api_key: str | None = None, model_name: str | None = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model_name = model_name or os.getenv("MODEL_NAME") or _DEFAULT_MODEL
        if not self.api_key:
            raise VLMError(
                "GROQ_API_KEY is not set. Get a free key from "
                "https://console.groq.com/keys and set it as an environment "
                "variable before starting the server."
            )

    def infer(
        self,
        instruction: str | None,
        elements: Sequence[Element],
        image: str | None = None,
        privacy_regions: Sequence[PrivacyRegionSummary] = (),
    ) -> Action:
        messages = _build_messages(instruction, elements, image, privacy_regions)
        payload = json.dumps(
            {
                "model": self.model_name,
                "messages": messages,
                "temperature": 0,
                "max_tokens": 200,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            _GROQ_ENDPOINT,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise VLMError(f"Groq API returned HTTP {exc.code}: {error_body[:300]}") from exc
        except urllib.error.URLError as exc:
            raise VLMError(f"Could not reach Groq API: {exc.reason}") from exc
        except TimeoutError as exc:
            raise VLMError("Groq API request timed out.") from exc

        try:
            raw_text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InvalidModelOutputError(
                "Groq API response did not contain the expected message content."
            ) from exc

        cleaned = _strip_code_fences(raw_text)
        try:
            action_dict = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise InvalidModelOutputError(
                f"Model did not return valid JSON: {cleaned[:200]!r}"
            ) from exc

        return validate_action(action_dict)