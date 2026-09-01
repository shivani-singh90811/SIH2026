"use strict";

/*
 * ============================================================
 * PRIVACY AGENT
 * DOM + PRIVACY PERCEPTION v2.9.1
 * ============================================================
 *
 * Privacy guarantees:
 *
 * - Never reads input.value
 * - Never reads textarea.value
 * - Never reads password contents
 * - Never exports contenteditable contents
 * - Detects common PII locally
 * - Sanitizes PII before output
 * - Never treats ancestor containers as sensitive regions
 * - Performs a local verification before returning context
 *
 * ============================================================
 */

const PRIVACY_AGENT_VERSION = "2.9.1";

console.log(
    "[Privacy Agent] DOM + Privacy Perception initialized",
    {
        version: PRIVACY_AGENT_VERSION
    }
);


/* ============================================================
   BASIC UTILITIES
============================================================ */

function safeText(value, maxLength = 300) {

    if (typeof value !== "string") {
        return "";
    }

    return value
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, maxLength);
}


function getTag(element) {

    return (
        element?.tagName || ""
    ).toLowerCase();
}


function isVisible(element) {

    if (!element) {
        return false;
    }

    const style =
        window.getComputedStyle(element);

    if (
        style.display === "none" ||
        style.visibility === "hidden" ||
        style.opacity === "0"
    ) {
        return false;
    }

    const rect =
        element.getBoundingClientRect();

    return (
        rect.width > 0 &&
        rect.height > 0
    );
}


function getBounds(element) {

    const rect =
        element.getBoundingClientRect();

    if (
        rect.width <= 0 ||
        rect.height <= 0
    ) {
        return null;
    }

    return {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height)
    };
}


/* ============================================================
   PII PATTERNS
============================================================ */

/*
 * Email
 */

const EMAIL_PATTERN =
    /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i;


/*
 * Phone
 *
 * Conservative enough to avoid treating every
 * short numeric string as a phone number.
 */

const PHONE_PATTERN =
    /(?:\+?\d[\d\s().-]{7,}\d)/;


/*
 * Card
 *
 * Supports common 13-19 digit card-like sequences
 * with optional spaces/hyphens.
 */

const CARD_PATTERN =
    /(?:\b\d{4}(?:[ -]\d{4}){2,3}\b|\b\d{13,19}\b)/;


/*
 * Semantic privacy keywords.
 */

const PRIVACY_KEYWORDS = [
    "password",
    "passcode",
    "pin",
    "otp",
    "cvv",
    "cvc",
    "credit card",
    "debit card",
    "card number",
    "account number",
    "bank account",
    "aadhaar",
    "aadhar",
    "pan number",
    "passport",
    "driver license",
    "driving licence",
    "social security",
    "date of birth"
];
function boundsToBbox(bounds) {
    return [
        bounds.x,
        bounds.y,
        bounds.x + bounds.width,
        bounds.y + bounds.height
    ];
}

const REASON_TO_PII_TYPE = {
    "password": "password", "otp": "otp", "pin": "pin",
    "cvv": "cvv", "cvc": "cvv",
    "credit card": "credit_card", "debit card": "debit_card",
    "card number": "credit_card", "payment-card": "credit_card",
    "account number": "account_number", "bank account": "account_number",
    "account": "account_number",
    "aadhaar": "aadhaar", "aadhar": "aadhaar",
    "pan number": "pan", "passport": "passport",
    "driver license": "driving_license", "driving licence": "driving_license",
    "social security": "other",
    "date of birth": "date_of_birth",
    "email": "email", "phone": "phone",
    "address": "personal_text", "identity": "other"
};

const REDACTION_FOR_TYPE = {
    password: "black", otp: "black", pin: "black", cvv: "black",
    pan: "black", aadhaar: "black", credit_card: "black",
    debit_card: "black", account_number: "black", passport: "black",
    driving_license: "black",
    email: "mask", phone: "mask", date_of_birth: "mask",
    face: "blur", personal_text: "black", other: "black"
};

/* ============================================================
   TEXT PRIVACY DETECTION
============================================================ */

