/* ==========================================================================
   stages.js — what each scanner is called and what it looks for.

   The server reports a stage as a key ("check2") and a category ("IBAN"),
   never as a sentence. Turning those into English belongs in one place: the
   statistics timeline, the waiting indicator and the blocked card all name
   the same checks, and the wording should not drift between them.
   ========================================================================== */

(function (global) {
    "use strict";

    var STAGES = {
        check1: {
            name: "Personal & Greek IDs",
            checking: "Checking for personal and Greek identifiers",
            why: "Check 1 looks for personal identifiers and Greek ID numbers."
        },
        check2: {
            name: "Confidential context",
            checking: "Checking for confidential context",
            why: "Check 2 looks for confidential company material."
        },
        check3: {
            name: "Prompt injection",
            checking: "Checking for prompt injection",
            why: "Check 3 looks for instructions aimed at the model itself."
        }
    };

    function entry(stage) {
        return STAGES[stage] || null;
    }

    /** "Personal & Greek IDs" — the check, on its own. */
    function name(stage) {
        var found = entry(stage);
        return found ? found.name : (stage || "a local check");
    }

    /** "Check 2 · Confidential context" — numbered, for tables and logs. */
    function label(stage) {
        var found = entry(stage);
        if (!found) return stage || "";
        var number = String(stage).replace(/\D/g, "");
        return number ? "Check " + number + " · " + found.name : found.name;
    }

    /** "Checking for confidential context" — the present-participle phrase. */
    function checking(stage) {
        var found = entry(stage);
        return found ? found.checking : "Checking the message";
    }

    /**
     * One sentence explaining a block, built from what the server sent.
     * `blockInfo` carries `stage`, `main_cause` and `line`.
     */
    function reason(blockInfo) {
        var info = blockInfo || {};
        var found = entry(info.stage);
        var text = found ? found.why : "A local check matched this message.";
        if (info.main_cause && info.main_cause !== "unknown") {
            text += " It stopped on " + info.main_cause;
        }
        if (info.line) text += " at line " + info.line;
        return text + ".";
    }

    global.Stages = {
        keys: Object.keys(STAGES),
        has: function (stage) { return !!entry(stage); },
        name: name,
        label: label,
        checking: checking,
        why: function (stage) {
            var found = entry(stage);
            return found ? found.why : "";
        },
        reason: reason
    };
})(window);
