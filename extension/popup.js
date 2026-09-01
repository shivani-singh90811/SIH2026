"use strict";


const statusElement =
    document.getElementById("status");

const outputElement =
    document.getElementById("output");

const scanButton =
    document.getElementById("scan");

const redactionButton =
    document.getElementById("redaction");

const screenshotButton =
    document.getElementById("screenshot");


/* ============================================================
   UI
============================================================ */

function setStatus(
    message,
    isError = false
) {

    if (!statusElement) {
        return;
    }


    statusElement.textContent =
        message;


    statusElement.style.color =
        isError
            ? "#ff5555"
            : "#ffffff";
}


function showOutput(data) {

    if (!outputElement) {
        return;
    }


    outputElement.innerHTML = "";


    const pre =
        document.createElement(
            "pre"
        );


    pre.textContent =
        JSON.stringify(
            data,
            null,
            2
        );


    pre.style.margin = "0";

    pre.style.whiteSpace =
        "pre-wrap";

    pre.style.wordBreak =
        "break-word";


    outputElement.appendChild(
        pre
    );
}


function showImagePreview(
    dataUrl,
    title,
    metadata
) {

    if (!outputElement) {
        return;
    }


    outputElement.innerHTML = "";


    const heading =
        document.createElement(
            "div"
        );


    heading.textContent =
        title;


    heading.style.fontWeight =
        "700";

    heading.style.marginBottom =
        "10px";


    const info =
        document.createElement(
            "div"
        );


    info.textContent =
        metadata;


    info.style.fontSize =
        "12px";

    info.style.marginBottom =
        "10px";

    info.style.color =
        "#b9c2d0";


    const image =
        document.createElement(
            "img"
        );


    image.src =
        dataUrl;

    image.alt =
        title;


    image.style.width =
        "100%";

    image.style.height =
        "auto";

    image.style.display =
        "block";

    image.style.borderRadius =
        "8px";

    image.style.border =
        "1px solid #263247";


    outputElement.appendChild(
        heading
    );

    outputElement.appendChild(
        info
    );

    outputElement.appendChild(
        image
    );
}


/* ============================================================
   ACTIVE TAB
============================================================ */

async function getActiveTab() {

    const tabs =
        await chrome.tabs.query({
            active: true,
            currentWindow: true
        });


    if (
        !tabs ||
        tabs.length === 0
    ) {

        throw new Error(
            "No active tab found."
        );
    }


    const tab =
        tabs[0];


    if (!tab.id) {

        throw new Error(
            "Active tab has no ID."
        );
    }


    return tab;
}


/* ============================================================
   CONTENT SCRIPT
============================================================ */

async function sendToContentScript(
    message
) {

    const tab =
        await getActiveTab();


    try {

        const response =
            await chrome.tabs.sendMessage(
                tab.id,
                message
            );


        if (!response) {

            throw new Error(
                "Content script returned no response."
            );
        }


        return response;

    } catch (error) {

        console.error(
            "[Privacy Agent Popup] Content communication failed:",
            error
        );


        throw new Error(
            "Could not communicate with the page. " +
            "Refresh the current webpage and try again."
        );
    }
}


/* ============================================================
   DOM SCAN
============================================================ */

async function scanPage() {

    try {

        setStatus(
            "Scanning page..."
        );


        const response =
            await sendToContentScript({

                type:
                    "PRIVACY_AGENT_SCAN"

            });


        if (
            response.success === false
        ) {

            throw new Error(
                response.error ||
                "DOM scan failed."
            );
        }


        showOutput(
            response
        );


        const count =
            response.statistics
                ?.totalElements ??
            response.elements
                ?.length ??
            0;


        const sensitive =
            response.statistics
                ?.sensitiveElements ??
            0;


        setStatus(
            `DOM scan complete — ${count} elements, ${sensitive} sensitive`
        );

    } catch (error) {

        console.error(
            "[Privacy Agent] DOM scan error:",
            error
        );


        setStatus(
            error.message ||
            "DOM scan failed.",
            true
        );
    }
}


/* ============================================================
   PRIVACY SCAN
============================================================ */

async function scanRedaction() {

    try {

        setStatus(
            "Scanning privacy regions..."
        );


        const response =
            await sendToContentScript({

                type:
                    "PRIVACY_AGENT_REDACTION_SCAN"

            });


        if (
            response.success === false
        ) {

            throw new Error(
                response.error ||
                "Privacy scan failed."
            );
        }


        showOutput(
            response
        );


        const count =
            response.performance
                ?.regionsFound ??
            response.regions
                ?.length ??
            0;


        const verified =
            response.privacy
                ?.verificationPassed;


        if (
            verified === false
        ) {

            setStatus(
                `Privacy scan complete — ${count} regions, verification FAILED`,
                true
            );

        } else {

            setStatus(
                `Privacy scan complete — ${count} sensitive regions`
            );
        }

    } catch (error) {

        console.error(
            "[Privacy Agent] Privacy scan error:",
            error
        );


        setStatus(
            error.message ||
            "Privacy scan failed.",
            true
        );
    }
}


