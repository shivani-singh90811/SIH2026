/**
 * vision/test_detector.js
 *
 * Tests for detector.js using Node's built-in test runner (`node:test`,
 * Node 18+) -- no npm install needed. DOM nodes are small hand-written
 * fake objects (same pattern as /agent/test_executor.js), so no jsdom
 * or other browser-emulation dependency is required.
 *
 * Run with:
 *   node --test test_detector.js
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { buildVisionOutput, classifyElement, extractLabel, isVisible } = require("./detector.js");

// ---------------------------------------------------------------------------
// Fake DOM helpers
// ---------------------------------------------------------------------------

function rect(left, top, right, bottom) {
    return { left, top, right, bottom, width: right - left, height: bottom - top };
}

function makeNode(overrides = {}) {
    const attrs = overrides.attrs || {};
    return {
        tagName: overrides.tagName || "DIV",
        type: overrides.type,
        href: overrides.href,
        value: overrides.value,
        textContent: overrides.textContent || "",
        children: overrides.children || [],
        offsetParent: overrides.offsetParent === undefined ? {} : overrides.offsetParent,
        getAttribute(name) {
            return attrs[name] ?? null;
        },
        getBoundingClientRect() {
            return overrides.rect || rect(0, 0, 100, 30);
        },
    };
}

// ---------------------------------------------------------------------------
// classifyElement
// ---------------------------------------------------------------------------

test("classifyElement recognizes a button", () => {
    const el = classifyElement(makeNode({ tagName: "BUTTON" }));
    assert.equal(el.type, "button");
    assert.equal(el.confidence, 0.98);
});

test("classifyElement recognizes input subtypes", () => {
    assert.equal(classifyElement(makeNode({ tagName: "INPUT", type: "text" })).type, "input");
    assert.equal(classifyElement(makeNode({ tagName: "INPUT", type: "checkbox" })).type, "checkbox");
    assert.equal(classifyElement(makeNode({ tagName: "INPUT", type: "radio" })).type, "radio");
    assert.equal(classifyElement(makeNode({ tagName: "INPUT", type: "submit" })).type, "button");
});

test("classifyElement recognizes textarea, select, image, form", () => {
    assert.equal(classifyElement(makeNode({ tagName: "TEXTAREA" })).type, "textarea");
    assert.equal(classifyElement(makeNode({ tagName: "SELECT" })).type, "select");
    assert.equal(classifyElement(makeNode({ tagName: "IMG" })).type, "image");
    assert.equal(classifyElement(makeNode({ tagName: "FORM" })).type, "form");
});

test("classifyElement requires an href for a link", () => {
    const withHref = classifyElement(makeNode({ tagName: "A", attrs: { href: "/page" } }));
    assert.equal(withHref.type, "link");
    const withoutHref = classifyElement(makeNode({ tagName: "A", attrs: {} }));
    assert.equal(withoutHref, null);
});

test("classifyElement recognizes headings with heuristic confidence", () => {
    const el = classifyElement(makeNode({ tagName: "H2" }));
    assert.equal(el.type, "heading");
    assert.equal(el.confidence, 0.65);
});

test("classifyElement treats a leaf text node as 'text'", () => {
    const el = classifyElement(makeNode({ tagName: "P", textContent: "Some paragraph text" }));
    assert.equal(el.type, "text");
});

test("classifyElement does not classify a wrapper div with element children as text", () => {
    const child = makeNode({ tagName: "SPAN", textContent: "inner" });
    const el = classifyElement(makeNode({ tagName: "DIV", textContent: "inner", children: [child] }));
    assert.equal(el, null);
});

test("classifyElement returns null for an empty, unrecognized element", () => {
    const el = classifyElement(makeNode({ tagName: "DIV", textContent: "" }));
    assert.equal(el, null);
});

// ---------------------------------------------------------------------------
// extractLabel
// ---------------------------------------------------------------------------

test("extractLabel prefers aria-label over everything else", () => {
    const node = makeNode({ tagName: "BUTTON", textContent: "Go", attrs: { "aria-label": "Search now" } });
    assert.equal(extractLabel(node, "button"), "Search now");
});

test("extractLabel uses alt text for images", () => {
    const node = makeNode({ tagName: "IMG", attrs: { alt: "Company logo" } });
    assert.equal(extractLabel(node, "image"), "Company logo");
});

test("extractLabel uses placeholder for inputs when no aria-label", () => {
    const node = makeNode({ tagName: "INPUT", attrs: { placeholder: "Search products" } });
    assert.equal(extractLabel(node, "input"), "Search products");
});

test("extractLabel falls back to textContent for buttons", () => {
    const node = makeNode({ tagName: "BUTTON", textContent: "  Submit  " });
    assert.equal(extractLabel(node, "button"), "Submit");
});

test("extractLabel truncates very long text", () => {
    const longText = "x".repeat(200);
    const node = makeNode({ tagName: "P", textContent: longText });
    const label = extractLabel(node, "text");
    assert.ok(label.length <= 83);
    assert.ok(label.endsWith("..."));
});

test("extractLabel returns null when nothing usable is found", () => {
    const node = makeNode({ tagName: "IMG", attrs: {} });
    assert.equal(extractLabel(node, "image"), null);
});

// ---------------------------------------------------------------------------
// isVisible
// ---------------------------------------------------------------------------

test("isVisible is false when offsetParent is null (display:none)", () => {
    const node = makeNode({ offsetParent: null, rect: rect(0, 0, 100, 30) });
    assert.equal(isVisible(node), false);
});

test("isVisible is false for a zero-area bounding box", () => {
    const node = makeNode({ rect: rect(10, 10, 10, 10) });
    assert.equal(isVisible(node), false);
});

test("isVisible is true for a normal visible element", () => {
    const node = makeNode({ rect: rect(0, 0, 100, 30) });
    assert.equal(isVisible(node), true);
});

// ---------------------------------------------------------------------------
// buildVisionOutput (end-to-end tree walk)
// ---------------------------------------------------------------------------

test("buildVisionOutput matches docs/api.md section 3 shape", () => {
    const button = makeNode({ tagName: "BUTTON", textContent: "Submit", rect: rect(100, 200, 180, 240) });
    const input = makeNode({ tagName: "INPUT", type: "email", attrs: { placeholder: "you@example.com" }, rect: rect(10, 10, 300, 40) });
    const root = makeNode({ tagName: "DIV", children: [input, button] });

    const output = buildVisionOutput(root);
    assert.equal(Array.isArray(output.elements), true);
    assert.equal(output.elements.length, 2);

    const [first, second] = output.elements;
    assert.equal(first.id, "vision_001");
    assert.equal(second.id, "vision_002");
    assert.deepEqual(first.bbox, [10, 10, 300, 40]);
    assert.equal(first.type, "input");
    assert.equal(first.label, "you@example.com");
    assert.equal(second.type, "button");
    assert.equal(second.label, "Submit");
    for (const el of output.elements) {
        assert.ok(el.confidence >= 0 && el.confidence <= 1);
    }
});

test("buildVisionOutput does not descend into a button's inner markup", () => {
    const innerSpan = makeNode({ tagName: "SPAN", textContent: "Submit" });
    const button = makeNode({ tagName: "BUTTON", textContent: "Submit", children: [innerSpan], rect: rect(0, 0, 80, 30) });
    const output = buildVisionOutput(button);
    // Only the button itself should be reported, not a separate "text"
    // element for the inner span.
    assert.equal(output.elements.length, 1);
    assert.equal(output.elements[0].type, "button");
});

test("buildVisionOutput skips invisible elements", () => {
    const hidden = makeNode({ tagName: "BUTTON", textContent: "Hidden", offsetParent: null, rect: rect(0, 0, 80, 30) });
    const visible = makeNode({ tagName: "BUTTON", textContent: "Visible", rect: rect(0, 40, 80, 70) });
    const root = makeNode({ tagName: "DIV", children: [hidden, visible] });
    const output = buildVisionOutput(root);
    assert.equal(output.elements.length, 1);
    assert.equal(output.elements[0].label, "Visible");
});

test("buildVisionOutput accepts a Document-like root (with .body)", () => {
    const button = makeNode({ tagName: "BUTTON", textContent: "Go", rect: rect(0, 0, 60, 30) });
    const fakeDocument = { body: makeNode({ tagName: "BODY", children: [button] }) };
    const output = buildVisionOutput(fakeDocument);
    assert.equal(output.elements.length, 1);
    assert.equal(output.elements[0].type, "button");
});

test("buildVisionOutput never includes raw input values (privacy-safe)", () => {
    const input = makeNode({ tagName: "INPUT", type: "password", value: "supersecret123", rect: rect(0, 0, 100, 30) });
    const output = buildVisionOutput(input);
    assert.equal(JSON.stringify(output).includes("supersecret123"), false);
});