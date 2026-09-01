/**
 * agent/executor.js
 *
 * Browser Agent stage of the pipeline (docs/api.md sections 10-14, 18,
 * 20): takes a single structured action returned by the backend
 * (click / type / scroll / wait) and executes it safely in the page.
 *
 * Security rules this file enforces (docs/api.md section 10, 19):
 *   - No arbitrary JavaScript execution. Every action maps to a fixed,
 *     hardcoded DOM call (`.click()`, `.value =`, `dispatchEvent`,
 *     `scrollBy`, `setTimeout`) -- nothing from the action payload is
 *     ever eval()'d, `new Function()`'d, or otherwise executed as code.
 *   - Only click, type, scroll, wait are supported. Anything else is
 *     rejected as INVALID_ACTION.
 *   - Privacy rule (section 12): a `type` action's `value` is never
 *     logged or included in any error/result message.
 *
 * This file works in two environments without any build step or
 * external dependency:
 *   - Browser (content script): attaches itself to
 *     `window.BrowserAgentExecutor`.
 *   - Node (tests): exported via `module.exports` so
 *     test_executor.js can require() it directly and inject a fake
 *     `domProvider`, with no real DOM/browser needed.
 *
 * NOTE for ShivaSai / integration: `locateElement` matches an action's
 * `target` against the `elements` list's `id`/`label` (docs/api.md
 * section 2/3). To resolve that to a real DOM node, this module first
 * looks for a `data-agent-id="<id>"` attribute -- if the
 * extension/vision module doesn't attach that yet, it falls back to
 * `elementFromPoint` using the element's bbox center, which works
 * today without any extra tagging. Attaching `data-agent-id` when
 * elements are built will make targeting more reliable and should be
 * discussed as a small addition to /extension.
 */