function detectTextPrivacy(text) {

    const value =
        safeText(text, 1000);

    if (!value) {
        return [];
    }

    const lower =
        value.toLowerCase();

    const reasons = [];


    if (
        EMAIL_PATTERN.test(value)
    ) {

        reasons.push("email");
    }


    if (
        PHONE_PATTERN.test(value)
    ) {

        reasons.push("phone");
    }


    if (
        CARD_PATTERN.test(value)
    ) {

        reasons.push("payment-card");
    }


    for (
        const keyword of PRIVACY_KEYWORDS
    ) {

        if (
            lower.includes(keyword)
        ) {

            reasons.push(keyword);
        }
    }


    return [
        ...new Set(reasons)
    ];
}


/* ============================================================
   TEXT SANITIZATION
============================================================ */

function sanitizeText(text) {

    const value =
        safeText(text, 300);

    if (!value) {

        return {
            text: "",
            sensitive: false,
            reasons: []
        };
    }


    const reasons =
        detectTextPrivacy(value);


    if (
        reasons.length > 0
    ) {

        return {
            text: "[REDACTED]",
            sensitive: true,
            reasons
        };
    }


    return {
        text: value,
        sensitive: false,
        reasons: []
    };
}


/* ============================================================
   ELEMENT METADATA PRIVACY
============================================================ */

function detectSensitiveElement(element) {

    const type = (
        element.getAttribute("type") ||
        ""
    ).toLowerCase();

    const name = (
        element.getAttribute("name") ||
        ""
    ).toLowerCase();

    const id = (
        element.id ||
        ""
    ).toLowerCase();

    const placeholder = (
        element.getAttribute("placeholder") ||
        ""
    ).toLowerCase();

    const autocomplete = (
        element.getAttribute("autocomplete") ||
        ""
    ).toLowerCase();

    const ariaLabel = (
        element.getAttribute("aria-label") ||
        ""
    ).toLowerCase();


    const metadata = [
        type,
        name,
        id,
        placeholder,
        autocomplete,
        ariaLabel
    ].join(" ");


    const reasons = [];


    if (
        type === "password" ||
        metadata.includes("password") ||
        metadata.includes("passwd") ||
        metadata.includes("pwd")
    ) {

        reasons.push("password");
    }


    if (
        type === "email" ||
        metadata.includes("email") ||
        metadata.includes("e-mail")
    ) {

        reasons.push("email");
    }


    if (
        type === "tel" ||
        metadata.includes("phone") ||
        metadata.includes("mobile") ||
        metadata.includes("telephone")
    ) {

        reasons.push("phone");
    }


    if (
        metadata.includes("credit card") ||
        metadata.includes("credit-card") ||
        metadata.includes("card-number") ||
        metadata.includes("card number") ||
        metadata.includes("debit") ||
        metadata.includes("cvv") ||
        metadata.includes("cvc")
    ) {

        reasons.push("payment-card");
    }


    if (
        metadata.includes("address") ||
        metadata.includes("street") ||
        metadata.includes("postal") ||
        metadata.includes("postcode") ||
        metadata.includes("zip")
    ) {

        reasons.push("address");
    }


    if (
        metadata.includes("passport") ||
        metadata.includes("aadhaar") ||
        metadata.includes("aadhar") ||
        metadata.includes("pan") ||
        metadata.includes("identity")
    ) {

        reasons.push("identity");
    }


    if (
        metadata.includes("username") ||
        metadata.includes("user name") ||
        metadata.includes("account")
    ) {

        reasons.push("account");
    }


    if (
        reasons.length === 0
    ) {

        return null;
    }


    return {

        sensitive: true,

        reasons: [
            ...new Set(reasons)
        ]
    };
}


/* ============================================================
   ELEMENT CLASSIFICATION
============================================================ */

function getElementType(element) {

    const tag =
        getTag(element);


    switch (tag) {

        case "input":
            return "input";

        case "textarea":
            return "textarea";

        case "select":
            return "select";

        case "button":
            return "button";

        case "a":
            return "link";

        case "img":
            return "image";

        case "form":
            return "form";

        case "label":
            return "label";

        case "h1":
        case "h2":
        case "h3":
        case "h4":
        case "h5":
        case "h6":
            return "heading";

        default:
            return tag || "unknown";
    }
}


