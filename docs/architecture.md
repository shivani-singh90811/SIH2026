# Privacy-Preserving AI Browser Agent

## 1. Project Goal

Build a browser-based AI agent that can understand the user's screen and perform browser actions while keeping sensitive information private.

The core privacy principle is:

> Sensitive visual data must be detected and sanitized locally before any network request is made.

## 2. High-Level Architecture

User
  ↓
Chrome / Firefox Extension
  ↓
Screen Capture + DOM Perception
  ↓
Local Vision Model
  ↓
Privacy & PII Detection
  ↓
Local Redaction
  ↓
Privacy Verification
  ↓
Sanitized Context
  ↓
Backend API
  ↓
VLM / AI Reasoning
  ↓
Structured Action
  ↓
Browser Agent
  ↓
Browser Action


## 3. Main Components

### A. Browser Extension

Responsibilities:
- Capture visible browser screen
- Read safe DOM/UI metadata
- Communicate with local AI modules
- Send only sanitized context
- Receive structured actions
- Execute browser actions

Directory:

`/extension`

---

### B. Local Vision Module

Responsibilities:
- Run a lightweight vision model locally
- Use ONNX Runtime Web / WebGPU where available
- Analyze screenshot
- Detect visual UI elements
- Generate bounding boxes
- Return confidence scores

Directory:

`/vision`

The model must run on the client device.

No raw screenshot should be sent to the server before privacy processing.

---

### C. Privacy & PII Module

Responsibilities:
- Detect sensitive information from DOM
- Detect sensitive visual regions
- Detect PII such as:
  - Email
  - Phone number
  - Password
  - OTP
  - Credit/debit card
  - Aadhaar
  - PAN
  - Passport
  - Other sensitive information
- Detect faces where supported
- Generate privacy regions
- Redact sensitive regions locally
- Verify that redaction was successful

Directory:

`/privacy`

---

### D. Backend

Responsibilities:
- Receive only sanitized context
- Validate incoming requests
- Send sanitized visual context to VLM
- Return structured browser actions

Directory:

`/server`

The backend must reject requests that do not pass privacy verification.

---

### E. Browser Agent

Responsibilities:
- Receive structured actions
- Validate actions
- Locate target elements
- Execute safe browser actions

Supported initial actions:

- click
- type
- scroll
- wait

Directory:

`/agent`

The agent must not execute arbitrary JavaScript received from the server.

---

### F. Testing & Evaluation

Responsibilities:
- End-to-end testing
- Privacy testing
- Vision accuracy testing
- PII precision/recall
- Redaction accuracy
- CPU/RAM usage
- End-to-end latency

Directory:

`/tests`

---

## 4. Data Flow

### Step 1: Capture

The extension captures the visible screen and safe DOM information.

### Step 2: Local Perception

The local vision model and DOM analyzer identify UI elements.

### Step 3: Privacy Detection

The privacy module identifies sensitive information and creates bounding boxes.

### Step 4: Local Redaction

Sensitive regions are masked, blacked out, blurred, or otherwise sanitized.

### Step 5: Verification

The system verifies that sensitive information has been removed before transmission.

### Step 6: Server Processing

Only sanitized visual context is sent to the backend.

### Step 7: AI Reasoning

The VLM interprets the sanitized context and determines the required action.

### Step 8: Action Execution

The backend returns a structured action and the local browser agent executes it.

---

## 5. Privacy Rule

The following rule is mandatory:

> No original screenshot containing sensitive information may be transmitted to the server.

The client must perform:

Detection → Redaction → Verification → Transmission

not:

Detection → Transmission → Redaction

---

## 6. Initial Demo Scenario

The first end-to-end demonstration should use a controlled test website.

Example task:

"Click the Submit button."

The screen contains:
- Name
- Email
- Phone
- Password
- Submit button

The system should:

1. Capture the screen locally.
2. Detect sensitive information locally.
3. Redact sensitive information.
4. Verify the redaction.
5. Send only sanitized context.
6. VLM identifies the Submit button.
7. VLM returns a structured click action.
8. Browser agent clicks Submit.

---

## 7. Technology Stack

### Client

- JavaScript / TypeScript
- Chrome Extension Manifest V3
- Firefox WebExtension APIs
- ONNX Runtime Web
- WebGPU
- WebAssembly
- HTML/CSS

### Backend

- Python
- FastAPI

### AI

- Lightweight client-side vision model
- VLM / open-weight model on server

### Development

- Git
- GitHub
- Pull Requests
- Feature branches

---

## 8. Development Rule

Each team member works only on their assigned module unless integration work requires otherwise.

No direct pushes to `main`.

Workflow:

Feature branch → Commit → Push → Pull Request → Review → Merge

---

## 9. Module Ownership

| Module | Owner |
|---|---|
| Extension | Member 1 |
| Local Vision | Member 2 |
| Privacy / PII | Member 3 |
| Backend / VLM | Member 4 |
| Browser Agent | Member 5 |
| Integration / Testing | Member 6 |

---

## 10. Integration Principle

All modules must communicate using the common data structures defined in `docs/api.md`.

Do not change the API format without discussing it with the integration lead.

The goal is to build one working end-to-end privacy-preserving browser agent, not six independent projects.
