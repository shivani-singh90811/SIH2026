"use strict";

/*
 * ============================================================
 * PRIVACY AGENT
 * SERVICE WORKER v3.2.1
 * ============================================================
 *
 * IMPORTANT:
 *
 * This file runs in a SERVICE WORKER.
 *
 * Therefore:
 * - document      ❌
 * - window        ❌
 * - DOM           ❌
 *
 * Allowed:
 * - chrome.* APIs
 * - OffscreenCanvas
 * - ImageBitmap
 * - fetch()
 *
 * All screenshot processing stays local.
 * ============================================================
 */

const SERVICE_VERSION = "3.2.1";


console.log(
    "[Privacy Agent] Service worker started",
    SERVICE_VERSION
);


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
   SCREENSHOT
============================================================ */

async function captureScreenshot(
    tab
) {

    const dataUrl =
        await chrome.tabs.captureVisibleTab(
            tab.windowId,
            {
                format: "png"
            }
        );


    if (!dataUrl) {

        throw new Error(
            "Screenshot capture returned no image."
        );
    }


    return dataUrl;
}


/* ============================================================
   DATA URL -> BLOB
============================================================ */

async function dataUrlToBlob(
    dataUrl
) {

    const response =
        await fetch(dataUrl);


    if (!response.ok) {

        throw new Error(
            "Could not decode screenshot."
        );
    }


    return response.blob();
}


/* ============================================================
   BLOB -> DATA URL
============================================================ */

async function blobToDataUrl(
    blob
) {

    const buffer =
        await blob.arrayBuffer();


    const bytes =
        new Uint8Array(
            buffer
        );


    const chunkSize =
        0x8000;


    let binary = "";


    for (
        let offset = 0;
        offset < bytes.length;
        offset += chunkSize
    ) {

        const chunk =
            bytes.subarray(
                offset,
                Math.min(
                    offset + chunkSize,
                    bytes.length
                )
            );


        binary +=
            String.fromCharCode(
                ...chunk
            );
    }


    return (
        `data:${blob.type};base64,` +
        btoa(binary)
    );
}


/* ============================================================
   CLAMP
============================================================ */

function clamp(
    value,
    min,
    max
) {

    return Math.max(
        min,
        Math.min(
            max,
            value
        )
    );
}


/* ============================================================
   MAP DOM REGION -> SCREENSHOT PIXELS
============================================================ */

function mapRegion(
    region,
    viewport,
    imageWidth,
    imageHeight
) {

    if (
        !region?.bounds
    ) {

        return null;
    }


    if (
        !viewport ||
        viewport.width <= 0 ||
        viewport.height <= 0
    ) {

        return null;
    }


    const scaleX =
        imageWidth /
        viewport.width;


    const scaleY =
        imageHeight /
        viewport.height;


    const padding = 2;


    const x =
        region.bounds.x *
        scaleX;


    const y =
        region.bounds.y *
        scaleY;


    const width =
        region.bounds.width *
        scaleX;


    const height =
        region.bounds.height *
        scaleY;


    const left =
        clamp(
            Math.floor(
                x - padding
            ),
            0,
            imageWidth
        );


    const top =
        clamp(
            Math.floor(
                y - padding
            ),
            0,
            imageHeight
        );


    const right =
        clamp(
            Math.ceil(
                x +
                width +
                padding
            ),
            0,
            imageWidth
        );


    const bottom =
        clamp(
            Math.ceil(
                y +
                height +
                padding
            ),
            0,
            imageHeight
        );


    if (
        right <= left ||
        bottom <= top
    ) {

        return null;
    }


    return {

        x: left,

        y: top,

        width:
            right - left,

        height:
            bottom - top
    };
}


/* ============================================================
   PIXEL CHECK
============================================================ */

function regionIsRedacted(
    ctx,
    region
) {

    if (!region) {
        return false;
    }


    const points = [

        {
            x:
                region.x +
                Math.floor(
                    region.width / 2
                ),

            y:
                region.y +
                Math.floor(
                    region.height / 2
                )
        },

        {
            x:
                region.x + 1,

            y:
                region.y + 1
        }

    ];


    for (
        const point of points
    ) {

        const x =
            clamp(
                point.x,
                0,
                ctx.canvas.width - 1
            );


        const y =
            clamp(
                point.y,
                0,
                ctx.canvas.height - 1
            );


        const pixel =
            ctx.getImageData(
                x,
                y,
                1,
                1
            ).data;


        /*
         * Black opaque mask.
         */

        const redacted =
            pixel[0] === 0 &&
            pixel[1] === 0 &&
            pixel[2] === 0 &&
            pixel[3] >= 250;


        if (!redacted) {

            return false;
        }
    }


    return true;
}


/* ============================================================
   REDACT SCREENSHOT
============================================================ */