/* ============================================================
   INTERACTION RELEVANCE
============================================================ */

function isInteractionRelevant(element) {

    const tag =
        getTag(element);


    if (
        [
            "input",
            "textarea",
            "select",
            "button",
            "a"
        ].includes(tag)
    ) {

        return true;
    }


    if (
        element.isContentEditable
    ) {

        return true;
    }


    if (
        element.getAttribute("role")
    ) {

        return true;
    }


    if (
        element.hasAttribute("tabindex")
    ) {

        return true;
    }


    if (
        /^h[1-6]$/.test(tag)
    ) {

        return true;
    }


    if (
        tag === "label"
    ) {

        return true;
    }


    return false;
}


/* ============================================================
   TEXT LEAF DETECTION
============================================================ */

function isTextLeaf(element) {

    if (!element) {
        return false;
    }


    if (
        element.children.length > 0
    ) {

        return false;
    }


    const tag =
        getTag(element);


    /*
     * These elements are allowed to expose only
     * their own leaf text after sanitization.
     */

    if (
        [
            "html",
            "head",
            "body",
            "main",
            "section",
            "article",
            "div",
            "span",
            "ul",
            "ol",
            "li"
        ].includes(tag)
    ) {

        return true;
    }


    return false;
}


/* ============================================================
   DOM SCANNER
============================================================ */

function scanDOM() {

    const start =
        performance.now();


    const elements = [];

    const privacyRegions = [];


    const allElements =
        Array.from(
            document.querySelectorAll("*")
        );


    allElements.forEach(
        (element, index) => {

            if (
                !isVisible(element)
            ) {

                return;
            }


            const bounds =
                getBounds(element);


            if (!bounds) {
                return;
            }


            const tag =
                getTag(element);


            const isEditable =
                element.isContentEditable === true;


            const interactionRelevant =
                isInteractionRelevant(
                    element
                );


            const textLeaf =
                isTextLeaf(
                    element
                );


            const sensitiveMetadata =
                detectSensitiveElement(
                    element
                );


            let elementText = "";

            let textReasons = [];


            /* ==================================================
               CONTENTEDITABLE
            ================================================== */

            if (
                isEditable
            ) {

                /*
                 * NEVER expose editable contents.
                 */

                elementText =
                    "[REDACTED_EDITABLE_CONTENT]";

                textReasons.push(
                    "contenteditable"
                );
            }


            /* ==================================================
               INPUT / TEXTAREA
            ================================================== */

            else if (
                tag === "input" ||
                tag === "textarea"
            ) {

                /*
                 * NEVER read .value.
                 */

                elementText = "";
            }


            /* ==================================================
               INTERACTIVE ELEMENT
            ================================================== */

            else if (
                interactionRelevant
            ) {

                const rawText =
                    safeText(
                        element.innerText ||
                        element.textContent ||
                        "",
                        300
                    );


                const sanitized =
                    sanitizeText(
                        rawText
                    );


                elementText =
                    sanitized.text;

                textReasons =
                    sanitized.reasons;
            }


            /* ==================================================
               LEAF TEXT
            ================================================== */

            else if (
                textLeaf
            ) {

                const rawText =
                    safeText(
                        element.innerText ||
                        element.textContent ||
                        "",
                        300
                    );


                const sanitized =
                    sanitizeText(
                        rawText
                    );


                elementText =
                    sanitized.text;

                textReasons =
                    sanitized.reasons;
            }


            /* ==================================================
               STRUCTURAL CONTAINER
            ================================================== */

            else {

                /*
                 * Never export inherited descendant text.
                 */

                elementText = "";
            }


            const privacyReasons = [
                ...(sensitiveMetadata?.reasons || []),
                ...textReasons
            ];


            const uniqueReasons = [
                ...new Set(
                    privacyReasons
                )
            ];


            const isSensitive =
                uniqueReasons.length > 0;


            /*
             * Only actual sensitive elements become
             * privacy regions.
             */

            if (
                isSensitive
            ) {

                privacyRegions.push({

                    id:
                        privacyRegions.length,

                    type:
                        "dom-sensitive-region",

                    source:
                        "dom",

                    reasons:
                        uniqueReasons,

                    confidence:
                        0.98,

                    bounds

                });
            }


            /*
             * Keep only useful elements for the agent.
             */

            if (
                interactionRelevant ||
                textLeaf ||
                isSensitive
            ) {

                const elementInfo = {

                    id:
                        index,

                    type:
                        getElementType(
                            element
                        ),

                    tag,

                    text:
                        elementText,

                    ariaLabel:
                        (
                            isSensitive
                                ? "[REDACTED]"
                                : safeText(
                                    element.getAttribute(
                                        "aria-label"
                                    ) || "",
                                    200
                                )
                        ),

                    placeholder:
                        (
                            isSensitive
                                ? "[REDACTED]"
                                : safeText(
                                    element.getAttribute(
                                        "placeholder"
                                    ) || "",
                                    200
                                )
                        ),

                    role:
                        safeText(
                            element.getAttribute(
                                "role"
                            ) || "",
                            100
                        ),

                    bounds
                };


                if (
                    isSensitive
                ) {

                    elementInfo.privacy = {

                        sensitive:
                            true,

                        reasons:
                            uniqueReasons
                    };
                }


                elements.push(
                    elementInfo
                );
            }

        }
    );


    const durationMs =
        Math.round(
            (
                performance.now() -
                start
            ) * 100
        ) / 100;


    return {

        schemaVersion:
            "ui-element.v3",

        scanner: {

            type:
                "dom",

            version:
                PRIVACY_AGENT_VERSION
        },

        page: {

            url:
                window.location.origin +
                window.location.pathname,

            title:
                safeText(
                    document.title,
                    200
                ),

            viewport: {

                width:
                    window.innerWidth,

                height:
                    window.innerHeight
            }
        },

        frame: {

            elements,

            privacyRegions
        },

        statistics: {

            totalElements:
                elements.length,

            sensitiveElements:
                privacyRegions.length
        },

        performance: {

            durationMs
        },

        timestamp:
            Date.now()
    };
}


