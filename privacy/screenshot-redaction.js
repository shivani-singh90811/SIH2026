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


    outputElement.textContent =
        JSON.stringify(
            data,
            null,
            2
        );
}


/*
 * Show a local screenshot preview.
 */

function showImagePreview(
    dataUrl,
    title
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


    heading.style.marginBottom =
        "10px";


    heading.style.fontWeight =
        "700";


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


    console.log(
        "[Privacy Agent Popup] Sending:",
        message
    );


    try {

        const response =
            await chrome.tabs.sendMessage(
                tab.id,
                message
            );


        console.log(
            "[Privacy Agent Popup] Response:",
            response
        );


        if (!response) {

            throw new Error(
                "Content script returned no response."
            );
        }


        return response;

    } catch (error) {

        console.error(
            "[Privacy Agent Popup] Content message failed:",
            error
        );


        throw new Error(
            "Could not communicate with the page. " +
            "Reload the webpage and try again."
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
            "[Privacy Agent] Redaction scan error:",
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
            "Capturing current page locally..."
        );


        const response =
            await chrome.runtime.sendMessage({

                type:
                    "PRIVACY_AGENT_CAPTURE_SCREENSHOT"

            });


        console.log(
            "[Privacy Agent Popup] Screenshot response:",
            response
        );


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

            viewport:
                response.viewport,

            privacyRegions:
                response.privacyRegions,

            privacyVerification:
                response.privacyVerification,

            image: {

                format:
                    response.image?.format,

                captured:
                    response.image?.captured,

                dataUrlLength:
                    response.image?.dataUrl
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
            "[Privacy Agent Popup] Screenshot error:",
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
   REDACTED SCREENSHOT
============================================================ */

async function captureRedactedScreenshot() {

    try {

        setStatus(
            "Capturing and redacting locally..."
        );


        const response =
            await chrome.runtime.sendMessage({

                type:
                    "PRIVACY_AGENT_CAPTURE_REDACTED_SCREENSHOT"

            });


        console.log(
            "[Privacy Agent Popup] Redacted screenshot response:",
            response
        );


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
                "Redaction verification failed. " +
                "The screenshot was not marked safe."
            );
        }


        /*
         * Show the actual locally redacted image.
         */

        showImagePreview(
            response.image.dataUrl,
            "Locally Redacted Screenshot"
        );


        setStatus(
            `Redaction complete — ` +
            `${response.redaction.regionsRedacted} regions redacted, ` +
            `verification passed`
        );


    } catch (error) {

        console.error(
            "[Privacy Agent Popup] Redacted screenshot error:",
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

    /*
     * Existing "Capture Current Page"
     * button continues to test raw capture.
     */

    screenshotButton.addEventListener(
        "click",
        captureScreenshot
    );
}


/*
 * Add a fourth button dynamically so you
 * don't need to modify popup.html again.
 */

const redactedScreenshotButton =
    document.createElement(
        "button"
    );


redactedScreenshotButton.id =
    "redacted-screenshot";


redactedScreenshotButton.type =
    "button";


redactedScreenshotButton.textContent =
    "Capture + Redact Locally";


redactedScreenshotButton.style.width =
    "100%";


redactedScreenshotButton.style.border =
    "0";


redactedScreenshotButton.style.borderRadius =
    "12px";


redactedScreenshotButton.style.padding =
    "15px";


redactedScreenshotButton.style.marginBottom =
    "12px";


redactedScreenshotButton.style.background =
    "#00a86b";


redactedScreenshotButton.style.color =
    "#ffffff";


redactedScreenshotButton.style.fontSize =
    "16px";


redactedScreenshotButton.style.fontWeight =
    "700";


redactedScreenshotButton.style.cursor =
    "pointer";


if (screenshotButton) {

    screenshotButton.insertAdjacentElement(
        "afterend",
        redactedScreenshotButton
    );

} else if (
    statusElement
) {

    statusElement.insertAdjacentElement(
        "beforebegin",
        redactedScreenshotButton
    );
}


redactedScreenshotButton.addEventListener(
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