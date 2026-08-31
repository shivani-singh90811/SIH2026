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

    return {
        buildVisionOutput,
        classifyElement, // exported for direct unit testing
        extractLabel, // exported for direct unit testing
        isVisible, // exported for direct unit testing
    };
});