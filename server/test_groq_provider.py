"""
server/test_groq_provider.py

Tests for groq_provider.py. All HTTP calls are mocked -- no real network
access or API key is needed to run these.

Run with:
    python -m unittest test_groq_provider.py -v
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from groq_provider import GroqVisionProvider, _strip_code_fences
from schemas import Element
from vlm import InvalidModelOutputError, VLMError


def _fake_groq_response(content_text: str):
    """Build a fake urlopen() context manager returning a Groq-shaped body."""
    body = json.dumps(
        {"choices": [{"message": {"content": content_text}}]}
    ).encode("utf-8")
    mock_response = MagicMock()
    mock_response.read.return_value = body
    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_response
    return mock_context


SAMPLE_ELEMENTS = [
    Element(id="element_001", type="button", label="Submit", bbox=(100, 200, 180, 240)),
]


class TestGroqVisionProvider(unittest.TestCase):
    def test_missing_api_key_raises_vlm_error(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(VLMError):
                GroqVisionProvider(api_key=None)

    def test_successful_click_action(self):
        provider = GroqVisionProvider(api_key="test-key")
        fake_response = _fake_groq_response('{"type": "click", "target": "Submit"}')
        with patch("urllib.request.urlopen", return_value=fake_response):
            action = provider.infer("Click the Submit button.", SAMPLE_ELEMENTS)
        self.assertEqual(action.type, "click")
        self.assertEqual(action.target, "Submit")

    def test_strips_markdown_code_fences(self):
        provider = GroqVisionProvider(api_key="test-key")
        fake_response = _fake_groq_response('```json\n{"type": "wait", "duration": 500}\n```')
        with patch("urllib.request.urlopen", return_value=fake_response):
            action = provider.infer("wait a bit", SAMPLE_ELEMENTS)
        self.assertEqual(action.type, "wait")
        self.assertEqual(action.duration, 500)

    def test_http_error_raises_vlm_error(self):
        import urllib.error

        provider = GroqVisionProvider(api_key="test-key")
        http_error = urllib.error.HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=MagicMock(read=lambda: b'{"error": "invalid api key"}'),
        )
        with patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(VLMError):
                provider.infer("click submit", SAMPLE_ELEMENTS)

    def test_malformed_response_body_raises_invalid_model_output(self):
        provider = GroqVisionProvider(api_key="test-key")
        body = json.dumps({"unexpected": "shape"}).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = body
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response
        with patch("urllib.request.urlopen", return_value=mock_context):
            with self.assertRaises(InvalidModelOutputError):
                provider.infer("click submit", SAMPLE_ELEMENTS)

    def test_non_json_model_output_raises_invalid_model_output(self):
        provider = GroqVisionProvider(api_key="test-key")
        fake_response = _fake_groq_response("I think you should click Submit!")
        with patch("urllib.request.urlopen", return_value=fake_response):
            with self.assertRaises(InvalidModelOutputError):
                provider.infer("click submit", SAMPLE_ELEMENTS)

    def test_invalid_action_shape_raises_invalid_model_output(self):
        provider = GroqVisionProvider(api_key="test-key")
        # "type": "double_click" is not one of the four supported actions.
        fake_response = _fake_groq_response('{"type": "double_click", "target": "Submit"}')
        with patch("urllib.request.urlopen", return_value=fake_response):
            with self.assertRaises(InvalidModelOutputError):
                provider.infer("click submit", SAMPLE_ELEMENTS)

    def test_strip_code_fences_helper(self):
        self.assertEqual(_strip_code_fences('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(_strip_code_fences('```\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(_strip_code_fences('{"a": 1}'), '{"a": 1}')

    def test_never_logs_or_persists_image(self):
        # Sanity check: infer() doesn't return or attach the raw image
        # anywhere in the resulting action.
        provider = GroqVisionProvider(api_key="test-key")
        fake_response = _fake_groq_response('{"type": "click", "target": "Submit"}')
        fake_image = "verysecretbase64imagecontent"
        with patch("urllib.request.urlopen", return_value=fake_response):
            action = provider.infer("click submit", SAMPLE_ELEMENTS, image=fake_image)
        self.assertNotIn(fake_image, str(action.model_dump()))


if __name__ == "__main__":
    unittest.main()