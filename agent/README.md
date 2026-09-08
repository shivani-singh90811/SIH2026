# Browser Agent Module (`/agent`)

Safely executes the single structured action returned by the backend
(`docs/api.md` sections 9-14) inside the browser: **click, type,
scroll, wait** — nothing else, and **never arbitrary JavaScript**.

This is plain JavaScript, no build step, no bundler — same style as
the rest of `/extension` (`content.js`, `popup.js` are plain scripts
too), because this code needs to run inside the browser via a content
script, and the project doesn't use a bundler yet.

## Files

| File | Purpose |
|---|---|
| `executor.js` | Core logic: `executeAction(action, elements, domProvider?)` |
| `test_executor.js` | 21 tests, Node's built-in test runner (`node:test`) — zero npm dependencies |
| `test_harness.html` | Manual browser sanity check (open directly in a browser) |
| `package.json` | Just a `test` script convenience — no dependencies |

## How it works

`executeAction(action, elements)`:
1. For `click`/`type`: matches `action.target` against the `elements`
   list (`docs/api.md` sections 2 & 3 — id/label/bbox), preferring an
   exact `id` match, then exact label, then partial label — and only
   among elements that are `visible` and `interactive`.
2. Resolves that match to a **real DOM node**, trying (in order):
   - `document.querySelector('[data-agent-id="<id>"]')`
   - falling back to `document.elementFromPoint(bbox center)`
3. Executes the action using only fixed, hardcoded DOM calls —
   `.click()`, `.value =` + `dispatchEvent`, `window.scrollBy()`,
   `setTimeout()`. **Nothing from the action payload is ever `eval()`'d
   or passed to `new Function()`** (`docs/api.md` section 10: "No
   arbitrary JavaScript execution").
4. Returns `{ success: true, executed: {...} }` or
   `{ success: false, error: { code, message } }`, using the same
   error codes as the rest of the contract (section 16):
   `INVALID_ACTION`, `TARGET_NOT_FOUND`, `ACTION_EXECUTION_FAILED`.

## ⚠️ Flags for the integration lead

1. **`docs/api.md` doesn't define a result schema for the agent's own
   execution outcome** (section 21 just says "the action is recorded
   for evaluation," without a shape). `executor.js` returns
   `{success, executed}` / `{success, error}`, matching the contract's
   existing convention (section 15) for consistency — but this is this
   module's own choice, not something already in the contract. Worth
   confirming if `/tests` (evaluation/integration) expects something
   more specific.
2. **DOM targeting works today via `elementFromPoint` + bbox**, no
   changes needed elsewhere. But it would be **more reliable** if
   whoever builds the `elements` list (ShivaSai's `/extension`, or
   Arif's `/vision`) also tags each real DOM node with
   `data-agent-id="<element.id>"` when it's built — `executor.js`
   already prefers that path if present. This is a suggestion, not a
   blocker.

## Running the tests

No install needed beyond Node itself (v18+, tested on v22):

```bash
cd agent
node --test test_executor.js
# or: npm test
```

All 21 tests should pass. DOM-dependent behavior (click/type
execution) is tested with small hand-written fake DOM objects passed
via `domProvider` — no jsdom or any other browser-emulation dependency
is needed.

## Manual browser check

Open `test_harness.html` directly in a browser (double-click it, no
server needed) and click through the buttons — it loads `executor.js`
as a real `<script>` tag (`window.BrowserAgentExecutor`) and runs each
action against real DOM elements on the page.

## Integrating into the extension

In a content script (after `executor.js` is loaded as another
`<script>` in `manifest.json`'s `content_scripts`, same as `content.js`):

```javascript
// action = the parsed BackendResponse.action from docs/api.md section 9
// elements = the same elements list that was sent to the backend
const result = await BrowserAgentExecutor.executeAction(action, elements);
if (!result.success) {
  // handle result.error.code / result.error.message
}
```

## Security notes

- **No arbitrary code execution.** Every action maps to one of four
  fixed, hardcoded DOM operations. The action payload's fields
  (`target`, `value`, `direction`, `amount`, `duration`) are only ever
  used as *data* (a string to match, a number to scroll by), never as
  code to execute.
- **Privacy rule (`docs/api.md` section 12):** a `type` action's
  `value` is never included in the returned result, an error message,
  or any log — verified by a dedicated test.
- **No network calls, no dependencies beyond Node's own test runner.**

## Limitations (MVP)

- Target matching is exact/substring-based, not fuzzy/NLP — it relies
  on the backend already having picked a specific, close-to-exact
  `target` string from the `elements` list (which `reasoning.py` in
  `/server` already does).
- `elementFromPoint` only finds the topmost element at that pixel — if
  another element visually overlaps the target's bbox, resolution can
  fail or hit the wrong node. The `data-agent-id` tagging path (see
  flag #2 above) avoids this entirely once available.
- Only single-target actions are supported — no multi-step or
  compound actions (e.g. "click X then type Y") in one call; the
  backend is expected to return one action per request, matching
  `docs/api.md` section 9.
