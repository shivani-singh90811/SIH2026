# API Contracts

This document defines the common data formats used by all modules of the
Privacy-Preserving AI Browser Agent.

All team members must follow these contracts while developing their modules.

---

# 1. General Rules

 ## 1.1 Coordinates

All bounding boxes use the following format:

 [x1, y1, x2, y2]

Where:

- x1 = left
- y1 = top
- x2 = right
- y2 = bottom

Coordinates are relative to the captured screenshot.

---

## 1.2 Confidence

Confidence values must be between 0 and 1.

Example:

```json
{
  "confidence": 0.95
}
```
##1.3 Privacy Rule
Sensitive information must be detected and redacted locally.
The following order is mandatory:
Detection → Redaction → Verification → Transmission
The original sensitive screenshot must never be sent to the server.
2. DOM Perception Output
The extension may collect safe DOM/UI information.
Example:
{
  "elements": [
    {
      "id": "element_001",
      "type": "button",
      "label": "Submit",
      "bbox": [100, 200, 180, 240],
      "visible": true,
      "interactive": true
    }
  ]
}
Fields
id: Unique element identifier
type: Element type
label: Safe visible label
bbox: Bounding box
visible: Whether the element is visible
interactive: Whether the element can be interacted with
Allowed element types
Initial types:
button
input
textarea
select
link
checkbox
radio
image
heading
text
form
other


3. Local Vision Output
The local vision model analyzes the screenshot and returns visual elements.
Example:
{
  "elements": [
    {
      "id": "vision_001",
      "type": "button",
      "label": "Submit",
      "bbox": [100, 200, 180, 240],
      "confidence": 0.95
    },
    {
      "id": "vision_002",
      "type": "face",
      "label": null,
      "bbox": [400, 100, 500, 220],
      "confidence": 0.91
    }
  ]
}
Required fields
id
type
bbox
confidence
Optional fields
label
4. Privacy Detection Output
The privacy module identifies sensitive regions.
Example:
{
  "regions": [
    {
      "id": "privacy_001",
      "type": "password",
      "bbox": [100, 300, 300, 340],
      "redaction": "black",
      "confidence": 0.99
    },
    {
      "id": "privacy_002",
      "type": "face",
      "bbox": [400, 100, 500, 220],
      "redaction": "blur",
      "confidence": 0.92
    }
  ]
}
Supported sensitive types
Initial types:
password
email
phone
otp
pin
cvv
credit_card
debit_card
aadhaar
pan
passport
driving_license
account_number
date_of_birth
face
personal_text
other


5. Redaction Types
The privacy module can use:
Black
Used for highly sensitive information.
Example:
{
  "redaction": "black"
}
Blur
Used for visual information such as faces.
Example:
{
  "redaction": "blur"
}
Mask
Used when partial information may safely remain visible.
Example:
{
  "redaction": "mask"
}
6. Privacy Verification Output
Before transmission, the privacy module must return a verification result.
Example:
{
  "privacy_verified": true,
  "regions": [
    {
      "id": "privacy_001",
      "type": "password",
      "bbox": [100, 300, 300, 340],
      "redaction": "black",
      "confidence": 0.99
    }
  ]
}
If verification fails:
{
  "privacy_verified": false,
  "error": {
    "code": "PRIVACY_VERIFICATION_FAILED",
    "message": "Sensitive information could not be safely redacted."
  }
}
When privacy_verified is false:
The screenshot must NOT be sent to the server.


7. Sanitized Context
Only sanitized context can be transmitted to the backend.
Example:
{
  "privacy_verified": true,
  "screen": {
    "width": 1920,
    "height": 1080
  },
  "elements": [
    {
      "id": "element_001",
      "type": "button",
      "label": "Submit",
      "bbox": [100, 200, 180, 240],
      "visible": true,
      "interactive": true
    }
  ],
  "privacy_regions": [
    {
      "type": "password",
      "bbox": [100, 300, 300, 340],
      "redaction": "black"
    }
  ]
}
The sanitized context MUST NOT contain:
Password values
OTP values
PIN values
CVV values
Full card numbers
Raw email values when classified as sensitive
Raw phone numbers
Aadhaar numbers
PAN numbers
Passport numbers
Other detected sensitive values

