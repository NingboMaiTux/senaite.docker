/* maitux.dualreport - PDF + Word output for the senaite.impress publish view
 *
 * This file is served as a "++plone++maitux.dualreport" static resource and
 * pulled into the publish/printview pages by a viewlet in the
 * "senaite.impress.publishcustomhead" slot (see browser/head.py).
 *
 * It does four things without touching the compiled impress bundle:
 *
 *  1. injects a "格式" (format) dropdown into the publish toolbar
 *     (PDF = 默认, Word)
 *  2. appends the selected format to every request the publish UI sends
 *     (window.impress.getRequestOptions is patched -> covers Save AND the
 *     render/PDF download payloads)
 *  3. makes the native "Download PDF" action download a Word file when the
 *     dropdown is set to Word (the PDF-download POST would otherwise fetch a
 *     PDF blob first)
 *  4. keeps Word restricted to the CoA template: the Word option is disabled
 *     (and forced back to PDF) for every template whose name does not contain
 *     "coareport" (WORD_MARKER below). The server enforces the same rule, so
 *     a stale/hand crafted payload cannot produce a Word file for another
 *     template.
 *
 * All code is ES5 (the bundle target) and runs only when window.impress is
 * present (i.e. on publish pages).
 */
(function (window, document) {
    "use strict";

    var FORMAT_NAME = "maitux_report_format";
    var FORMAT_PDF = "pdf";
    var FORMAT_WORD = "word";

    /* Word output is only supported for the CoA template, mirroring
     * maitux.dualreport.config.WORD_TEMPLATE_MARKER on the server side. */
    var WORD_MARKER = "coareport";
    var WORD_HINT = "Word 仅支持 CoaReport.pt 模板 / " +
        "Word is only available for the CoaReport.pt template";

    var lastFormat = FORMAT_PDF;

    /* keep the pristine implementation around: getRequestOptions() is patched
     * below, and the template lookup must not run through the patch. */
    var originalGetRequestOptions = null;

    function isCoaTemplate(name) {
        return String(name || "").toLowerCase().replace(/\s+/g, "")
            .indexOf(WORD_MARKER) !== -1;
    }

    /* Current impress template, e.g. "CoaReport.pt" (empty when unknown). */
    function currentTemplate() {
        var impress = window.impress;
        try {
            var getter = originalGetRequestOptions ||
                (impress && impress.getRequestOptions);
            if (getter) {
                var options = getter.call(impress);
                if (options && options.template) {
                    return String(options.template);
                }
            }
        } catch (err) { /* ignore */ }
        var sel = document.querySelector(
            'form[name="publishform"] select[name="template"]');
        return sel ? String(sel.value) : "";
    }

    function wordAllowed() {
        return isCoaTemplate(currentTemplate());
    }

    function getFormat() {
        var sel = findSelect();
        var fmt = sel ? sel.value : lastFormat;
        if (fmt === FORMAT_WORD && !wordAllowed()) {
            /* never send "word" to the server for a non CoA template */
            return FORMAT_PDF;
        }
        return fmt;
    }

    function findSelect() {
        var form = document.querySelector('form[name="publishform"]');
        if (!form) {
            return null;
        }
        return form.querySelector('select[name="' + FORMAT_NAME + '"]');
    }

    function makeSelect() {
        var sel = document.createElement("select");
        sel.name = FORMAT_NAME;
        sel.className = "custom-select";
        sel.title = "Report format / 报告格式";

        var optPdf = document.createElement("option");
        optPdf.value = FORMAT_PDF;
        optPdf.textContent = "PDF";
        sel.appendChild(optPdf);

        var optWord = document.createElement("option");
        optWord.value = FORMAT_WORD;
        optWord.textContent = "Word";
        optWord.title = WORD_HINT;
        sel.appendChild(optWord);

        sel.addEventListener("change", function () {
            lastFormat = sel.value;
            syncWordOption(sel);
        });
        return sel;
    }

    /* Enable the Word entry only for the CoA template; otherwise force the
     * dropdown back to PDF so the toolbar never looks like Word is usable. */
    function syncWordOption(sel) {
        var allowed = wordAllowed();
        var optWord = sel.querySelector('option[value="' + FORMAT_WORD + '"]');
        if (optWord) {
            optWord.disabled = !allowed;
            optWord.title = allowed ? "" : WORD_HINT;
        }
        if (!allowed && sel.value === FORMAT_WORD) {
            sel.value = FORMAT_PDF;
            lastFormat = FORMAT_PDF;
        }
        return allowed;
    }

    /* Insert the format select into the toolbar (template/format/orientation
     * row). Called on every (re-)render of the React controlled form. */
    function ensureSelect() {
        var form = document.querySelector('form[name="publishform"]');
        if (!form) {
            return false;
        }
        /* re-evaluate the Word availability whenever the template changes
         * (capture phase: React handlers may stop propagation) */
        if (!form.__maitux_word_sync) {
            form.__maitux_word_sync = true;
            form.addEventListener("change", function () {
                var current = findSelect();
                if (current) {
                    syncWordOption(current);
                }
            }, true);
        }
        if (findSelect()) {
            var existing = findSelect();
            syncWordOption(existing);
            if (existing.value !== lastFormat) {
                existing.value = lastFormat;
                syncWordOption(existing);
            }
            return true;
        }
        var group = form.querySelector(".input-group");
        if (!group) {
            return false;
        }
        var append = group.querySelector(".input-group-append");
        var sel = makeSelect();
        sel.value = lastFormat;
        syncWordOption(sel);
        if (append) {
            group.insertBefore(sel, append);
        } else {
            group.appendChild(sel);
        }
        return true;
    }

    function makeWordName() {
        var impress = window.impress;
        var items = [];
        try {
            items = impress.get_items ? impress.get_items() : [];
        } catch (err) { /* ignore */ }
        var base = "Report";
        if (items && items.length) {
            base = items.join("_").slice(0, 120);
        }
        var d = new Date();
        function pad(n) { return (n < 10 ? "0" : "") + n; }
        var stamp = d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) +
            "-" + pad(d.getHours()) + pad(d.getMinutes());
        return base + "-" + stamp + "." + "docx";
    }

    function saveBlob(blob, filename) {
        var url = window.URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(function () {
            window.URL.revokeObjectURL(url);
            if (a.parentNode) {
                a.parentNode.removeChild(a);
            }
        }, 1500);
    }

    function isWordBlob(response) {
        var ctype = "";
        try {
            ctype = response.headers.get("Content-Type") || "";
        } catch (err) { /* ignore */ }
        ctype = String(ctype).toLowerCase();
        return ctype.indexOf("word") !== -1 ||
            ctype.indexOf("openxml") !== -1 ||
            ctype.indexOf("msword") !== -1 ||
            ctype.indexOf("octet-stream") !== -1;
    }

    function isDownloadPdfAction(url) {
        return String(url || "").indexOf("impress_download_pdf") !== -1;
    }

    function installPatches() {
        var impress = window.impress;
        if (!impress || !impress.getRequestOptions) {
            return false;
        }
        if (impress.__maitux_dual_patched) {
            return true;
        }

        var origGetRequestOptions = impress.getRequestOptions.bind(impress);
        originalGetRequestOptions = origGetRequestOptions;
        impress.getRequestOptions = function () {
            var options = origGetRequestOptions();
            options.report_format = getFormat();
            return options;
        };

        /* Word downloads through the native "download PDF" action */
        var origHandleCustomAction = impress.handleCustomAction.bind(impress);
        impress.handleCustomAction = function (evt) {
            var url = "";
            if (evt && evt.currentTarget) {
                url = evt.currentTarget.getAttribute("url") || "";
            }
            if (getFormat() === FORMAT_WORD && isDownloadPdfAction(url)) {
                evt.preventDefault();
                var options = impress.getRequestOptions();
                options.report_format = FORMAT_WORD;
                impress.api.create_pdf(options).then(function (blob) {
                    saveBlob(blob, makeWordName());
                });
                return;
            }
            return origHandleCustomAction(evt);
        };

        /* defensive: if a Word blob ever arrives through the generic action
         * response handler, download it instead of doing nothing */
        var origHandleActionResponse = impress.handleActionResponse
            ? impress.handleActionResponse.bind(impress) : null;
        impress.handleActionResponse = function (response) {
            if (response && response.blob && isWordBlob(response)) {
                return response.blob().then(function (blob) {
                    saveBlob(blob, makeWordName());
                });
            }
            if (origHandleActionResponse) {
                return origHandleActionResponse(response);
            }
            return null;
        };

        impress.__maitux_dual_patched = true;
        return true;
    }

    function boot() {
        /* window.impress is created when the React component mounts; poll a
         * few times until it exists (the bundle is loaded before this file) */
        var patched = installPatches();
        ensureSelect();
        if (!patched) {
            var tries = 0;
            var timer = window.setInterval(function () {
                tries += 1;
                if (installPatches()) {
                    window.clearInterval(timer);
                } else if (tries > 100) {
                    window.clearInterval(timer);
                }
            }, 200);
        }
        /* React replaces the whole form on every state change (template
         * reload, preview load, ...) - keep the dropdown and the patches in
         * sync with the current DOM */
        if (window.MutationObserver) {
            var observer = new MutationObserver(function () {
                ensureSelect();
                installPatches();
            });
            observer.observe(document.body, { childList: true, subtree: true });
        }
    }

    /* Small public surface: lets the restriction be checked from the browser
     * console (e.g. window.maitux_dualreport.wordAllowed()) and unit tested
     * without a full browser. */
    window.maitux_dualreport = {
        isCoaTemplate: isCoaTemplate,
        currentTemplate: currentTemplate,
        wordAllowed: wordAllowed,
        getFormat: getFormat,
        syncWordOption: syncWordOption
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }
})(window, document);
