"""
server/test_server.py

Tests for the FastAPI backend.

These tests use FastAPI's TestClient, so the actual Uvicorn server
does not need to be running while the tests are executed.

Run from the server directory:

    python -m unittest test_server.py -v
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from main import app
from schemas import ClickAction, Element
from vlm import (
    FallbackProvider,
    InvalidModelOutputError,
    VLMConfig,
    VLMError,
    create_provider,
    validate_action,
)


client = TestClient(app)


def _base_request(**overrides) -> dict:
    """
    Create a valid backend request used by the tests.

    Individual tests can override fields by passing keyword arguments.
    """

    request = {
        "request_id": "req_001",
        "privacy_verified": True,
        "screen": {
            "width": 1920,
            "height": 1080,
        },
        "elements": [
            {
                "id": "element_001",
                "type": "button",
                "label": "Submit",
                "bbox": [100, 200, 180, 240],
                "visible": True,
                "interactive": True,
            },
            {
                "id": "element_002",
                "type": "input",
                "label": "Search",
                "bbox": [10, 10, 300, 40],
                "visible": True,
                "interactive": True,
            },
            {
                "id": "login_button",
                "type": "button",
                "label": "Login",
                "bbox": [400, 200, 500, 240],
                "visible": True,
                "interactive": True,
            },
        ],
        "privacy_regions": [],
        "image": None,
        "instruction": "Click the Submit button.",
    }

    request.update(overrides)

    return request


class TestBackendContract(unittest.TestCase):

    # ===============================================================
    # BASIC BACKEND TESTS
    # ===============================================================

    def test_click_action_matches_demo_scenario(self):
        """
        Verify that the backend can understand a basic click request.
        """

        response = client.post(
            "/api/v1/action",
            json=_base_request(),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        body = response.json()

        self.assertEqual(
            body["request_id"],
            "req_001",
        )

        self.assertTrue(
            body["success"]
        )

        self.assertEqual(
            body["action"],
            {
                "type": "click",
                "target": "Submit",
            },
        )

    def test_type_action(self):
        """
        Verify that the backend can generate a type action.
        """

        req = _base_request(
            instruction="type 'weather' into Search"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        action = response.json()["action"]

        self.assertEqual(
            action["type"],
            "type",
        )

        self.assertEqual(
            action["target"],
            "Search",
        )

        self.assertEqual(
            action["value"],
            "weather",
        )

    def test_scroll_action(self):
        """
        Verify that the backend can generate a scroll action.
        """

        req = _base_request(
            instruction="scroll down 800px"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        action = response.json()["action"]

        self.assertEqual(
            action,
            {
                "type": "scroll",
                "direction": "down",
                "amount": 800,
            },
        )

    def test_wait_action(self):
        """
        Verify that the backend can generate a wait action.
        """

        req = _base_request(
            instruction="wait 2 seconds"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        action = response.json()["action"]

        self.assertEqual(
            action,
            {
                "type": "wait",
                "duration": 2000,
            },
        )

    # ===============================================================
    # PRIVACY TESTS
    # ===============================================================

    def test_privacy_verified_false_is_rejected(self):
        """
        The backend must reject requests when privacy verification
        has not succeeded.
        """

        req = _base_request(
            privacy_verified=False
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        body = response.json()

        self.assertFalse(
            body["success"]
        )

        self.assertEqual(
            body["error"]["code"],
            "INVALID_REQUEST",
        )

    # ===============================================================
    # ERROR HANDLING TESTS
    # ===============================================================

    def test_unmatched_target_returns_target_not_found(self):
        """
        Verify that an unknown UI target produces a 404 error.
        """

        req = _base_request(
            instruction="click the Nonexistent Button"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            404,
        )

        body = response.json()

        self.assertFalse(
            body["success"]
        )

        self.assertEqual(
            body["error"]["code"],
            "TARGET_NOT_FOUND",
        )

    def test_missing_instruction_returns_invalid_request(self):
        """
        Verify that a missing instruction is rejected.
        """

        req = _base_request(
            instruction=None
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        body = response.json()

        self.assertEqual(
            body["error"]["code"],
            "INVALID_REQUEST",
        )

    def test_malformed_request_returns_validation_error(self):
        """
        FastAPI/Pydantic should reject a request that does not contain
        the required backend fields.
        """

        response = client.post(
            "/api/v1/action",
            json={
                "request_id": "req_002"
            },
        )

        self.assertEqual(
            response.status_code,
            422,
        )

    def test_unsupported_action_words_return_invalid_request(self):
        """
        Verify that unsupported instructions are rejected.
        """

        req = _base_request(
            instruction="teleport to the moon"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.assertEqual(
            response.json()["error"]["code"],
            "INVALID_REQUEST",
        )

    # ===============================================================
    # HEALTH CHECK
    # ===============================================================

    def test_health_check(self):
        """
        Verify that the backend health endpoint is working.
        """

        response = client.get(
            "/health"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.json(),
            {
                "status": "ok"
            },
        )

    # ===============================================================
    # ADDITIONAL REASONING TESTS
    # ===============================================================

    def test_type_preserves_capitalization(self):
        """
        The value entered by the user must preserve its original
        capitalization.
        """

        req = _base_request(
            instruction='Type "Hello World" into Search'
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        action = response.json()["action"]

        self.assertEqual(
            action["type"],
            "type",
        )

        self.assertEqual(
            action["target"],
            "Search",
        )

        self.assertEqual(
            action["value"],
            "Hello World",
        )

    def test_type_preserves_mixed_case(self):
        """
        Verify that mixed uppercase/lowercase text is preserved.
        """

        req = _base_request(
            instruction="enter 'Delhi NCR 2026' in Search"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        action = response.json()["action"]

        self.assertEqual(
            action["value"],
            "Delhi NCR 2026",
        )

    def test_click_is_case_insensitive(self):
        """
        Action detection and target matching should not depend on
        capitalization.
        """

        req = _base_request(
            instruction="CLICK THE SUBMIT BUTTON"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        action = response.json()["action"]

        self.assertEqual(
            action,
            {
                "type": "click",
                "target": "Submit",
            },
        )

    def test_click_can_match_element_id(self):
        """
        Verify that the reasoning layer can find an element using
        its ID when necessary.
        """

        req = _base_request(
            instruction="click login_button"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        action = response.json()["action"]

        self.assertEqual(
            action["type"],
            "click",
        )

        self.assertEqual(
            action["target"],
            "Login",
        )

    def test_tap_is_supported(self):
        """
        'tap' should be treated as a click action.
        """

        req = _base_request(
            instruction="tap the Submit button"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        action = response.json()["action"]

        self.assertEqual(
            action,
            {
                "type": "click",
                "target": "Submit",
            },
        )

    def test_scroll_default_amount(self):
        """
        If no scroll amount is provided, the backend should use
        the safe default amount.
        """

        req = _base_request(
            instruction="scroll down"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        action = response.json()["action"]

        self.assertEqual(
            action,
            {
                "type": "scroll",
                "direction": "down",
                "amount": 500,
            },
        )

    def test_scroll_amount_has_safety_limit(self):
        """
        Very large scroll values should be limited to the maximum
        safe amount defined in reasoning.py.
        """

        req = _base_request(
            instruction="scroll down 100000px"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        action = response.json()["action"]

        self.assertEqual(
            action["amount"],
            5000,
        )

    def test_wait_milliseconds(self):
        """
        Verify that milliseconds are accepted for wait actions.
        """

        req = _base_request(
            instruction="wait 500 ms"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        action = response.json()["action"]

        self.assertEqual(
            action,
            {
                "type": "wait",
                "duration": 500,
            },
        )

    def test_wait_has_safety_limit(self):
        """
        Very long waits should be limited to the maximum safe
        duration defined in reasoning.py.
        """

        req = _base_request(
            instruction="wait 100 seconds"
        )

        response = client.post(
            "/api/v1/action",
            json=req,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        action = response.json()["action"]

        self.assertEqual(
            action["duration"],
            30000,
        )


class TestVLMBoundary(unittest.TestCase):

    def test_default_provider_is_the_rule_based_fallback(self):
        provider = create_provider(VLMConfig())
        self.assertIsInstance(provider, FallbackProvider)

    def test_fallback_provider_returns_validated_action(self):
        provider = FallbackProvider()
        element = Element.model_validate(_base_request()["elements"][0])
        action = provider.infer("click Submit", [element])
        self.assertIsInstance(action, ClickAction)
        self.assertEqual(action.target, "Submit")

    def test_invalid_model_output_is_rejected(self):
        with self.assertRaises(InvalidModelOutputError):
            validate_action({"type": "execute_javascript", "code": "alert(1)"})

    def test_unsupported_provider_is_rejected(self):
        with self.assertRaises(VLMError):
            create_provider(VLMConfig(provider="cloud"))


if __name__ == "__main__":
    unittest.main()