"""
server/reasoning.py

Action reasoning layer for the Privacy-Preserving AI Browser Agent.

Current implementation:
    Sanitized UI elements + natural-language instruction
                    |
                    v
              Rule-based reasoning
                    |
                    v
             Structured action

Supported actions:
    - click
    - type
    - scroll
    - wait

This module is intentionally independent from FastAPI so that the
rule-based reasoning layer can later be replaced by a local VLM/LLM
without changing main.py or the API schemas.

Security principles:
    - Only sanitized UI metadata is used.
    - No raw screenshots are processed here.
    - No credentials, passwords, OTPs, or other sensitive values are
      logged or persisted.
    - The reasoning layer returns only predefined structured actions.
    - It never generates arbitrary JavaScript.
"""

from __future__ import annotations

import difflib
import re

from schemas import (
    ClickAction,
    Element,
    ScrollAction,
    TypeAction,
    WaitAction,
)


class ActionInferenceError(Exception):
    """Raised when an instruction cannot be converted into a supported action."""


class TargetNotFoundError(Exception):
    """Raised when an action target cannot be found in the supplied UI elements."""


# Supported action words
_CLICK_WORDS = (
    "click",
    "press",
    "tap",
    "select",
    "choose",
)

_SCROLL_DIRECTIONS = (
    "up",
    "down",
    "left",
    "right",
)

# Words that should not affect target matching
_STOPWORDS = {
    "the",
    "a",
    "an",
    "on",
    "button",
    "link",
    "field",
    "input",
    "box",
    "element",
    "please",
    "now",
}

_ELEMENT_TYPE_WORDS = {
    "button",
    "link",
    "field",
    "input",
    "textbox",
    "text",
    "checkbox",
    "radio",
    "select",
    "dropdown",
    "menu",
}


def _normalize_text(value: str) -> str:
    """
    Normalize text for comparison.

    This function is only used for matching. It must NOT be used
    to modify values that the user wants to type.
    """
    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _clean_target_phrase(phrase: str) -> str:
    """
    Convert a natural-language target into a simpler matching phrase.

    Examples:

        "the Submit button" -> "submit"

        "the Search input field" -> "search"
    """
    normalized = _normalize_text(phrase)

    words = re.findall(r"[a-z0-9_'-]+", normalized)

    cleaned = [
        word
        for word in words
        if word not in _STOPWORDS
        and word not in _ELEMENT_TYPE_WORDS
    ]

    return " ".join(cleaned).strip()


def _token_similarity(first: str, second: str) -> float:
    """Calculate similarity between two pieces of text."""

    first = _normalize_text(first)
    second = _normalize_text(second)

    if not first or not second:
        return 0.0

    if first == second:
        return 1.0

    if first in second or second in first:
        return 0.95

    return difflib.SequenceMatcher(
        None,
        first,
        second,
    ).ratio()


def _best_matching_element(
    target_phrase: str,
    elements: list[Element],
) -> Element | None:
    """
    Find the most relevant UI element.

    Matching considers:
        1. Element label
        2. Element ID
        3. Fuzzy label similarity
        4. Fuzzy ID similarity

    Visible and interactive elements are preferred.
    """

    if not target_phrase:
        return None

    if not elements:
        return None

    normalized_target = _clean_target_phrase(target_phrase)

    if not normalized_target:
        return None

    # Prefer visible + interactive elements.
    preferred = [
        element
        for element in elements
        if element.visible and element.interactive
    ]

    candidates = preferred if preferred else list(elements)

    def score(element: Element) -> float:
        label = _normalize_text(element.label or "")
        element_id = _normalize_text(element.id or "")
        element_type = _normalize_text(element.type or "")

        label_score = _token_similarity(
            normalized_target,
            label,
        )

        id_score = _token_similarity(
            normalized_target,
            element_id,
        )

        type_bonus = 0.0

        target_words = set(normalized_target.split())

        if element_type in target_words:
            type_bonus = 0.05

        return max(label_score, id_score) + type_bonus

    scored = sorted(
        candidates,
        key=score,
        reverse=True,
    )

    if not scored:
        return None

    best = scored[0]

    # Confidence threshold prevents unrelated elements from
    # accidentally being selected.
    if score(best) < 0.50:
        return None

    return best


def _parse_scroll(instruction: str) -> ScrollAction:
    """
    Parse scroll commands.

    Examples:
        scroll down
        scroll down 800
        scroll down 800px
        scroll up 500 pixels
        scroll right 300
    """

    text = _normalize_text(instruction)

    direction = next(
        (
            direction
            for direction in _SCROLL_DIRECTIONS
            if re.search(rf"\b{direction}\b", text)
        ),
        "down",
    )

    amount_match = re.search(
        r"\b(\d+)\s*(?:px|pixels?)?\b",
        text,
    )

    amount = int(amount_match.group(1)) if amount_match else 500

    if amount <= 0:
        amount = 500

    # Safety limit for one scroll request.
    amount = min(amount, 5000)

    return ScrollAction(
        direction=direction,
        amount=amount,
    )


