"""
server/reasoning.py

MVP stand-in for the VLM/AI-reasoning stage in docs/api.md's pipeline
(section 18: "VLM / AI Reasoning -> Structured Action"). No proprietary
model is used here (per project rules) -- this is a small rule-based
matcher over the `elements` list the extension already sent, so the
first end-to-end demo (section 21: "Click the Submit button") works
end-to-end today. It is written so a real local/VLM-based reasoning
step can replace `infer_action()` later without touching main.py or
the request/response schemas.

Security note: this module never receives raw sensitive values --
only `elements` (safe DOM/UI labels, per section 2) and the sanitized
`privacy_regions` summary (section 7). Nothing here is logged with
raw instruction text beyond what the caller already sent over HTTP.
"""

from __future__ import annotations

import difflib
import re

from schemas import ClickAction, Element, ScrollAction, TypeAction, WaitAction


class ActionInferenceError(Exception):
    """Raised when no action can be inferred from the given instruction."""


class TargetNotFoundError(Exception):
    """Raised when an instruction implies an action but no matching
    element can be found among the ones provided."""


_CLICK_WORDS = ("click", "press", "tap", "select", "choose")
_SCROLL_DIRECTIONS = ("up", "down", "left", "right")

_STOPWORDS = {"the", "a", "an", "on", "button", "link", "please", "now"}


def _clean_target_phrase(phrase: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9']+", phrase.lower()) if w not in _STOPWORDS]
    return " ".join(words).strip()


def _best_matching_element(target_phrase: str, elements: list[Element]) -> Element | None:
    """Match a free-text target phrase to the closest interactive,
    visible element by label (falling back to id). Prefers DOM
    targeting via label/id, per docs/api.md section 11.
    """
    if not target_phrase:
        return None

    candidates = [e for e in elements if e.visible and e.interactive]
    if not candidates:
        candidates = list(elements)  # fall back rather than fail outright

    def _score(element: Element) -> float:
        label = (element.label or "").lower()
        if not label:
            return 0.0
        if target_phrase in label or label in target_phrase:
            return 1.0
        return difflib.SequenceMatcher(None, target_phrase, label).ratio()

    scored = sorted(candidates, key=_score, reverse=True)
    if not scored or _score(scored[0]) < 0.5:
        return None
    return scored[0]


def _parse_scroll(instruction: str) -> ScrollAction:
    direction = next((d for d in _SCROLL_DIRECTIONS if d in instruction), "down")
    amount_match = re.search(r"(\d+)\s*(px|pixels)?", instruction)
    amount = int(amount_match.group(1)) if amount_match else 500
    return ScrollAction(direction=direction, amount=amount)


def _parse_wait(instruction: str) -> WaitAction:
    seconds_match = re.search(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|s)\b", instruction)
    ms_match = re.search(r"(\d+)\s*(ms|milliseconds?)\b", instruction)
    if ms_match:
        duration = int(ms_match.group(1))
    elif seconds_match:
        duration = int(float(seconds_match.group(1)) * 1000)
    else:
        duration = 1000
    return WaitAction(duration=duration)


def _parse_type(instruction: str, elements: list[Element]) -> TypeAction:
    # Matches "type X into Y" / "enter X in Y" / "type X in the Y field"
    match = re.search(
        r"(?:type|enter)\s+['\"]?(.+?)['\"]?\s+(?:into|in)\s+(?:the\s+)?(.+)",
        instruction,
    )
    if not match:
        raise ActionInferenceError(
            "Could not parse a type action; expected a phrase like "
            "\"type 'weather' into Search\"."
        )
    value, target_phrase = match.group(1), _clean_target_phrase(match.group(2))
    element = _best_matching_element(target_phrase, elements)
    if element is None:
        raise TargetNotFoundError(f"No element found matching '{target_phrase}'.")
    return TypeAction(target=element.label or element.id, value=value)


def infer_action(instruction: str | None, elements: list[Element]):
    """Infer a single structured action from a natural-language
    instruction and the elements the extension observed.

    Raises:
        ActionInferenceError: the instruction's intent could not be
            parsed at all (e.g. missing, or an unsupported action).
        TargetNotFoundError: the intent was understood (e.g. "click")
            but no matching element was found among `elements`.
    """
    if not instruction or not instruction.strip():
        raise ActionInferenceError("No instruction was provided.")

    text = instruction.strip().lower()

    if "scroll" in text:
        return _parse_scroll(text)

    if "wait" in text:
        return _parse_wait(text)

    if any(word in text for word in ("type", "enter")) and (" into " in text or " in " in text):
        return _parse_type(text, elements)

    if any(word in text for word in _CLICK_WORDS):
        # Strip the action verb itself, then clean stopwords, e.g.
        # "click the submit button" -> "submit"
        target_phrase = text
        for word in _CLICK_WORDS:
            target_phrase = target_phrase.replace(word, " ")
        target_phrase = _clean_target_phrase(target_phrase)
        element = _best_matching_element(target_phrase, elements)
        if element is None:
            raise TargetNotFoundError(f"No element found matching '{target_phrase}'.")
        return ClickAction(target=element.label or element.id)

    raise ActionInferenceError(
        f"Could not infer a supported action (click/type/scroll/wait) from: {instruction!r}"
    )