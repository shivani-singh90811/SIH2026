"""
server/test_server.py

Tests for the backend stub, using FastAPI's TestClient (in-process,
no real HTTP server needs to be running). Needs `httpx` installed
(see requirements-test.txt) -- only for running these tests, not for
running the server itself.

Run with:
    pip install -r requirements.txt -r requirements-test.txt
    python3 -m unittest test_server.py -v
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _base_request(**overrides) -> dict:
    request = {
        "request_id": "req_001",
        "privacy_verified": True,
        "screen": {"width": 1920, "height": 1080},
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
        ],
        "privacy_regions": [],
        "image": None,
        "instruction": "Click the Submit button.",
    }
    request.update(overrides)
    return request


class TestBackendContract(unittest.TestCase):
    def test_click_action_matches_demo_scenario(self):
        # docs/api.md section 21: "Click the Submit button."
        response = client.post("/api/v1/action", json=_base_request())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["request_id"], "req_001")
        self.assertTrue(body["success"])
        self.assertEqual(body["action"], {"type": "click", "target": "Submit"})

    def test_type_action(self):
        req = _base_request(instruction="type 'weather' into Search")
        response = client.post("/api/v1/action", json=req)
        self.assertEqual(response.status_code, 200)
        action = response.json()["action"]
        self.assertEqual(action["type"], "type")
        self.assertEqual(action["target"], "Search")
        self.assertEqual(action["value"], "weather")

    def test_scroll_action(self):
        req = _base_request(instruction="scroll down 800px")
        response = client.post("/api/v1/action", json=req)
        self.assertEqual(response.status_code, 200)
        action = response.json()["action"]
        self.assertEqual(action, {"type": "scroll", "direction": "down", "amount": 800})

    def test_wait_action(self):
        req = _base_request(instruction="wait 2 seconds")
        response = client.post("/api/v1/action", json=req)
        self.assertEqual(response.status_code, 200)
        action = response.json()["action"]
        self.assertEqual(action, {"type": "wait", "duration": 2000})

    def test_privacy_verified_false_is_rejected(self):
        # docs/api.md section 8: "The backend must reject requests
        # where privacy_verified is false."
        req = _base_request(privacy_verified=False)
        response = client.post("/api/v1/action", json=req)
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "INVALID_REQUEST")

    def test_unmatched_target_returns_target_not_found(self):
        req = _base_request(instruction="click the Nonexistent Button")
        response = client.post("/api/v1/action", json=req)
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "TARGET_NOT_FOUND")

    def test_missing_instruction_returns_invalid_request(self):
        req = _base_request(instruction=None)
        response = client.post("/api/v1/action", json=req)
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"]["code"], "INVALID_REQUEST")

    def test_malformed_request_returns_invalid_request(self):
        response = client.post("/api/v1/action", json={"request_id": "req_002"})
        self.assertEqual(response.status_code, 422)  # FastAPI's own schema validation

    def test_unsupported_action_words_return_invalid_request(self):
        req = _base_request(instruction="teleport to the moon")
        response = client.post("/api/v1/action", json=req)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_health_check(self):
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()