def _parse_wait(instruction: str) -> WaitAction:
    """
    Parse wait commands.

    Examples:
        wait
        wait 2 seconds
        wait 500 ms
        wait 1.5 seconds
    """

    text = _normalize_text(instruction)

    milliseconds_match = re.search(
        r"\b(\d+)\s*(?:ms|milliseconds?)\b",
        text,
    )

    seconds_match = re.search(
        r"\b(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b",
        text,
    )

    if milliseconds_match:
        duration = int(milliseconds_match.group(1))

    elif seconds_match:
        duration = int(
            float(seconds_match.group(1)) * 1000
        )

    else:
        duration = 1000

    if duration <= 0:
        duration = 1000

    # Safety limit: maximum 30 seconds per wait action.
    duration = min(duration, 30000)

    return WaitAction(
        duration=duration,
    )


def _parse_type(
    instruction: str,
    elements: list[Element],
) -> TypeAction:
    """
    Parse type/enter instructions.

    Examples:

        type "Hello World" into Search

        type 'Hello World' into Search

        enter 'Delhi' in Search

        type Hello into Search

    The original capitalization of the value is preserved.
    """

    # First handle quoted values.
    quoted_match = re.search(
        r'''(?:type|enter)\s+(?:"([^"]*)"|'([^']*)')\s+
        (?:into|in)\s+(?:the\s+)?(.+)$''',
        instruction,
        re.IGNORECASE | re.VERBOSE,
    )

    if quoted_match:
        if quoted_match.group(1) is not None:
            value = quoted_match.group(1)
        else:
            value = quoted_match.group(2)

        target_phrase = quoted_match.group(3)

    else:
        # Handle unquoted values.
        unquoted_match = re.search(
            r'''(?:type|enter)\s+(.+?)\s+
            (?:into|in)\s+(?:the\s+)?(.+)$''',
            instruction,
            re.IGNORECASE | re.VERBOSE,
        )

        if not unquoted_match:
            raise ActionInferenceError(
                "Could not parse a type action. Expected a phrase like "
                '"type \'Hello World\' into Search".'
            )

        value = unquoted_match.group(1).strip()
        target_phrase = unquoted_match.group(2)

    if not value:
        raise ActionInferenceError(
            "The type action contains an empty value."
        )

    cleaned_target = _clean_target_phrase(
        target_phrase
    )

    element = _best_matching_element(
        cleaned_target,
        elements,
    )

    if element is None:
        raise TargetNotFoundError(
            f"No element found matching '{cleaned_target}'."
        )

    return TypeAction(
        target=element.label or element.id,
        value=value,
    )


def _parse_click(
    instruction: str,
    elements: list[Element],
) -> ClickAction:
    """
    Parse click-like instructions.

    Examples:

        click Submit

        click the Submit button

        press Login

        tap the menu button

        select Settings
    """

    text = _normalize_text(instruction)

    target_phrase = text

    for word in _CLICK_WORDS:
        target_phrase = re.sub(
            rf"\b{re.escape(word)}\b",
            " ",
            target_phrase,
        )

    target_phrase = _clean_target_phrase(
        target_phrase
    )

    if not target_phrase:
        raise ActionInferenceError(
            "A click action was detected, but no target was provided."
        )

    element = _best_matching_element(
        target_phrase,
        elements,
    )

    if element is None:
        raise TargetNotFoundError(
            f"No element found matching '{target_phrase}'."
        )

    return ClickAction(
        target=element.label or element.id
    )


def infer_action(
    instruction: str | None,
    elements: list[Element],
):
    """
    Convert a natural-language instruction into one structured action.

    Supported actions:
        click
        type
        scroll
        wait

    Raises:
        ActionInferenceError:
            The instruction is missing or unsupported.

        TargetNotFoundError:
            The requested UI target could not be found.

    Only predefined action models from schemas.py are returned.
    No arbitrary JavaScript or executable code is generated.
    """

    if not instruction or not instruction.strip():
        raise ActionInferenceError(
            "No instruction was provided."
        )

    # Preserve the original instruction.
    original_instruction = instruction.strip()

    # Lowercase copy is ONLY used for action detection.
    text = _normalize_text(
        original_instruction
    )

    # ---------------------------------------------------------------
    # SCROLL
    # ---------------------------------------------------------------

    if re.search(r"\bscroll\b", text):
        return _parse_scroll(
            original_instruction
        )

    # ---------------------------------------------------------------
    # WAIT
    # ---------------------------------------------------------------

    if re.search(r"\bwait\b", text):
        return _parse_wait(
            original_instruction
        )

    # ---------------------------------------------------------------
    # TYPE / ENTER
    # ---------------------------------------------------------------

    if (
        re.search(r"\b(?:type|enter)\b", text)
        and re.search(r"\b(?:into|in)\b", text)
    ):
        # IMPORTANT:
        # Use the original instruction here so capitalization
        # of the value is preserved.
        return _parse_type(
            original_instruction,
            elements,
        )

    # ---------------------------------------------------------------
    # CLICK / PRESS / TAP / SELECT
    # ---------------------------------------------------------------

    if any(
        re.search(
            rf"\b{re.escape(word)}\b",
            text,
        )
        for word in _CLICK_WORDS
    ):
        return _parse_click(
            original_instruction,
            elements,
        )

    # ---------------------------------------------------------------
    # UNSUPPORTED ACTION
    # ---------------------------------------------------------------

    raise ActionInferenceError(
        "Could not infer a supported action "
        "(click/type/scroll/wait) from the instruction."
    )