8. Backend Request
The extension sends sanitized context to the backend.
Example:
{
  "request_id": "req_001",
  "privacy_verified": true,
  "screen": {
    "width": 1920,
    "height": 1080
  },
  "elements": [],
  "privacy_regions": [],
  "image": "<SANITIZED_IMAGE>"
}
Important
The backend must reject requests where:
{
  "privacy_verified": false
}


9. Backend Response
The backend/VLM returns a structured browser action.
Example:
{
  "request_id": "req_001",
  "success": true,
  "action": {
    "type": "click",
    "target": "Submit"
  }
}

10. Supported Browser Actions
The initial agent supports only the following actions:
click
type
scroll
wait
No arbitrary JavaScript execution is allowed.

11. Click Action
Example:
{
  "type": "click",
  "target": "Submit"
}
The browser agent should locate the target using:
DOM element information
Element ID
Visible label
Bounding box
The agent should prefer DOM targeting when available.


12. Type Action
Example:
{
  "type": "type",
  "target": "Search",
  "value": "weather"
}
Privacy Rule
The agent must not expose sensitive values in logs.
Sensitive values such as passwords or OTPs must never be logged.
13. Scroll Action
Example:
{
  "type": "scroll",
  "direction": "down",
  "amount": 500
}
Allowed directions:
up
down
left
right
14. Wait Action
Example:
{
  "type": "wait",
  "duration": 1000
}
Duration is specified in milliseconds.


15. Error Response
All modules should use the following error structure:
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message."
  }
}
Example:
{
  "success": false,
  "error": {
    "code": "MODEL_LOAD_FAILED",
    "message": "Vision model could not be loaded."
  }
}


16. Common Error Codes
Initial error codes:
MODEL_LOAD_FAILED
VISION_INFERENCE_FAILED
PRIVACY_DETECTION_FAILED
PRIVACY_VERIFICATION_FAILED
INVALID_REQUEST
INVALID_ACTION
TARGET_NOT_FOUND
ACTION_EXECUTION_FAILED
NETWORK_ERROR
SERVER_ERROR


17. Request ID
Every end-to-end request should have a unique request_id.
Example:
{
  "request_id": "req_001"
}
This helps with:
debugging
latency measurement
logs
tracing requests


18. End-to-End Data Flow
The complete data flow is:
Browser Screen
      ↓
Extension
      ↓
DOM Perception + Local Vision
      ↓
Privacy / PII Detection
      ↓
Local Redaction
      ↓
Privacy Verification
      ↓
Sanitized Context
      ↓
Backend
      ↓
VLM / AI Reasoning
      ↓
Structured Action
      ↓
Browser Agent
      ↓
Browser Action


19. Integration Rules
All team members must follow these rules:
Do not change the API format without discussing it with the integration lead.
Do not send raw sensitive information to the backend.
Do not send the original screenshot to the backend.
Do not execute arbitrary JavaScript returned by the server.
Do not log passwords, OTPs, card numbers, or other sensitive values.
Keep module-specific code inside the assigned folder.
Use the existing API contract when connecting modules.
Test your module independently before creating a Pull Request.
Do not directly push to main.
Use:
Feature Branch → Commit → Push → Pull Request → Review → Merge


20. Module Ownership
Module
Directory
Responsibility
Browser Extension
/extension
Browser integration, screen capture, DOM communication
Local Vision
/vision
Local visual perception and bounding boxes
Privacy / PII
/privacy
Sensitive data detection, redaction and verification
Backend / VLM
/server
Sanitized data processing and AI reasoning
Browser Agent
/agent
Safe browser action execution
Integration / Testing
/tests
End-to-end integration and evaluation


21. First End-to-End Demo
The first working demo should follow this scenario:
User asks:
"Click the Submit button."
The system should:
Capture the screen locally.
Analyze the screen using DOM + local vision.
Detect sensitive information.
Redact sensitive information locally.
Verify the redaction.
Send only sanitized context to the server.
VLM identifies the Submit button.
Backend returns:
{
  "action": {
    "type": "click",
    "target": "Submit"
  }
}
Browser agent clicks the Submit button.
The action is recorded for evaluation.

22. Performance Metrics
The system should measure:
Visual perception accuracy
PII detection precision
PII detection recall
Redaction precision
Client-side CPU usage
Client-side memory usage
Local inference latency
Network latency
End-to-end task latency
These metrics correspond to the SIH evaluation criteria.

24. Contract Version
Current API contract version:
v1
Any breaking change must update the contract version and be discussed with the integration lead.