/* ============================================================
   RAW SCREENSHOT
============================================================ */

async function captureScreenshot() {

    try {

        setStatus(
            "Capturing screenshot..."
        );


        const response =
            await chrome.runtime.sendMessage({

                type:
                    "PRIVACY_AGENT_CAPTURE_SCREENSHOT"

            });


        if (
            !response ||
            response.success === false
        ) {

            throw new Error(
                response?.error ||
                "Screenshot capture failed."
            );
        }


        showOutput({

            success:
                true,

            schemaVersion:
                response.schemaVersion,

            scanner:
                response.scanner,

            tab:
                response.tab,

            image: {

                format:
                    response.image
                        ?.format,

                captured:
                    response.image
                        ?.captured,

                dataUrlLength:
                    response.image
                        ?.dataUrl
                        ?.length || 0
            },

            timestamp:
                response.timestamp

        });


        setStatus(
            "Screenshot captured locally."
        );

    } catch (error) {

        console.error(
            "[Privacy Agent] Screenshot error:",
            error
        );


        setStatus(
            error.message ||
            "Screenshot capture failed.",
            true
        );
    }
}


/* ============================================================
   CAPTURE + REDACT
============================================================ */

async function captureRedactedScreenshot() {

    try {

        setStatus(
            "Checking privacy regions..."
        );


        /*
         * IMPORTANT:
         *
         * popup.js talks directly to content.js.
         * The service worker no longer does this.
         */

        const privacyResponse =
            await sendToContentScript({

                type:
                    "PRIVACY_AGENT_REDACTION_SCAN"

            });


        if (
            !privacyResponse ||
            privacyResponse.success === false
        ) {

            throw new Error(
                privacyResponse?.error ||
                "Privacy scan failed."
            );
        }


        if (
            privacyResponse.privacy
                ?.verificationPassed === false
        ) {

            throw new Error(
                "Privacy verification failed. " +
                "The screenshot will not be released."
            );
        }


        const regions =
            privacyResponse.regions || [];


        const viewport =
            privacyResponse
                .sanitizedContext
                ?.page
                ?.viewport;


        if (
            !viewport
        ) {

            throw new Error(
                "Viewport information is missing."
            );
        }


        setStatus(
            `Capturing and redacting ${regions.length} regions locally...`
        );


        /*
         * Send ONLY already-validated privacy regions
         * to the service worker.
         */

        const response =
            await chrome.runtime.sendMessage({

                type:
                    "PRIVACY_AGENT_CAPTURE_REDACTED_SCREENSHOT",

                privacyRegions:
                    regions,

                viewport
            });


        if (
            !response ||
            response.success === false
        ) {

            throw new Error(
                response?.error ||
                "Redacted screenshot failed."
            );
        }


        if (
            !response.redaction
                ?.verificationPassed
        ) {

            throw new Error(
                "Pixel redaction verification failed."
            );
        }


        showImagePreview(
            response.image.dataUrl,

            "Locally Redacted Screenshot",

            `${response.redaction.regionsRedacted} regions redacted • ` +
            `${response.redaction.regionsVerified} verified • ` +
            `verification passed`
        );


        setStatus(
            `Redaction complete — ${response.redaction.regionsRedacted} regions redacted`
        );


    } catch (error) {

        console.error(
            "[Privacy Agent] Redacted screenshot failed:",
            error
        );


        setStatus(
            error.message ||
            "Redacted screenshot failed.",
            true
        );
    }
}


/* ============================================================
   EVENTS
============================================================ */

if (scanButton) {

    scanButton.addEventListener(
        "click",
        scanPage
    );
}


if (redactionButton) {

    redactionButton.addEventListener(
        "click",
        scanRedaction
    );
}


if (screenshotButton) {

    screenshotButton.addEventListener(
        "click",
        captureScreenshot
    );
}


/*
 * Add the final button dynamically.
 */

const redactedButton =
    document.createElement(
        "button"
    );


redactedButton.id =
    "redacted-screenshot";


redactedButton.type =
    "button";


redactedButton.textContent =
    "Capture + Redact Locally";


redactedButton.style.width =
    "100%";

redactedButton.style.border =
    "0";

redactedButton.style.borderRadius =
    "12px";

redactedButton.style.padding =
    "15px";

redactedButton.style.marginBottom =
    "12px";

redactedButton.style.background =
    "#00a86b";

redactedButton.style.color =
    "#ffffff";

redactedButton.style.fontSize =
    "16px";

redactedButton.style.fontWeight =
    "700";

redactedButton.style.cursor =
    "pointer";


if (screenshotButton) {

    screenshotButton.insertAdjacentElement(
        "afterend",
        redactedButton
    );
}


redactedButton.addEventListener(
    "click",
    captureRedactedScreenshot
);


/* ============================================================
   INITIAL STATE
============================================================ */

setStatus(
    "Privacy Agent ready."
);


console.log(
    "[Privacy Agent Popup] Loaded."
);