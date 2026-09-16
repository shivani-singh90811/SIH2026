/**
 * vision/yolo-detector.js
 *
 * ============================================================
 * ADAPTED FROM: arifmoin522-a11y/ui-detection-browser
 *               (public/js/detector.js)
 * ============================================================
 * The core algorithm (preprocessing, inference call, NMS, IoU) is
 * Arif's real, working implementation -- NOT rewritten. What changed
 * from his original file, and why:
 *
 *   1. `ort` is no longer assumed to come from a CDN <script> tag.
 *      Manifest V3 extensions cannot load remotely-hosted executable
 *      code (Chrome policy) -- `ort.min.js` must be bundled inside
 *      the extension and loaded via a local <script>/content_scripts
 *      entry instead. This file still just uses the global `ort`
 *      object; only *where that global comes from* changed, which is
 *      a manifest.json/loading concern, not a change to this file.
 *   2. `modelPath` is now expected to be a fully-resolved URL (e.g.
 *      built with `chrome.runtime.getURL(...)` by the caller) rather
 *      than a relative string like "model/ui-detection.onnx" --
 *      content scripts don't resolve relative paths against the
 *      extension's own root the way a normal page would.
 *   3. `drawDetections()` (canvas-preview drawing for his standalone
 *      demo page) was dropped -- not needed inside the extension.
 *   4. Pure, DOM/ORT-independent math (`computeIoU`, `nms`) is
 *      exported separately so it can be unit-tested in Node without
 *      a browser, a real model, or a real image.
 *
 * Class list, thresholds, preprocessing math, and postprocessing math
 * are otherwise identical to the original.
 */