/* ============================================================
   SANITIZED CONTEXT
============================================================ */

function createSanitizedContext(
    scanResult
) {

    return {

        schemaVersion:
            "sanitized-context.v3",

        privacy: {

            sanitized:
                true,

            sensitiveElementsDetected:
                scanResult.statistics
                    .sensitiveElements
        },

        page: {

            url:
                scanResult.page.url,

            title:
                scanResult.page.title,

            viewport:
                scanResult.page.viewport
        },

        elements:
            scanResult.frame.elements,

        privacyRegions:
            scanResult.frame.privacyRegions,

        timestamp:
            Date.now()
    };
}


/* ============================================================
   PRIVACY VERIFICATION
============================================================ */

function verifySanitizedContext(
    context
) {

    /*
     * Only inspect exported element text.
     *
     * We deliberately do NOT run broad PII
     * regexes over the entire serialized object,
     * because the object contains geometry,
     * timestamps, IDs, and other non-content data.
     */

    for (
        const element of
        context.elements
    ) {

        const text =
            typeof element.text === "string"
                ? element.text
                : "";


        /* ====================================================
           CONTENTEDITABLE
        ==================================================== */

        if (
            element.privacy?.reasons
                ?.includes(
                    "contenteditable"
                )
        ) {

            if (
                text !==
                "[REDACTED_EDITABLE_CONTENT]"
            ) {

                return {

                    passed:
                        false,

                    reason:
                        "Contenteditable content was not sanitized."
                };
            }
        }


        /* ====================================================
           EMAIL
        ==================================================== */

        if (
            text !== "[REDACTED]" &&
            EMAIL_PATTERN.test(text)
        ) {

            return {

                passed:
                    false,

                reason:
                    "Email-like data remains in sanitized element text."
            };
        }


        /* ====================================================
           PHONE
        ==================================================== */

        if (
            text !== "[REDACTED]" &&
            PHONE_PATTERN.test(text)
        ) {

            return {

                passed:
                    false,

                reason:
                    "Phone-like data remains in sanitized element text."
            };
        }


        /* ====================================================
           PAYMENT CARD
        ==================================================== */

        if (
            text !== "[REDACTED]" &&
            CARD_PATTERN.test(text)
        ) {

            return {

                passed:
                    false,

                reason:
                    "Card-like data remains in sanitized element text."
            };
        }


        /* ====================================================
           SENSITIVE SEMANTIC ELEMENT
        ==================================================== */

        const reasons =
            element.privacy?.reasons || [];


        if (
            reasons.includes("password") &&
            text !== "" &&
            text !== "[REDACTED]" &&
            text !== "[REDACTED_EDITABLE_CONTENT]"
        ) {

            return {

                passed:
                    false,

                reason:
                    "Password-related element contains unsanitized text."
            };
        }

    }


    return {

        passed:
            true,

        reason:
            "Sanitized context passed local privacy verification."
    };
}


