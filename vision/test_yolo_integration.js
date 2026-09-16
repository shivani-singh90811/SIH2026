/**
 * vision/test_yolo_integration.js
 *
 * Tests for the YOLO-adapter functions added to detector.js
 * (adaptYoloDetections, yoloClassToContractType, detectWithYolo).
 * These are pure/mockable -- no browser, real model, or real image
 * is needed.
 *
 * Run with: node --test test_yolo_integration.js
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { adaptYoloDetections, yoloClassToContractType, detectWithYolo } = require("./detector.js");

test("adaptYoloDetections converts bbox object to [x1,y1,x2,y2] array", () => {
    const result = adaptYoloDetections([
        { class: "button", score: 0.9, bbox: { x1: 10.4, y1: 20.6, x2: 100.2, y2: 50.9 } },
    ]);
    assert.deepEqual(result.elements[0].bbox, [10, 21, 100, 51]);
    assert.equal(Array.isArray(result.elements[0].bbox), true);
});

test("adaptYoloDetections never invents a label from the class name", () => {
    const result = adaptYoloDetections([{ class: "password", score: 0.9, bbox: { x1: 0, y1: 0, x2: 10, y2: 10 } }]);
    assert.equal(result.elements[0].label, null);
});

test("adaptYoloDetections tags every element with source: 'vision'", () => {
    const result = adaptYoloDetections([{ class: "button", score: 0.9, bbox: { x1: 0, y1: 0, x2: 10, y2: 10 } }]);
    assert.equal(result.elements[0].source, "vision");
});

test("adaptYoloDetections keeps the raw class as an additive field_hint, not the type", () => {
    const result = adaptYoloDetections([{ class: "password", score: 0.9, bbox: { x1: 0, y1: 0, x2: 10, y2: 10 } }]);
    assert.equal(result.elements[0].field_hint, "password");
    assert.equal(result.elements[0].type, "input"); // mapped, not raw
});

test("adaptYoloDetections assigns unique sequential ids", () => {
    const result = adaptYoloDetections([
        { class: "button", score: 0.9, bbox: { x1: 0, y1: 0, x2: 10, y2: 10 } },
        { class: "input", score: 0.8, bbox: { x1: 20, y1: 0, x2: 30, y2: 10 } },
    ]);
    assert.deepEqual(result.elements.map((e) => e.id), ["vision_yolo_001", "vision_yolo_002"]);
});

test("adaptYoloDetections defaults confidence to 0 if score is missing", () => {
    const result = adaptYoloDetections([{ class: "button", bbox: { x1: 0, y1: 0, x2: 10, y2: 10 } }]);
    assert.equal(result.elements[0].confidence, 0);
});

test("adaptYoloDetections throws a clear error for non-array input", () => {
    assert.throws(() => adaptYoloDetections("not an array"), TypeError);
});

test("yoloClassToContractType maps known structural classes correctly", () => {
    assert.equal(yoloClassToContractType("button"), "button");
    assert.equal(yoloClassToContractType("checkbox"), "checkbox");
    assert.equal(yoloClassToContractType("reminder checkbox"), "checkbox");
    assert.equal(yoloClassToContractType("redio button"), "radio");
    assert.equal(yoloClassToContractType("message"), "textarea");
    assert.equal(yoloClassToContractType("dropdown"), "select");
    assert.equal(yoloClassToContractType("country dropdown"), "select");
});

test("yoloClassToContractType maps every other field-purpose class to 'input'", () => {
    for (const cls of ["password", "email-input", "phone-num", "first-name", "DOB", "otp", "zip code"]) {
        assert.equal(yoloClassToContractType(cls), "input", `${cls} should map to input`);
    }
});

test("yoloClassToContractType falls back to 'input' for an unknown class", () => {
    assert.equal(yoloClassToContractType("some-future-class"), "input");
});

test("detectWithYolo returns a clean error when no detector instance is given (fallback path)", async () => {
    const result = await detectWithYolo(null, {});
    assert.equal(result.success, false);
    assert.equal(result.error.code, "MODEL_LOAD_FAILED");
});

test("detectWithYolo returns a clean error when detection throws (model/inference failure)", async () => {
    const fakeDetector = { detect: async () => { throw new Error("model not loaded"); } };
    const result = await detectWithYolo(fakeDetector, {});
    assert.equal(result.success, false);
    assert.equal(result.error.code, "VISION_INFERENCE_FAILED");
});

test("detectWithYolo returns adapted elements on success", async () => {
    const fakeDetector = {
        detect: async () => [{ class: "button", score: 0.95, bbox: { x1: 0, y1: 0, x2: 50, y2: 20 } }],
    };
    const result = await detectWithYolo(fakeDetector, {});
    assert.equal(result.success, true);
    assert.equal(result.elements.length, 1);
    assert.equal(result.elements[0].type, "button");
});