# Local Vision Module (`/vision`)

MVP for the Local Vision stage (`docs/api.md` section 3, `docs/architecture.md`
section B). **No real ONNX/WebGPU vision model is wired up yet** — this scans
the DOM directly and reformats what it finds into the exact "Local Vision
Output" shape from the contract, so the rest of the pipeline (privacy,
backend, agent) can be built and tested against a real element list today.

Written so a real vision model can replace `scanDocument()`'s internals
later without changing `buildVisionOutput()`'s public shape.

## Files

| File | Purpose |
|---|---|
| `detector.js` | Core logic: `buildVisionOutput(document)` → `{ elements: [...] }` |
| `test_detector.js` | 22 tests, Node's built-in test runner (`node:test`) — zero dependencies |
| `test_harness.html` | Manual browser sanity check (open directly in a browser) |
| `package.json` | Just a `test` script convenience — no dependencies |

## How it works

`buildVisionOutput(root)` walks the DOM (or a subtree) and, for each node:
1. **Classifies** it into one of `docs/api.md` section 2's element types
   (`button`, `input`, `textarea`, `select`, `link`, `checkbox`, `radio`,
   `image`, `heading`, `text`, `form`) using tag name and attributes.
2. **Extracts a label** — `aria-label` first, then type-specific sources
   (`alt` for images, `placeholder` for inputs — **never the entered
   value**), then visible text.
3. **Checks visibility** (`offsetParent` + non-zero bounding box).
4. Returns `{ id, type, label, bbox, confidence }` per element, matching
   the contract exactly — plus `id`s assigned once per scan so they stay
   unique.

Recognized "leaf" elements (button, input, textarea, select, img) are not
descended into, so a button's inner icon/span markup isn't double-reported
as a separate "text" element.

## ⚠️ Not included in this fallback

- **No face detection.** `docs/architecture.md` lists faces as a
  privacy-relevant category, but that needs actual image/CV analysis,
  which this DOM-only fallback cannot do. A real vision model is needed
  for that category.
- **Confidence is not a model probability.** It's a fixed value: `0.98`
  for a definitive tag match (e.g. an actual `<button>`), `0.65` for a
  heuristic classification (e.g. "this leaf node with text is probably
  a text element"). See `CONFIDENCE` in `detector.js`.
- **`elementFromPoint`-style pixel matching isn't needed here** — this
  reads the DOM directly, so bounding boxes come from
  `getBoundingClientRect()`, which is exact for the current viewport
  (matches a `chrome.tabs.captureVisibleTab`-style screenshot 1:1).

## Running the tests

No install needed beyond Node itself (v18+, tested on v22):

```bash
cd vision
node --test test_detector.js
# or: npm test
```

All 22 tests should pass. DOM interaction is tested with small
hand-written fake DOM node objects — no jsdom or other browser-emulation
dependency is needed (same pattern as `/agent/test_executor.js`).

## Manual browser check

Open `test_harness.html` directly in a browser and click "Scan this
page" — it loads `detector.js` as a real `<script>` tag
(`window.LocalVisionDetector`) and scans real DOM elements, including a
deliberately hidden button to confirm visibility filtering works.

## Integrating into the extension

```javascript
// In a content script, after detector.js is loaded as another <script>
// in manifest.json's content_scripts (same as content.js):
const visionOutput = LocalVisionDetector.buildVisionOutput(document);
// visionOutput.elements matches docs/api.md section 3 and can be fed
// directly into /privacy's detector or /server's request `elements` field.
```

## Security notes

- **Never reads input/textarea entered values.** Labels for those come
  only from `aria-label` or `placeholder` — a dedicated test
  (`buildVisionOutput never includes raw input values`) checks this.
  An earlier draft of this module *did* fall back to an input's live
  `.value` when no placeholder was present — that was caught by this
  test suite and fixed before this file was ever integrated.
- **No network calls, no dependencies beyond Node's own test runner.**
- Only reads the same category of "safe DOM/UI metadata" that
  `docs/api.md` section 2 already allows the extension to collect.

## Limitations (MVP)

- **Visibility heuristic is approximate.** `offsetParent === null` misses
  `position: fixed` elements in some browsers, and doesn't check
  `visibility: hidden` or `opacity: 0`. Good enough for the MVP demo
  scenario; a real vision model sidesteps this by looking at rendered
  pixels instead.
- **Text/heading classification is heuristic**, not a trained model —
  a `<div>` styled to look like a heading won't be classified as one;
  only actual `<h1>`-`<h6>` tags are.
- **No cross-frame or shadow-DOM traversal** in this MVP — only the
  given root's regular DOM tree.