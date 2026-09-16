/**
 * vision/detector.js
 *
 * MVP stand-in for the Local Vision stage in docs/api.md's pipeline
 * (section 18: "DOM Perception + Local Vision"). No real on-device
 * vision model (ONNX/WebGPU) is wired up yet -- this scans the DOM
 * directly and reformats what it finds into the exact "Local Vision
 * Output" shape from docs/api.md section 3, so the rest of the
 * pipeline (privacy, backend, agent) can be built and tested against
 * a real element list today.
 *
 * Written so a real vision model can replace `scanDocument()`'s
 * internals later without changing `buildVisionOutput()`'s public
 * shape or the rest of the pipeline.
 *
 * Same dual-environment pattern as /agent/executor.js:
 *   - Browser: attaches to `window.LocalVisionDetector`.
 *   - Node (tests): exported via `module.exports`, tested against
 *     small hand-written fake DOM node objects -- no jsdom needed.
 *
 * Security note: this module only reads structural/visual DOM info
 * (tag names, visible text, bounding boxes) -- the same category of
 * "safe DOM/UI information" docs/api.md section 2 already allows the
 * extension to collect. It never reads input/textarea values (only
 * aria-label/placeholder are used as a label source for those, never
 * the entered content -- see extractLabel), and it never sends
 * anything anywhere (no network calls in this file).
 */

