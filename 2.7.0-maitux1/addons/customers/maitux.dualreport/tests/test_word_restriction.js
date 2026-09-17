/* Unit test for the "Word is only for CoaReport.pt" restriction in
 * maitux.dualreport/resources/js/impress_dualformat.js
 *
 * Runs the real file in a vm context with a minimal DOM stub, then checks the
 * decision helpers through the public window.maitux_dualreport surface.
 *
 * Usage: node test_word_restriction.js <path-to-impress_dualformat.js>
 */
"use strict";

const fs = require("fs");
const vm = require("vm");

const path = process.argv[2] ||
    "../src/maitux/dualreport/resources/js/impress_dualformat.js";
const code = fs.readFileSync(path, "utf8");

/* ---- minimal DOM / window stubs ---------------------------------------- */
let templateSelect = null;
let formatSelect = null;

function fakeSelect(value, options) {
    return {
        value: value,
        options: options || [],
        querySelector: function (sel) {
            return this.options.find(function (o) {
                return sel.indexOf('"' + o.value + '"') !== -1;
            }) || null;
        },
        addEventListener: function () {}
    };
}

const form = {
    __maitux_word_sync: false,
    addEventListener: function () {},
    querySelector: function (sel) {
        if (sel.indexOf("maitux_report_format") !== -1) {
            return formatSelect;
        }
        if (sel.indexOf('name="template"') !== -1) {
            return templateSelect;
        }
        return null;
    }
};

const document = {
    readyState: "complete",
    body: {},
    addEventListener: function () {},
    createElement: function () {
        return {
            style: {}, children: [],
            appendChild: function (c) { this.children.push(c); },
            addEventListener: function () {},
            setAttribute: function () {}
        };
    },
    querySelector: function (sel) {
        if (sel.indexOf('form[name="publishform"]') === 0) {
            return form;
        }
        return null;
    }
};

const win = {
    document: document,
    setTimeout: function () { return 0; },
    setInterval: function () { return 0; },
    clearInterval: function () {},
    URL: {}
};
win.window = win;

const ctx = {
    window: win,
    document: document,
    console: console,
    setTimeout: win.setTimeout,
    setInterval: win.setInterval,
    clearInterval: win.clearInterval
};
vm.createContext(ctx);
vm.runInContext(code, ctx, { filename: path });

const api = win.maitux_dualreport;
if (!api) {
    console.log("FAIL: window.maitux_dualreport missing");
    process.exit(1);
}

let failures = 0;

function check(label, got, expected) {
    const ok = got === expected;
    if (!ok) {
        failures += 1;
    }
    console.log("   %s %-52s got=%s expected=%s",
        ok ? "PASS" : "FAIL", label, JSON.stringify(got),
        JSON.stringify(expected));
}

console.log("--- isCoaTemplate ---");
check("CoaReport.pt", api.isCoaTemplate("CoaReport.pt"), true);
check("coareport.pt (lowercase)", api.isCoaTemplate("coareport.pt"), true);
check("INNOCARE.reportdesign:CoaReport.pt", api.isCoaTemplate(
    "INNOCARE.reportdesign:CoaReport.pt"), true);
check("Coa Report.pt (space)", api.isCoaTemplate("Coa Report.pt"), true);
check("DataReport.pt", api.isCoaTemplate("DataReport.pt"), false);
check("senaite.impress:Default.pt", api.isCoaTemplate(
    "senaite.impress:Default.pt"), false);
check("senaite.impress:MultiDefault.pt", api.isCoaTemplate(
    "senaite.impress:MultiDefault.pt"), false);
check("empty", api.isCoaTemplate(""), false);
check("undefined", api.isCoaTemplate(undefined), false);

console.log("--- getFormat() downgrade ---");
win.impress = {
    getRequestOptions: function () { return { template: "DataReport.pt" }; }
};
formatSelect = fakeSelect("word");
check("word + DataReport.pt", api.getFormat(), "pdf");
check("wordAllowed + DataReport.pt", api.wordAllowed(), false);

win.impress.getRequestOptions = function () {
    return { template: "CoaReport.pt" };
};
check("word + CoaReport.pt", api.getFormat(), "word");
check("wordAllowed + CoaReport.pt", api.wordAllowed(), true);

formatSelect = fakeSelect("pdf");
check("pdf + CoaReport.pt", api.getFormat(), "pdf");

console.log("--- syncWordOption() forces PDF for non CoA ---");
const optWord = { value: "word", disabled: false, title: "" };
formatSelect = fakeSelect("word", [optWord]);
win.impress.getRequestOptions = function () {
    return { template: "senaite.impress:Default.pt" };
};
api.syncWordOption(formatSelect);
check("select value after sync", formatSelect.value, "pdf");
check("Word option disabled", optWord.disabled, true);

console.log("--- syncWordOption() enables Word for CoA ---");
win.impress.getRequestOptions = function () {
    return { template: "CoaReport.pt" };
};
api.syncWordOption(formatSelect);
check("Word option disabled", optWord.disabled, false);

console.log("");
console.log(failures === 0 ? "RESULT: PASS" : "RESULT: FAIL (" + failures + ")");
process.exit(failures === 0 ? 0 : 1);
