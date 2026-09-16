/**
 * vision/test_yolo_detector.js
 *
 * Tests the parts of yolo-detector.js that don't need a browser, a
 * real ONNX model, or ONNX Runtime Web: the IoU and NMS math. The
 * model-loading/inference/preprocessing parts need a real browser
 * (canvas, ort, an actual .onnx file) and are covered by the manual
 * browser test procedure instead (see extension/lib/ort/README.md).
 *
 * Run with: node --test test_yolo_detector.js
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { YoloDetectorMath, CLASSES } = require("./yolo-detector.js");
const { computeIoU, nms } = YoloDetectorMath;

test("CLASSES has 39 entries matching the real model's class count", () => {
    assert.equal(CLASSES.length, 39);
});

test("computeIoU is 1.0 for identical boxes", () => {
    const box = { x1: 10, y1: 10, x2: 50, y2: 50 };
    assert.ok(Math.abs(computeIoU(box, box) - 1.0) < 1e-6);
});

test("computeIoU is 0 for non-overlapping boxes", () => {
    const a = { x1: 0, y1: 0, x2: 10, y2: 10 };
    const b = { x1: 100, y1: 100, x2: 110, y2: 110 };
    assert.equal(computeIoU(a, b), 0);
});

test("computeIoU is between 0 and 1 for partially overlapping boxes", () => {
    const a = { x1: 0, y1: 0, x2: 10, y2: 10 };
    const b = { x1: 5, y1: 5, x2: 15, y2: 15 };
    const iou = computeIoU(a, b);
    assert.ok(iou > 0 && iou < 1);
});

test("nms keeps the highest-confidence box and suppresses overlapping same-class boxes", () => {
    const detections = [
        { class: "button", score: 0.6, bbox: { x1: 0, y1: 0, x2: 100, y2: 40 } },
        { class: "button", score: 0.9, bbox: { x1: 2, y1: 2, x2: 98, y2: 38 } }, // overlaps the above heavily
    ];
    const kept = nms(detections, 0.45);
    assert.equal(kept.length, 1);
    assert.equal(kept[0].score, 0.9);
});

test("nms does not suppress boxes of different classes even if they overlap", () => {
    const detections = [
        { class: "button", score: 0.9, bbox: { x1: 0, y1: 0, x2: 100, y2: 40 } },
        { class: "input", score: 0.8, bbox: { x1: 2, y1: 2, x2: 98, y2: 38 } },
    ];
    const kept = nms(detections, 0.45);
    assert.equal(kept.length, 2);
});

test("nms does not suppress boxes that don't overlap", () => {
    const detections = [
        { class: "button", score: 0.9, bbox: { x1: 0, y1: 0, x2: 10, y2: 10 } },
        { class: "button", score: 0.8, bbox: { x1: 500, y1: 500, x2: 510, y2: 510 } },
    ];
    const kept = nms(detections, 0.45);
    assert.equal(kept.length, 2);
});