(function (root, factory) {
    "use strict";
    const mod = factory();
    if (typeof module !== "undefined" && module.exports) {
        module.exports = mod; // Node (tests)
    } else {
        root.LocalVisionDetector = mod; // Browser (content script)
    }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    // Tags that get their own element and are NOT descended into
    // further (avoids double-reporting text inside a button as a
    // separate "text" element, etc.).
    const LEAF_TAGS = new Set(["BUTTON", "INPUT", "TEXTAREA", "SELECT", "IMG"]);

    // Rule-based "confidence": this is deterministic tag/attribute
    // matching, not a trained model's probability. Definitive tag
    // matches get a high, fixed value; heuristic text/role
    // classification (see classifyElement) gets a lower one to reflect
    // the extra uncertainty -- see README "Limitations".
    const CONFIDENCE = {
        definitive: 0.98,
        heuristic: 0.65,
    };

    /**
     * Classify a DOM node into one of docs/api.md section 2's element
     * types, or null if it isn't one the fallback recognizes.
     *
     * Expects a DOM-like node: `.tagName`, `.getAttribute(name)`,
     * `.type` (for inputs), `.href` (for anchors), `.children`
     * (array-like), `.textContent`.
     */
    function classifyElement(node) {
        const tag = (node.tagName || "").toUpperCase();

        if (tag === "BUTTON") return { type: "button", confidence: CONFIDENCE.definitive };

        if (tag === "INPUT") {
            const inputType = (node.type || "text").toLowerCase();
            if (inputType === "checkbox") return { type: "checkbox", confidence: CONFIDENCE.definitive };
            if (inputType === "radio") return { type: "radio", confidence: CONFIDENCE.definitive };
            if (inputType === "button" || inputType === "submit" || inputType === "reset") {
                return { type: "button", confidence: CONFIDENCE.definitive };
            }
            return { type: "input", confidence: CONFIDENCE.definitive };
        }

        if (tag === "TEXTAREA") return { type: "textarea", confidence: CONFIDENCE.definitive };
        if (tag === "SELECT") return { type: "select", confidence: CONFIDENCE.definitive };
        if (tag === "IMG") return { type: "image", confidence: CONFIDENCE.definitive };
        if (tag === "FORM") return { type: "form", confidence: CONFIDENCE.definitive };

        if (tag === "A" && node.getAttribute && node.getAttribute("href")) {
            return { type: "link", confidence: CONFIDENCE.definitive };
        }

        if (/^H[1-6]$/.test(tag)) return { type: "heading", confidence: CONFIDENCE.heuristic };

        // Generic leaf text: an element with direct text and no child
        // elements is heuristically "text" -- not a definitive tag
        // match, hence the lower confidence.
        const hasElementChildren = Array.isArray(node.children) && node.children.length > 0;
        const text = (node.textContent || "").trim();
        if (!hasElementChildren && text.length > 0) {
            return { type: "text", confidence: CONFIDENCE.heuristic };
        }

        return null;
    }

    /**
     * Best-effort accessible label for an element, checked in a fixed
     * priority order. Returns null if nothing usable is found.
     */
    function extractLabel(node, type) {
        const ariaLabel = node.getAttribute && node.getAttribute("aria-label");
        if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();

        if (type === "image") {
            const alt = node.getAttribute && node.getAttribute("alt");
            if (alt && alt.trim()) return alt.trim();
            return null;
        }

        if (type === "input" || type === "textarea") {
            const placeholder = node.getAttribute && node.getAttribute("placeholder");
            if (placeholder && placeholder.trim()) return placeholder.trim();
            // Deliberately never falls back to node.value here: unlike a
            // button's static markup value, an input/textarea's value is
            // user-entered content (which may be a password, email, or
            // any other sensitive text) and must never be surfaced as a
            // "label" in vision output.
            return null;
        }

        const text = (node.textContent || "").trim();
        if (text) return text.length > 80 ? text.slice(0, 80) + "..." : text;

        if ((type === "button") && node.value && String(node.value).trim()) {
            return String(node.value).trim();
        }

        return null;
    }

    /**
     * Visibility check. Uses `offsetParent` (null when display:none or
     * detached) plus a non-zero bounding box -- a reasonable MVP
     * heuristic; it will not catch every case (e.g. position:fixed
     * elements report a null offsetParent in some browsers, and
     * visibility:hidden / opacity:0 aren't checked here). See README.
     */
    function isVisible(node) {
        if (node.offsetParent === null && node.offsetParent !== undefined) {
            return false;
        }
        const rect = typeof node.getBoundingClientRect === "function" ? node.getBoundingClientRect() : null;
        if (!rect) return false;
        return rect.width > 0 && rect.height > 0;
    }

    function bboxFromRect(rect) {
        return [
            Math.round(rect.left),
            Math.round(rect.top),
            Math.round(rect.right),
            Math.round(rect.bottom),
        ];
    }

    /**
     * Walk a DOM (sub)tree and return a flat list of recognized
     * elements in docs/api.md section 3's shape (minus `id`, assigned
     * by the caller so ids stay unique across the whole scan).
     *
     * `root` must expose `.children` (array-like) recursively, plus
     * the per-node properties classifyElement/extractLabel/isVisible
     * use above. In a browser this is a real Element; in tests it's a
     * small plain-object tree.
     */
    function scanNode(node, results) {
        if (!node) return;

        const classification = classifyElement(node);
        if (classification && isVisible(node)) {
            const rect = node.getBoundingClientRect();
            results.push({
                type: classification.type,
                label: extractLabel(node, classification.type),
                bbox: bboxFromRect(rect),
                confidence: classification.confidence,
            });
        }

        // Don't descend into a recognized leaf's children (its inner
        // text/icon markup isn't a separate element) -- but do descend
        // into containers (form, heading wrapper, or unclassified div)
        // so nested real elements are still found.
        const tag = (node.tagName || "").toUpperCase();
        if (classification && LEAF_TAGS.has(tag)) return;

        const children = node.children || [];
        for (let i = 0; i < children.length; i++) {
            scanNode(children[i], results);
        }
    }

    /**
     * Scan a document (or any root node) and return docs/api.md
     * section 3's exact output shape:
     *   { elements: [{ id, type, label, bbox, confidence }, ...] }
     */
    function buildVisionOutput(root) {
        const rawResults = [];
        const rootNode = root && root.body ? root.body : root; // accept a Document or an Element
        scanNode(rootNode, rawResults);

        const elements = rawResults.map((el, index) => ({
            id: `vision_${String(index + 1).padStart(3, "0")}`,
            type: el.type,
            label: el.label,
            bbox: el.bbox,
            confidence: el.confidence,
        }));

        return { elements };
    }


    /* ============================================================
       YOLO INTEGRATION (adapted from arifmoin522-a11y/ui-detection-browser)
    ============================================================ */

    /*
     * This section does NOT touch anything above it. It adapts the
     * real YOLOv8s detector's raw output (see yolo-detector.js,
     * loaded as a separate script -- content_scripts order in
     * manifest.json) into the EXACT SAME contract shape as
     * buildVisionOutput() above, so callers (the extension, /server,
     * /agent) see one consistent format regardless of which
     * perception source produced it.
     *
     * bbox stays [x1, y1, x2, y2] -- this is the contract already
     * used by /privacy, /server, /agent and buildVisionOutput() above;
     * it is not changed here.
     */

    // Maps the real model's 39 field-purpose classes
    // (foduucom/web-form-ui-field-detection) to the 12 generic
    // element types from docs/api.md section 2. Everything not listed
    // is some flavor of a single-line input field.
    const YOLO_CLASS_TO_TYPE = {
        button: "button",
        checkbox: "checkbox",
        "reminder checkbox": "checkbox",
        "terms checkbox": "checkbox",
        "redio button": "radio", // verbatim dataset class name (typo preserved intentionally)
        message: "textarea",
        dropdown: "select",
        "country dropdown": "select",
        "day dropdown": "select",
        "month dropdown": "select",
        "year dropdown": "select",
        "state dropdown": "select",
        "gender dropdown": "select",
    };

    function yoloClassToContractType(yoloClass) {
        return YOLO_CLASS_TO_TYPE[yoloClass] || "input";
    }

    function yoloBboxToArray(bbox) {
        return [
            Math.round(bbox.x1),
            Math.round(bbox.y1),
            Math.round(bbox.x2),
            Math.round(bbox.y2),
        ];
    }

    /**
     * Adapt yolo-detector.js's raw detect() output into this file's
     * contract shape. Pure function -- no browser/model/image needed,
     * fully unit-testable.
     *
     * @param {Array<{class, score, bbox: {x1,y1,x2,y2}}>} rawDetections
     * @returns {{elements: Array}}
     */
    function adaptYoloDetections(rawDetections) {
        if (!Array.isArray(rawDetections)) {
            throw new TypeError("adaptYoloDetections expects an array (yolo-detector.js's detect() output)");
        }

        const elements = rawDetections.map((det, index) => ({
            id: `vision_yolo_${String(index + 1).padStart(3, "0")}`,
            type: yoloClassToContractType(det.class),
            // YOLO detects field *purpose*, not visible text -- never
            // invent a label from the class name. A DOM/fusion layer
            // (out of scope here) can fill this in from accessible
            // DOM info when available.
            label: null,
            bbox: yoloBboxToArray(det.bbox),
            confidence: typeof det.score === "number" ? det.score : 0,
            source: "vision",
            field_hint: det.class, // additive, non-contract: raw model class, for future privacy/fusion use
        }));

        return { elements };
    }

    /**
     * Safe orchestration wrapper: runs YOLO detection on an image
     * through an already-loaded UIDetector instance (see
     * yolo-detector.js) and adapts the result. Never throws -- if
     * detection fails for any reason (model not loaded, inference
     * error, etc.), returns a clean structured error instead of
     * crashing the caller, per the "clean fallback/error path"
     * requirement.
     *
     * @param {object} detectorInstance - an already-constructed AND
     *   loaded yolo-detector.js UIDetector instance.
     * @param {HTMLImageElement|HTMLCanvasElement} imageElement
     */
    async function detectWithYolo(detectorInstance, imageElement) {
        if (!detectorInstance) {
            return {
                success: false,
                error: { code: "MODEL_LOAD_FAILED", message: "No YOLO detector instance was provided." },
            };
        }

        try {
            const rawDetections = await detectorInstance.detect(imageElement);
            return { success: true, ...adaptYoloDetections(rawDetections) };
        } catch (error) {
            console.error("[Vision] YOLO detection failed, no detections returned:", error);
            return {
                success: false,
                error: { code: "VISION_INFERENCE_FAILED", message: error?.message || "YOLO detection failed." },
            };
        }
    }

    return {
        buildVisionOutput,
        classifyElement, // exported for direct unit testing
        extractLabel, // exported for direct unit testing
        isVisible, // exported for direct unit testing
        adaptYoloDetections, // exported for direct unit testing
        yoloClassToContractType, // exported for direct unit testing
        detectWithYolo,
    };
});