(function (root, factory) {
    "use strict";
    const mod = factory();
    if (typeof module !== "undefined" && module.exports) {
        module.exports = mod; // Node (tests)
    } else {
        root.BrowserAgentExecutor = mod; // Browser (content script)
    }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    const SUPPORTED_ACTION_TYPES = ["click", "type", "scroll", "wait"];
    const SCROLL_DIRECTIONS = ["up", "down", "left", "right"];

    function errorResult(code, message) {
        return { success: false, error: { code, message } };
    }

    function successResult(executed) {
        // docs/api.md does not define an agent-execution-result shape;
        // this mirrors the contract's existing {success, ...} / error
        // convention (section 15) for consistency. Flag with the
        // integration lead if a specific evaluation-logging format is
        // expected instead (see README).
        return { success: true, executed };
    }

    /**
     * Match an action's target string against the elements list
     * (docs/api.md sections 2 & 3: id, type, label, bbox, visible,
     * interactive). Prefers an exact id match, then an exact label
     * match, then a case-insensitive partial label match -- this is
     * the metadata-matching step only; it never touches the DOM.
     *
     * Returns the matching element object, or null.
     */
    function locateElement(target, elements) {
        if (!target || !Array.isArray(elements) || elements.length === 0) {
            return null;
        }

        const candidates = elements.filter((el) => el.visible !== false && el.interactive !== false);
        const pool = candidates.length > 0 ? candidates : elements;

        const byId = pool.find((el) => el.id === target);
        if (byId) return byId;

        const targetLower = String(target).trim().toLowerCase();

        const exactLabel = pool.find(
            (el) => (el.label || "").trim().toLowerCase() === targetLower
        );
        if (exactLabel) return exactLabel;

        const partialLabel = pool.find((el) => {
            const label = (el.label || "").trim().toLowerCase();
            return label.length > 0 && (label.includes(targetLower) || targetLower.includes(label));
        });
        return partialLabel || null;
    }

    /**
     * Resolve an element's metadata (from locateElement) to a real DOM
     * node. Tries a `data-agent-id` tag first (best case, if the
     * extension attaches one), then falls back to the bbox center via
     * elementFromPoint -- which works with today's contract fields
     * alone, no extension changes required.
     */
    function resolveDomNode(elementMeta, domProvider) {
        if (!elementMeta || !domProvider) return null;

        if (typeof domProvider.querySelector === "function") {
            const tagged = domProvider.querySelector(`[data-agent-id="${elementMeta.id}"]`);
            if (tagged) return tagged;
        }

        if (Array.isArray(elementMeta.bbox) && elementMeta.bbox.length === 4 && typeof domProvider.elementFromPoint === "function") {
            const [x1, y1, x2, y2] = elementMeta.bbox;
            const centerX = Math.round((x1 + x2) / 2);
            const centerY = Math.round((y1 + y2) / 2);
            const node = domProvider.elementFromPoint(centerX, centerY);
            if (node) return node;
        }

        return null;
    }

    function dispatchInputEvents(node) {
        // Fires standard, framework-friendly events (React/Vue-style
        // controlled inputs listen for these) -- still just native
        // Event objects, never arbitrary code.
        node.dispatchEvent(new Event("input", { bubbles: true }));
        node.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function executeClick(action, elements, domProvider) {
        const elementMeta = locateElement(action.target, elements);
        if (!elementMeta) {
            return errorResult("TARGET_NOT_FOUND", `No element found matching target: ${action.target}`);
        }
        const node = resolveDomNode(elementMeta, domProvider);
        if (!node) {
            return errorResult("TARGET_NOT_FOUND", `Element metadata matched but no DOM node could be resolved for: ${action.target}`);
        }
        if (node.disabled) {
            return errorResult("ACTION_EXECUTION_FAILED", `Target element is disabled: ${action.target}`);
        }
        try {
            node.click();
        } catch (err) {
            return errorResult("ACTION_EXECUTION_FAILED", `click() threw: ${err.message}`);
        }
        return successResult({ type: "click", target: action.target });
    }

    function executeType(action, elements, domProvider) {
        const elementMeta = locateElement(action.target, elements);
        if (!elementMeta) {
            return errorResult("TARGET_NOT_FOUND", `No element found matching target: ${action.target}`);
        }
        const node = resolveDomNode(elementMeta, domProvider);
        if (!node) {
            return errorResult("TARGET_NOT_FOUND", `Element metadata matched but no DOM node could be resolved for: ${action.target}`);
        }

        const tagName = (node.tagName || "").toUpperCase();
        const isTextEnterable = tagName === "INPUT" || tagName === "TEXTAREA" || node.isContentEditable;
        if (!isTextEnterable) {
            return errorResult("ACTION_EXECUTION_FAILED", `Target element is not a text-enterable field: ${action.target}`);
        }
        if (node.disabled) {
            return errorResult("ACTION_EXECUTION_FAILED", `Target element is disabled: ${action.target}`);
        }

        try {
            if (node.isContentEditable && tagName !== "INPUT" && tagName !== "TEXTAREA") {
                node.textContent = action.value;
            } else {
                node.value = action.value;
            }
            dispatchInputEvents(node);
        } catch (err) {
            // Privacy rule (section 12): never include action.value here.
            return errorResult("ACTION_EXECUTION_FAILED", `type action failed for target: ${action.target}`);
        }

        // Privacy rule (section 12): the typed value is never included
        // in the result, logged, or echoed back.
        return successResult({ type: "type", target: action.target });
    }

    function executeScroll(action, domProvider) {
        if (!SCROLL_DIRECTIONS.includes(action.direction)) {
            return errorResult("INVALID_ACTION", `Unsupported scroll direction: ${action.direction}`);
        }
        if (typeof action.amount !== "number" || action.amount <= 0) {
            return errorResult("INVALID_ACTION", "scroll amount must be a positive number");
        }

        const win = (domProvider && domProvider.window) || (typeof window !== "undefined" ? window : null);
        if (!win || typeof win.scrollBy !== "function") {
            return errorResult("ACTION_EXECUTION_FAILED", "No scrollable window available.");
        }

        const dx = action.direction === "left" ? -action.amount : action.direction === "right" ? action.amount : 0;
        const dy = action.direction === "down" ? action.amount : action.direction === "up" ? -action.amount : 0;

        try {
            win.scrollBy(dx, dy);
        } catch (err) {
            return errorResult("ACTION_EXECUTION_FAILED", `scrollBy() threw: ${err.message}`);
        }
        return successResult({ type: "scroll", direction: action.direction, amount: action.amount });
    }

    function executeWait(action, timerProvider) {
        if (typeof action.duration !== "number" || action.duration <= 0) {
            return Promise.resolve(errorResult("INVALID_ACTION", "wait duration must be a positive number (ms)"));
        }
        const setTimeoutFn = (timerProvider && timerProvider.setTimeout) || (typeof setTimeout !== "undefined" ? setTimeout : null);
        if (!setTimeoutFn) {
            return Promise.resolve(errorResult("ACTION_EXECUTION_FAILED", "No timer available."));
        }
        return new Promise((resolve) => {
            setTimeoutFn(() => resolve(successResult({ type: "wait", duration: action.duration })), action.duration);
        });
    }

    /**
     * Execute a single structured action (docs/api.md sections 10-14).
     *
     * Args:
     *   action: { type: "click"|"type"|"scroll"|"wait", ... } as
     *     returned by the backend response (docs/api.md section 9).
     *   elements: the elements list from DOM perception / local vision
     *     (docs/api.md sections 2 & 3) used to resolve click/type targets.
     *   domProvider: optional. Defaults to the real `document`/`window`
     *     in a browser. Tests inject a fake object with
     *     `querySelector`, `elementFromPoint`, `window.scrollBy`, and
     *     `setTimeout` instead of touching real globals.
     *
     * Returns:
     *   A Promise resolving to { success: true, executed: {...} } or
     *   { success: false, error: { code, message } }, using the same
     *   error codes as the rest of the contract (section 16).
     */
    async function executeAction(action, elements, domProvider) {
        const effectiveDom =
            domProvider ||
            (typeof document !== "undefined"
                ? { querySelector: document.querySelector.bind(document), elementFromPoint: document.elementFromPoint.bind(document), window: typeof window !== "undefined" ? window : undefined }
                : null);

        if (!action || typeof action !== "object" || !SUPPORTED_ACTION_TYPES.includes(action.type)) {
            return errorResult(
                "INVALID_ACTION",
                `Unsupported or missing action type. Supported: ${SUPPORTED_ACTION_TYPES.join(", ")}`
            );
        }

        try {
            switch (action.type) {
                case "click":
                    return executeClick(action, elements, effectiveDom);
                case "type":
                    return executeType(action, elements, effectiveDom);
                case "scroll":
                    return executeScroll(action, effectiveDom);
                case "wait":
                    return await executeWait(action, effectiveDom);
                default:
                    return errorResult("INVALID_ACTION", `Unsupported action type: ${action.type}`);
            }
        } catch (err) {
            return errorResult("ACTION_EXECUTION_FAILED", `Unexpected error executing ${action.type}: ${err.message}`);
        }
    }

    return {
        executeAction,
        locateElement, // exported for direct unit testing
        resolveDomNode, // exported for direct unit testing
        SUPPORTED_ACTION_TYPES,
    };
});