(function (root, factory) {
    "use strict";
    const mod = factory();
    if (typeof module !== "undefined" && module.exports) {
        module.exports = mod; // Node (tests -- math helpers only)
    } else {
        root.UIDetector = mod.UIDetector; // Browser (content script)
        root.YoloDetectorMath = mod.YoloDetectorMath; // exposed for consistency/testing
    }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    // Exact class list from the real model
    // (foduucom/web-form-ui-field-detection) -- order matters, it
    // must match the model's own output ordering. Includes the
    // dataset's own naming (e.g. "redio button") verbatim.
    const CLASSES = [
        "DOB", "address", "age input", "age", "button", "checkbox",
        "city", "company", "country dropdown", "country input", "date",
        "day dropdown", "doc-upload", "dropdown", "email-input", "emp id",
        "first-name", "gender dropdown", "gender", "input", "job role",
        "last-name", "message", "month dropdown", "name", "otp",
        "password", "phone-num", "redio button", "region",
        "reminder checkbox", "state dropdown", "state input-", "state",
        "terms checkbox", "username", "web url-", "year dropdown", "zip code"
    ];

    function computeIoU(a, b) {
        const x1 = Math.max(a.x1, b.x1);
        const y1 = Math.max(a.y1, b.y1);
        const x2 = Math.min(a.x2, b.x2);
        const y2 = Math.min(a.y2, b.y2);

        const intersection = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
        const areaA = (a.x2 - a.x1) * (a.y2 - a.y1);
        const areaB = (b.x2 - b.x1) * (b.y2 - b.y1);

        return intersection / (areaA + areaB - intersection + 1e-6);
    }

    function nms(detections, iouThreshold) {
        const sorted = [...detections].sort((a, b) => b.score - a.score);
        const n = sorted.length;
        const suppressed = new Uint8Array(n);

        for (let i = 0; i < n; i++) {
            if (suppressed[i]) continue;
            const best = sorted[i];
            for (let j = i + 1; j < n; j++) {
                if (suppressed[j]) continue;
                if (sorted[j].class !== best.class) continue;
                if (computeIoU(best.bbox, sorted[j].bbox) >= iouThreshold) {
                    suppressed[j] = 1;
                }
            }
        }

        const kept = [];
        for (let i = 0; i < n; i++) {
            if (!suppressed[i]) kept.push(sorted[i]);
        }
        return kept;
    }

    class UIDetector {
        /**
         * @param {string} modelUrl - a fully-resolved URL to the
         *   .onnx model file (e.g. chrome.runtime.getURL("model/ui-detection.onnx")
         *   inside the extension; a plain relative/absolute path also
         *   works outside an extension context).
         */
        constructor(modelUrl) {
            if (!modelUrl) {
                throw new Error("UIDetector requires a resolved model URL (see class docstring).");
            }
            this.modelUrl = modelUrl;
            this.session = null;
            this.inputShape = [1, 3, 640, 640];
            this.confThreshold = 0.25;
            this.iouThreshold = 0.45;
        }

        async loadModel() {
            if (typeof ort === "undefined") {
                throw new Error(
                    "ONNX Runtime Web ('ort') is not loaded. It must be bundled locally " +
                    "and loaded before yolo-detector.js -- see extension/lib/ort/ and " +
                    "manifest.json's content_scripts order. CDN loading is not allowed " +
                    "in a Manifest V3 extension."
                );
            }
            console.log("[Vision] Loading YOLO model from", this.modelUrl);
            try {
                this.session = await ort.InferenceSession.create(this.modelUrl, {
                    executionProviders: ["wasm"],
                    graphOptimizationLevel: "all"
                });
            } catch (error) {
                throw new Error(
                    `[Vision] Failed to load ONNX model at ${this.modelUrl}. ` +
                    `Confirm the file exists (see extension/lib/ort/README.md) and the ` +
                    `path was resolved with chrome.runtime.getURL(). Original error: ${error.message}`
                );
            }
            console.log("[Vision] Model loaded successfully");
            return true;
        }

        preprocess(imageElement) {
            const canvas = document.createElement("canvas");
            const [, channels, height, width] = this.inputShape;
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext("2d");

            const scale = Math.min(width / imageElement.width, height / imageElement.height);
            const offsetX = (width - imageElement.width * scale) / 2;
            const offsetY = (height - imageElement.height * scale) / 2;

            ctx.fillStyle = "#000";
            ctx.fillRect(0, 0, width, height);
            ctx.drawImage(imageElement, offsetX, offsetY, imageElement.width * scale, imageElement.height * scale);

            const imageData = ctx.getImageData(0, 0, width, height);
            const pixels = new Uint32Array(imageData.data.buffer);
            const channelSize = height * width;
            const float32Data = new Float32Array(channels * channelSize);

            for (let i = 0; i < channelSize; i++) {
                const p = pixels[i];
                float32Data[i] = (p & 0xff) / 255.0;
                float32Data[channelSize + i] = ((p >> 8) & 0xff) / 255.0;
                float32Data[2 * channelSize + i] = ((p >> 16) & 0xff) / 255.0;
            }

            return {
                tensor: new ort.Tensor("float32", float32Data, this.inputShape),
                scale, offsetX, offsetY,
                origWidth: imageElement.width,
                origHeight: imageElement.height
            };
        }

        async detect(imageElement) {
            if (!this.session) {
                throw new Error("Model not loaded. Call loadModel() first.");
            }

            console.log("[Vision] Running local YOLO inference (no network request)...");
            const started = performance.now();

            const { tensor, scale, offsetX, offsetY, origWidth, origHeight } = this.preprocess(imageElement);

            const inputName = this.session.inputNames[0];
            const results = await this.session.run({ [inputName]: tensor });
            const outputName = this.session.outputNames[0];
            const output = results[outputName];

            const detections = this.postprocess(output.data, scale, offsetX, offsetY, origWidth, origHeight);

            console.log(
                `[Vision] Inference complete in ${(performance.now() - started).toFixed(0)}ms -- ` +
                `${detections.length} detection(s) after NMS`
            );

            return detections;
        }

        postprocess(data, scale, offsetX, offsetY, origWidth, origHeight) {
            const detections = [];
            const numDetections = data.length / (CLASSES.length + 4);

            for (let i = 0; i < numDetections; i++) {
                const base = i * (CLASSES.length + 4);
                const cx = data[base];
                const cy = data[base + 1];
                const w = data[base + 2];
                const h = data[base + 3];

                let maxScore = 0;
                let maxClassIdx = 0;
                for (let j = 0; j < CLASSES.length; j++) {
                    const score = data[base + 4 + j];
                    if (score > maxScore) {
                        maxScore = score;
                        maxClassIdx = j;
                    }
                }

                if (maxScore < this.confThreshold) continue;

                const x1 = (cx - w / 2 - offsetX) / scale;
                const y1 = (cy - h / 2 - offsetY) / scale;
                const x2 = (cx + w / 2 - offsetX) / scale;
                const y2 = (cy + h / 2 - offsetY) / scale;

                detections.push({
                    class: CLASSES[maxClassIdx],
                    classIdx: maxClassIdx,
                    score: maxScore,
                    bbox: {
                        x1: Math.max(0, x1),
                        y1: Math.max(0, y1),
                        x2: Math.min(origWidth, x2),
                        y2: Math.min(origHeight, y2)
                    }
                });
            }

            return nms(detections, this.iouThreshold);
        }
    }

    return {
        UIDetector,
        CLASSES,
        YoloDetectorMath: { computeIoU, nms } // pure functions, testable without a browser
    };
});