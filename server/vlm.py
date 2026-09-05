"""Model-agnostic reasoning boundary for sanitized browser context.

The current provider is the existing rule-based reasoner. A local VLM can
later implement the same interface without changing the FastAPI contract.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, Sequence

from pydantic import TypeAdapter, ValidationError

from reasoning import ActionInferenceError, TargetNotFoundError, infer_action as infer_rule_action
from schemas import Action, Element, PrivacyRegionSummary


class VLMError(Exception):
    """Base error for the reasoning boundary."""


class InvalidModelOutputError(VLMError):
    """Raised when a provider returns an unsupported action shape."""


class VLMProvider(Protocol):
    """Interface implemented by fallback and future local VLM providers."""

    def infer(
        self,
        instruction: str | None,
        elements: Sequence[Element],
        image: str | None = None,
        privacy_regions: Sequence[PrivacyRegionSummary] = (),
    ) -> Action:
        """Infer one validated browser action from sanitized context."""


@dataclass(frozen=True)
class VLMConfig:
    """Provider settings; no credentials or provider is assumed by default."""

    provider: str = "fallback"
    model_name: str | None = None
    endpoint: str | None = None

    @classmethod
    def from_environment(cls) -> "VLMConfig":
        return cls(
            provider=os.getenv("MODEL_PROVIDER", "fallback").strip().lower(),
            model_name=os.getenv("MODEL_NAME") or None,
            endpoint=os.getenv("MODEL_ENDPOINT") or None,
        )


_ACTION_ADAPTER = TypeAdapter(Action)


def validate_action(action: object) -> Action:
    """Validate provider output against the four supported action models."""

    try:
        return _ACTION_ADAPTER.validate_python(action)
    except ValidationError as exc:
        raise InvalidModelOutputError(
            "Reasoning provider returned an invalid browser action."
        ) from exc


class FallbackProvider:
    """Adapter around the existing safe rule-based reasoning implementation."""

    def infer(
        self,
        instruction: str | None,
        elements: Sequence[Element],
        image: str | None = None,
        privacy_regions: Sequence[PrivacyRegionSummary] = (),
    ) -> Action:
        # Image and privacy summaries are intentionally not logged or persisted.
        action = infer_rule_action(instruction, list(elements))
        return validate_action(action)


def create_provider(config: VLMConfig | None = None) -> VLMProvider:
    """Create the configured provider without loading a model at startup."""

    selected = config or VLMConfig.from_environment()
    if selected.provider in {"fallback", "rule-based", "rule_based"}:
        return FallbackProvider()

    raise VLMError(
        f"Unsupported MODEL_PROVIDER '{selected.provider}'. "
        "Only the fallback provider is currently available."
    )


provider = create_provider()


def infer_action(
    instruction: str | None,
    elements: Sequence[Element],
    image: str | None = None,
    privacy_regions: Sequence[PrivacyRegionSummary] = (),
) -> Action:
    """Infer one validated action from sanitized browser context."""

    return provider.infer(instruction, elements, image, privacy_regions)


__all__ = [
    "ActionInferenceError",
    "InvalidModelOutputError",
    "TargetNotFoundError",
    "VLMConfig",
    "VLMError",
    "VLMProvider",
    "create_provider",
    "infer_action",
    "validate_action",
]