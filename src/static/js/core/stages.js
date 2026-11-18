/* ==========================================================================
   stages.js — local check definitions and blocked-card copy.

   The server reports a stage key ("check2") and a category ("IBAN"), never
   a sentence. Chat wait states and blocked-card copy stay stage-agnostic so
   no check name or index is exposed in chat, while administrator statistics
   still use `name` and `label`.
   ========================================================================== */

(function (global) {
    "use strict";

    function t(text) {
        return global.I18n && typeof global.I18n.t === "function"
            ? global.I18n.t(text)
            : text;
    }

    var STAGES = {
        check1: { name: "Personal & Greek IDs" },
        check2: { name: "Confidential context" },
        check3: { name: "Prompt injection" }
    };

    function entry(stage) {
        return STAGES[stage] || null;
    }

    /** "Personal & Greek IDs" — used by administrator Statistics. */
    function name(stage) {
        var found = entry(stage);
        return t(found ? found.name : (stage || "a local check"));
    }

    /** "Check 2 · Confidential context" — numbered for administrator Statistics. */
    function label(stage) {
        var found = entry(stage);
        if (!found) return stage || "";
        var number = String(stage).replace(/\D/g, "");
        if (!number) return t(found.name);
        return t("Check " + number) + " · " + t(found.name);
    }

    /** Calm, stage-agnostic headline for a blocked card. */
    function verdict(_stage) {
        return t("Stopped — a local check flagged this message");
    }

    /**
     * One stage-agnostic sentence explaining a block, built from the server's
     * verdict. `blockInfo` carries `main_cause` and `line`.
     */
    function reason(blockInfo) {
        var info = blockInfo || {};
        var text = t("A local check matched this message.");
        var hasCause = info.main_cause && info.main_cause !== "unknown";
        var hasLine = !!info.line;

        if (global.I18n && global.I18n.current() === "el") {
            if (hasCause && hasLine) {
                text += " Εντόπισε " + info.main_cause + " στη γραμμή " + info.line + ".";
            } else if (hasCause) {
                text += " Εντόπισε " + info.main_cause + ".";
            } else if (hasLine) {
                text += " Σταμάτησε στη γραμμή " + info.line + ".";
            }
            return text;
        }

        if (hasCause && hasLine) {
            text += " It stopped on " + info.main_cause + " at line " + info.line + ".";
        } else if (hasCause) {
            text += " It stopped on " + info.main_cause + ".";
        } else if (hasLine) {
            text += " It stopped at line " + info.line + ".";
        }
        return text;
    }

    /**
     * Labelled mono trace line for the "Why?" expander on a blocked card:
     * "Cause: AFM · Line: 2 · Characters: 40–49"
     */
    function detailLine(_stage, match) {
        var m = match || {};
        var rawCause = m.main_cause || m.cause;
        var cause = (rawCause && rawCause !== "unknown") ? rawCause : null;
        var hasOffsets = typeof m.start_offset === "number" && typeof m.end_offset === "number";

        var parts = [];
        if (cause) {
            parts.push(t("Cause") + ": " + cause);
        }
        if (m.line) {
            parts.push(t("Line") + ": " + m.line);
        }
        if (hasOffsets) {
            parts.push(t("Characters") + ": " + m.start_offset + "–" + m.end_offset);
        }
        return parts.length ? parts.join(" · ") : t("Local check");
    }

    global.Stages = {
        keys: Object.keys(STAGES),
        has: function (stage) { return !!entry(stage); },
        name: name,
        label: label,
        verdict: verdict,
        detailLine: detailLine,
        reason: reason
    };
})(window);