async function redactScreenshot({

    screenshotDataUrl,

    viewport,

    privacyRegions

}) {

    const blob =
        await dataUrlToBlob(
            screenshotDataUrl
        );


    const bitmap =
        await createImageBitmap(
            blob
        );


    const canvas =
        new OffscreenCanvas(
            bitmap.width,
            bitmap.height
        );


    const ctx =
        canvas.getContext(
            "2d",
            {
                willReadFrequently: true
            }
        );


    if (!ctx) {

        bitmap.close();

        throw new Error(
            "Could not create OffscreenCanvas context."
        );
    }


    /*
     * Original screenshot.
     */

    ctx.drawImage(
        bitmap,
        0,
        0
    );


    bitmap.close();


    const mappedRegions = [];


    const regions =
        Array.isArray(
            privacyRegions
        )
            ? privacyRegions
            : [];


    /*
     * Convert all DOM coordinates
     * to screenshot coordinates.
     */

    for (
        const region of regions
    ) {

        const mapped =
            mapRegion(
                region,
                viewport,
                canvas.width,
                canvas.height
            );


        if (!mapped) {
            continue;
        }


        mappedRegions.push({

            sourceId:
                region.id,

            reasons:
                Array.isArray(
                    region.reasons
                )
                    ? region.reasons
                    : [],

            ...mapped
        });
    }


    /*
     * Black privacy mask.
     */

    ctx.fillStyle =
        "#000000";


    for (
        const region of mappedRegions
    ) {

        ctx.fillRect(
            region.x,
            region.y,
            region.width,
            region.height
        );
    }


    /*
     * Verify every region.
     */

    const verification = [];


    for (
        const region of mappedRegions
    ) {

        verification.push({

            sourceId:
                region.sourceId,

            verified:
                regionIsRedacted(
                    ctx,
                    region
                )
        });
    }


    const verificationPassed =
        verification.length === 0
            ? true
            : verification.every(
                item =>
                    item.verified
            );


    /*
     * Convert to PNG.
     */

    const redactedBlob =
        await canvas.convertToBlob({
            type: "image/png"
        });


    const redactedDataUrl =
        await blobToDataUrl(
            redactedBlob
        );


    return {

        success:
            true,

        schemaVersion:
            "redacted-screenshot.v1",

        scanner: {

            type:
                "local-pixel-redaction",

            version:
                SERVICE_VERSION
        },

        image: {

            width:
                canvas.width,

            height:
                canvas.height,

            format:
                "png",

            redacted:
                true,

            dataUrl:
                redactedDataUrl,

            dataUrlLength:
                redactedDataUrl.length
        },

        privacy: {

            regionsDetected:
                regions.length,

            regionsMapped:
                mappedRegions.length,

            regionsRedacted:
                mappedRegions.length,

            regionsVerified:
                verification.filter(
                    item =>
                        item.verified
                ).length,

            verificationPassed
        },

        regions:
            mappedRegions,

        verification,

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
            "[Privacy Agent] Service message:",
            message
        );


        /* ====================================================
           PING
        ==================================================== */

        if (
            message?.type ===
            "PRIVACY_AGENT_SERVICE_PING"
        ) {

            sendResponse({

                success:
                    true,

                ready:
                    true,

                version:
                    SERVICE_VERSION
            });


            return false;
        }


        /* ====================================================
           RAW SCREENSHOT
        ==================================================== */

        if (
            message?.type ===
            "PRIVACY_AGENT_CAPTURE_SCREENSHOT"
        ) {

            (async () => {

                try {

                    const tab =
                        await getActiveTab();


                    const dataUrl =
                        await captureScreenshot(
                            tab
                        );


                    sendResponse({

                        success:
                            true,

                        schemaVersion:
                            "screenshot.v2",

                        scanner: {

                            type:
                                "browser-screenshot",

                            version:
                                SERVICE_VERSION
                        },

                        tab: {

                            id:
                                tab.id,

                            windowId:
                                tab.windowId,

                            url:
                                tab.url || ""
                        },

                        image: {

                            format:
                                "png",

                            captured:
                                true,

                            dataUrl
                        },

                        timestamp:
                            Date.now()
                    });

                } catch (error) {

                    console.error(
                        "[Privacy Agent] Screenshot failed:",
                        error
                    );


                    sendResponse({

                        success:
                            false,

                        error:
                            error?.message ||
                            "Screenshot capture failed."
                    });
                }

            })();


            return true;
        }


        /* ====================================================
           REDACTED SCREENSHOT
        ==================================================== */

        if (
            message?.type ===
            "PRIVACY_AGENT_CAPTURE_REDACTED_SCREENSHOT"
        ) {

            (async () => {

                try {

                    const tab =
                        await getActiveTab();


                    const viewport =
                        message.viewport;


                    const privacyRegions =
                        message.privacyRegions || [];


                    if (
                        !viewport
                    ) {

                        throw new Error(
                            "Viewport information is missing."
                        );
                    }


                    /*
                     * Capture current page.
                     */

                    const rawScreenshot =
                        await captureScreenshot(
                            tab
                        );


                    /*
                     * Local redaction.
                     */

                    const result =
                        await redactScreenshot({

                            screenshotDataUrl:
                                rawScreenshot,

                            viewport,

                            privacyRegions
                        });


                    if (
                        !result.privacy
                            .verificationPassed
                    ) {

                        throw new Error(
                            "Pixel redaction verification failed."
                        );
                    }


                    sendResponse({

                        success:
                            true,

                        schemaVersion:
                            "sanitized-visual-context.v1",

                        scanner:
                            result.scanner,

                        tab: {

                            id:
                                tab.id,

                            windowId:
                                tab.windowId,

                            url:
                                tab.url || ""
                        },

                        viewport,

                        redaction:
                            result.privacy,

                        regions:
                            result.regions,

                        verification:
                            result.verification,

                        image:
                            result.image,

                        timestamp:
                            Date.now()
                    });

                } catch (error) {

                    console.error(
                        "[Privacy Agent] Redaction failed:",
                        error
                    );


                    sendResponse({

                        success:
                            false,

                        error:
                            error?.message ||
                            "Screenshot redaction failed."
                    });
                }

            })();


            return true;
        }


        sendResponse({

            success:
                false,

            error:
                "Unknown service message."

        });


        return false;
    }
);


console.log(
    "[Privacy Agent] Service worker ready."
);