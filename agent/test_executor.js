/**
 * agent/test_executor.js
 *
 * Tests for executor.js using Node's built-in test runner (`node:test`,
 * available since Node 18 -- no npm install needed). DOM-dependent
 * behavior is tested with small hand-written fake DOM objects injected
 * via `domProvider`, so no jsdom or other browser-emulation dependency
 * is required either.
 *
 * Run with:
 *   node --test test_executor.js
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { executeAction, locateElement } = require("./executor.js");

// ---------------------------------------------------------------------------
// Fake DOM helpers
// ---------------------------------------------------------------------------

function makeFakeNode(overrides = {}) {
    return {
        tagName: "BUTTON",
        disabled: false,
        isContentEditable: false,
        clicked: false,
        value: undefined,
        events: [],
        click() {
            this.clicked = true;
        },
        dispatchEvent(event) {
            this.events.push(event.type);
        },
        ...overrides,
    };
}

function makeFakeDom({ nodesById = {}, nodeAtPoint = null, scrollCalls = [], timers = [] } = {}) {
    return {
        querySelector(selector) {
            const match = /data-agent-id="([^"]+)"/.exec(selector);
            if (match && nodesById[match[1]]) return nodesById[match[1]];
            return null;
        },
        elementFromPoint() {
            return nodeAtPoint;
        },
        window: {
            scrollBy(dx, dy) {
                scrollCalls.push([dx, dy]);
            },
        },
        setTimeout(fn, ms) {
            timers.push(ms);
            fn(); // resolve immediately for tests
        },
    };
}

const SAMPLE_ELEMENTS = [
    { id: "element_001", type: "button", label: "Submit", bbox: [100, 200, 180, 240], visible: true, interactive: true },
    { id: "element_002", type: "input", label: "Search", bbox: [10, 10, 300, 40], visible: true, interactive: true },
    { id: "element_003", type: "button", label: "Cancel", bbox: [200, 200, 280, 240], visible: false, interactive: true },
];

// ---------------------------------------------------------------------------
// locateElement (pure metadata matching, no DOM needed)
// ---------------------------------------------------------------------------

test("locateElement matches by exact id", () => {
    const el = locateElement("element_001", SAMPLE_ELEMENTS);
    assert.equal(el.label, "Submit");
});

test("locateElement matches by exact label", () => {
    const el = locateElement("Submit", SAMPLE_ELEMENTS);
    assert.equal(el.id, "element_001");
});

test("locateElement matches by case-insensitive partial label", () => {
    const el = locateElement("submit button", SAMPLE_ELEMENTS);
    assert.equal(el.id, "element_001");
});

test("locateElement does not match invisible/non-interactive elements when visible candidates exist", () => {
    // "Cancel" is invisible; the agent should never target an invisible
    // element, so this must return null (TARGET_NOT_FOUND upstream),
    // not silently fall back to it.
    const el = locateElement("Cancel", SAMPLE_ELEMENTS);
    assert.equal(el, null);
});

test("locateElement returns null for no match", () => {
    const el = locateElement("Nonexistent", SAMPLE_ELEMENTS);
    assert.equal(el, null);
});

test("locateElement returns null for empty target or elements", () => {
    assert.equal(locateElement("", SAMPLE_ELEMENTS), null);
    assert.equal(locateElement("Submit", []), null);
});

// ---------------------------------------------------------------------------
// executeAction: click
// ---------------------------------------------------------------------------

test("click succeeds via data-agent-id tag", async () => {
    const node = makeFakeNode();
    const dom = makeFakeDom({ nodesById: { element_001: node } });
    const result = await executeAction({ type: "click", target: "Submit" }, SAMPLE_ELEMENTS, dom);
    assert.equal(result.success, true);
    assert.equal(node.clicked, true);
    assert.deepEqual(result.executed, { type: "click", target: "Submit" });
});

test("click falls back to elementFromPoint when no data-agent-id tag exists", async () => {
    const node = makeFakeNode();
    const dom = makeFakeDom({ nodeAtPoint: node });
    const result = await executeAction({ type: "click", target: "Submit" }, SAMPLE_ELEMENTS, dom);
    assert.equal(result.success, true);
    assert.equal(node.clicked, true);
});

test("click returns TARGET_NOT_FOUND when no element metadata matches", async () => {
    const dom = makeFakeDom({});
    const result = await executeAction({ type: "click", target: "Nonexistent" }, SAMPLE_ELEMENTS, dom);
    assert.equal(result.success, false);
    assert.equal(result.error.code, "TARGET_NOT_FOUND");
});

test("click returns TARGET_NOT_FOUND when metadata matches but DOM node cannot be resolved", async () => {
    const dom = makeFakeDom({}); // no nodesById, no nodeAtPoint
    const result = await executeAction({ type: "click", target: "Submit" }, SAMPLE_ELEMENTS, dom);
    assert.equal(result.success, false);
    assert.equal(result.error.code, "TARGET_NOT_FOUND");
});

test("click returns ACTION_EXECUTION_FAILED for a disabled element", async () => {
    const node = makeFakeNode({ disabled: true });
    const dom = makeFakeDom({ nodesById: { element_001: node } });
    const result = await executeAction({ type: "click", target: "Submit" }, SAMPLE_ELEMENTS, dom);
    assert.equal(result.success, false);
    assert.equal(result.error.code, "ACTION_EXECUTION_FAILED");
});

// ---------------------------------------------------------------------------
// executeAction: type
// ---------------------------------------------------------------------------

test("type succeeds on an input element and fires input/change events", async () => {
    const node = makeFakeNode({ tagName: "INPUT" });
    const dom = makeFakeDom({ nodesById: { element_002: node } });
    const result = await executeAction({ type: "type", target: "Search", value: "weather" }, SAMPLE_ELEMENTS, dom);
    assert.equal(result.success, true);
    assert.equal(node.value, "weather");
    assert.deepEqual(node.events, ["input", "change"]);
    // Privacy rule: the value must never appear in the result.
    assert.equal(JSON.stringify(result).includes("weather"), false);
});

test("type fails on a non-text-enterable element", async () => {
    const node = makeFakeNode({ tagName: "BUTTON" });
    const dom = makeFakeDom({ nodesById: { element_001: node } });
    const secretValue = "supersecretvalue123";
    const result = await executeAction({ type: "type", target: "Submit", value: secretValue }, SAMPLE_ELEMENTS, dom);
    assert.equal(result.success, false);
    assert.equal(result.error.code, "ACTION_EXECUTION_FAILED");
    assert.equal(JSON.stringify(result).includes(secretValue), false);
});

// ---------------------------------------------------------------------------
// executeAction: scroll
// ---------------------------------------------------------------------------

test("scroll down calls scrollBy with the right sign", async () => {
    const scrollCalls = [];
    const dom = makeFakeDom({ scrollCalls });
    const result = await executeAction({ type: "scroll", direction: "down", amount: 500 }, [], dom);
    assert.equal(result.success, true);
    assert.deepEqual(scrollCalls, [[0, 500]]);
});

test("scroll up is negative on the y axis", async () => {
    const scrollCalls = [];
    const dom = makeFakeDom({ scrollCalls });
    await executeAction({ type: "scroll", direction: "up", amount: 300 }, [], dom);
    assert.deepEqual(scrollCalls, [[0, -300]]);
});

test("scroll rejects an invalid direction", async () => {
    const dom = makeFakeDom({});
    const result = await executeAction({ type: "scroll", direction: "diagonal", amount: 100 }, [], dom);
    assert.equal(result.success, false);
    assert.equal(result.error.code, "INVALID_ACTION");
});

test("scroll rejects a non-positive amount", async () => {
    const dom = makeFakeDom({});
    const result = await executeAction({ type: "scroll", direction: "down", amount: -5 }, [], dom);
    assert.equal(result.success, false);
    assert.equal(result.error.code, "INVALID_ACTION");
});

// ---------------------------------------------------------------------------
// executeAction: wait
// ---------------------------------------------------------------------------

test("wait resolves successfully after the given duration", async () => {
    const timers = [];
    const dom = makeFakeDom({ timers });
    const result = await executeAction({ type: "wait", duration: 1000 }, [], dom);
    assert.equal(result.success, true);
    assert.deepEqual(timers, [1000]);
});

test("wait rejects a non-positive duration", async () => {
    const dom = makeFakeDom({});
    const result = await executeAction({ type: "wait", duration: 0 }, [], dom);
    assert.equal(result.success, false);
    assert.equal(result.error.code, "INVALID_ACTION");
});

// ---------------------------------------------------------------------------
// executeAction: unsupported / no arbitrary execution
// ---------------------------------------------------------------------------

test("unsupported action type returns INVALID_ACTION", async () => {
    const dom = makeFakeDom({});
    const result = await executeAction({ type: "eval", code: "alert(1)" }, [], dom);
    assert.equal(result.success, false);
    assert.equal(result.error.code, "INVALID_ACTION");
});

test("missing action returns INVALID_ACTION rather than throwing", async () => {
    const dom = makeFakeDom({});
    const result = await executeAction(null, [], dom);
    assert.equal(result.success, false);
    assert.equal(result.error.code, "INVALID_ACTION");
});
