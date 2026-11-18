/* ==========================================================================
   dom.js — small DOM, formatting and avatar helpers.

   Kept deliberately thin: create elements, escape text, format timestamps
   and numbers for EN/EL, and assign each member a consistent avatar tone.
   No page logic lives here, so every page script can share it.
   ========================================================================== */

(function (global) {
    "use strict";

    var AVATAR_TONES = [
        "stone", "taupe", "sand", "walnut",
        "umber", "clay", "sienna", "rust"
    ];

    function isGreek() {
        if (global.I18n && typeof global.I18n.current === "function") {
            return global.I18n.current() === "el";
        }
        var doc = global.document && global.document.documentElement;
        return !!(doc && doc.lang === "el");
    }

    function locale() {
        return isGreek() ? "el-GR" : "en-GB";
    }

    /** Create an element: el("div", "card", "text") */
    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    /** Build from an HTML string. */
    function fromHTML(html) {
        var tpl = document.createElement("template");
        tpl.innerHTML = (html || "").trim();
        return tpl.content.firstElementChild;
    }

    var ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

    /** Escape untrusted text before it goes anywhere near innerHTML. */
    function esc(value) {
        return String(value === null || value === undefined ? "" : value)
            .replace(/[&<>"']/g, function (c) { return ESCAPES[c]; });
    }

    function $(selector, root) { return (root || document).querySelector(selector); }

    function $$(selector, root) {
        return Array.prototype.slice.call((root || document).querySelectorAll(selector));
    }

    function on(target, type, handler, options) {
        if (!target) return function () {};
        target.addEventListener(type, handler, options);
        return function () { target.removeEventListener(type, handler, options); };
    }

    /* ------------------------------------------------------------------
       Deterministic per-member avatars — same username, same warm-neutral
       tone and two-letter initials on every screen.
       ------------------------------------------------------------------ */

    function avatarTone(username) {
        var key = String(username || "member").trim().toLowerCase();
        var hash = 2166136261;
        for (var i = 0; i < key.length; i++) {
            hash ^= key.charCodeAt(i);
            hash = Math.imul ? Math.imul(hash, 16777619) : (hash * 16777619) | 0;
        }
        return AVATAR_TONES[(hash >>> 0) % AVATAR_TONES.length];
    }

    function initials(username) {
        var raw = String(username || "").trim();
        if (!raw) return "M";
        var parts = raw.split(/[\s._-]+/).filter(Boolean);
        var letters;
        if (parts.length >= 2) {
            letters = parts[0].charAt(0) + parts[1].charAt(0);
        } else {
            letters = raw.slice(0, 2);
        }
        return letters.toLocaleUpperCase(locale());
    }

    function paintAvatar(node, username) {
        if (!node) return;
        node.textContent = initials(username);
        node.setAttribute("data-tone", avatarTone(username));
        node.setAttribute("aria-hidden", "true");
    }

    function avatarHTML(username, extraClass) {
        var cls = "avatar" + (extraClass ? " " + extraClass : "");
        return '<span class="' + esc(cls) + '" data-tone="' +
            esc(avatarTone(username)) + '" aria-hidden="true">' +
            esc(initials(username)) + "</span>";
    }

    /* ------------------------------------------------------------------
       Numbers and UTC timestamps
       ------------------------------------------------------------------ */

    function formatNumber(value) {
        var n = Number(value);
        if (!isFinite(n)) return "0";
        try {
            return new Intl.NumberFormat(locale()).format(n);
        } catch (err) {
            return String(n);
        }
    }

    function formatPercent(value) {
        var n = Number(value);
        if (!isFinite(n)) return "0%";
        return formatNumber(Math.round(n)) + "%";
    }

    /** Relative time for chat lists: "3 min ago" / "πριν 3 λεπτά". */
    function timeAgo(iso) {
        if (!iso) return "";
        var raw = String(iso);
        // SQLite datetime('now') writes bare UTC without a trailing Z.
        if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(raw)) {
            raw = raw.replace(" ", "T") + "Z";
        }
        var then = new Date(raw);
        if (isNaN(then.getTime())) return "";
        var seconds = Math.max(0, Math.floor((Date.now() - then.getTime()) / 1000));
        var elLang = isGreek();
        if (seconds < 45) return elLang ? "μόλις τώρα" : "just now";

        var units = [
            [60,   "sec",   "secs",   "δευτ.",   "δευτ."],
            [60,   "min",   "min",    "λεπτό",   "λεπτά"],
            [24,   "hour",  "hours",  "ώρα",     "ώρες"],
            [7,    "day",   "days",   "ημέρα",   "ημέρες"],
            [4.35, "week",  "weeks",  "εβδ.",    "εβδ."],
            [12,   "month", "months", "μήνα",    "μήνες"]
        ];
        var value = seconds;
        var chosen = units[0];
        for (var i = 0; i < units.length; i++) {
            chosen = units[i];
            if (value < units[i][0] || i === units.length - 1) break;
            value = value / units[i][0];
        }
        var n = Math.max(1, Math.floor(value));
        if (elLang) {
            return "πριν " + formatNumber(n) + " " + (n === 1 ? chosen[3] : chosen[4]);
        }
        return formatNumber(n) + " " + (n === 1 ? chosen[1] : chosen[2]) + " ago";
    }

    /** Parse ISO or SQLite UTC strings consistently as UTC. */
    function parseUTC(iso) {
        var raw = String(iso || "").trim();
        if (!raw) return null;
        if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(raw)) {
            raw = raw.replace(" ", "T") + "Z";
        } else if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(raw) &&
                   !/[zZ]|[+-]\d{2}:?\d{2}$/.test(raw)) {
            raw += "Z";
        }
        var d = new Date(raw);
        return isNaN(d.getTime()) ? null : d;
    }

    /** Absolute UTC time for transcripts and audit trails. */
    function stamp(iso) {
        if (!iso) return "";
        var d = parseUTC(iso);
        if (!d) return String(iso);
        try {
            var day = d.toLocaleDateString(locale(), {
                day: "2-digit", month: "short", timeZone: "UTC"
            });
            var time = d.toLocaleTimeString(locale(), {
                hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC"
            });
            return day + " · " + time + " UTC";
        } catch (err) {
            return d.toISOString().slice(0, 16).replace("T", " ") + " UTC";
        }
    }

    function clockTime(iso) {
        if (!iso) return "";
        var d = parseUTC(iso);
        if (!d) return "";
        try {
            return d.toLocaleTimeString(locale(), {
                hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC"
            }) + " UTC";
        } catch (err) {
            return d.toISOString().slice(11, 16) + " UTC";
        }
    }

    function plural(n, one, many) {
        return formatNumber(n) + " " + (n === 1 ? one : (many || one + "s"));
    }

    function debounce(fn, wait) {
        var timer = null;
        return function () {
            var args = arguments, self = this;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(self, args); }, wait || 220);
        };
    }

    function copyText(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text);
        }
        return Promise.reject(new Error("Clipboard unavailable"));
    }

    /* Wrap every case-insensitive occurrence of `query` in <mark>.

       Walks text nodes rather than rewriting HTML, so rendered markdown and
       attribute values stay untouched. Returns the number of matches found. */
    function highlightText(root, query) {
        var needle = String(query || "").trim().toLowerCase();
        if (!needle || !root) return 0;

        var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
        var nodes = [];
        while (walker.nextNode()) {
            var node = walker.currentNode;
            if (node.nodeValue && node.nodeValue.toLowerCase().indexOf(needle) !== -1) {
                nodes.push(node);
            }
        }

        var count = 0;
        nodes.forEach(function (node) {
            var text = node.nodeValue;
            var lower = text.toLowerCase();
            var fragment = document.createDocumentFragment();
            var from = 0;
            var at = lower.indexOf(needle);

            while (at !== -1) {
                if (at > from) fragment.appendChild(document.createTextNode(text.slice(from, at)));
                var mark = document.createElement("mark");
                mark.textContent = text.slice(at, at + needle.length);
                fragment.appendChild(mark);
                count += 1;
                from = at + needle.length;
                at = lower.indexOf(needle, from);
            }
            if (from < text.length) fragment.appendChild(document.createTextNode(text.slice(from)));
            node.parentNode.replaceChild(fragment, node);
        });
        return count;
    }

    var POLICY_FIELDS = {
        check1: "action_check1", check2: "action_check2", check3: "action_check3", block_code: "action_code"
    };

    function policyAction(settings, rule) {
        var action = settings[POLICY_FIELDS[rule]];
        if (action) return action;
        // Old payloads still represent the same effective rules.
        var enabled = rule === "block_code" ? !!settings[rule] : settings[rule] !== false;
        return enabled ? "block" : "allow";
    }

    function activeChecks(settings) {
        return Object.keys(POLICY_FIELDS).filter(function (rule) { return policyAction(settings, rule) !== "allow"; }).length;
    }

    global.Dom = {
        policyAction: policyAction, activeChecks: activeChecks, policyFields: POLICY_FIELDS,
        el: el, fromHTML: fromHTML, esc: esc,
        $: $, $$: $$, on: on,
        avatarTone: avatarTone, initials: initials,
        paintAvatar: paintAvatar, avatarHTML: avatarHTML,
        formatNumber: formatNumber, formatPercent: formatPercent,
        timeAgo: timeAgo, stamp: stamp, clockTime: clockTime,
        plural: plural, debounce: debounce, copyText: copyText,
        highlightText: highlightText
    };
})(window);