/* ============================================================
   PRIVACY SCAN
============================================================ */

function scanPrivacyRedaction() {

    const scan =
        scanDOM();


    const sanitizedContext =
        createSanitizedContext(
            scan
        );


    const verification =
        verifySanitizedContext(
            sanitizedContext
        );


    return {

        success:
            true,

        schemaVersion:
            "privacy-region.v3",

        scanner: {

            type:
                "privacy-dom",

            version:
                PRIVACY_AGENT_VERSION
        },

        regions:
            scan.frame.privacyRegions,

        performance: {

            regionsFound:
                scan.statistics
                    .sensitiveElements,

            durationMs:
                scan.performance
                    .durationMs
        },

        privacy: {

            scanCompleted:
                true,

            regionsDetected:
                scan.statistics
                    .sensitiveElements,

            /*
             * IMPORTANT:
             *
             * These are DOM-detected regions.
             * Actual screenshot/pixel redaction
             * is a later module.
             */

            regionsRedacted:
                0,

            verificationPassed:
                verification.passed,

            verificationReason:
                verification.reason
        },

        sanitizedContext,

        timestamp:
            Date.now()
    };
}


/* ============================================================
   MESSAGE HANDLER
============================================================ */

chrome.runtime.onMessage.addListener(
    (
        message,
        sender,
        sendResponse
    ) => {

        console.log(
            "[Privacy Agent] Message received:",
            message
        );


        /* ====================================================
           PING
        ==================================================== */

        if (
            message?.type ===
            "PRIVACY_AGENT_PING"
        ) {

            sendResponse({

                success:
                    true,

                ready:
                    true,

                version:
                    PRIVACY_AGENT_VERSION
            });

            return false;
        }


        /* ====================================================
           DOM SCAN
        ==================================================== */

        if (
            message?.type ===
            "PRIVACY_AGENT_SCAN"
        ) {

            try {

                const result =
                    scanDOM();


                console.log(
                    "[Privacy Agent] DOM scan complete:",
                    result.statistics
                );


                sendResponse({

                    success:
                        true,

                    ...result
                });

            } catch (error) {

                console.error(
                    "[Privacy Agent] DOM scan failed:",
                    error
                );


                sendResponse({

                    success:
                        false,

                    error:
                        error?.message ||
                        "DOM scan failed."
                });
            }


            return false;
        }


        /* ====================================================
           PRIVACY SCAN
        ==================================================== */

        if (
            message?.type ===
            "PRIVACY_AGENT_REDACTION_SCAN"
        ) {

            try {

                const result =
                    scanPrivacyRedaction();


                console.log(
                    "[Privacy Agent] Privacy scan complete:",
                    result.performance
                );


                sendResponse(
                    result
                );

            } catch (error) {

                console.error(
                    "[Privacy Agent] Privacy scan failed:",
                    error
                );


                sendResponse({

                    success:
                        false,

                    error:
                        error?.message ||
                        "Privacy scan failed."
                });
            }


            return false;
        }


        /* ====================================================
           UNKNOWN MESSAGE
        ==================================================== */

        console.warn(
            "[Privacy Agent] Unknown message type:",
            message?.type
        );


        sendResponse({

            success:
                false,

            error:
                `Unknown message type: ${message?.type}`
        });


        return false;
    }
);


/* ============================================================
   READY
============================================================ */

console.log(
    "[Privacy Agent] Content script ready."
);
