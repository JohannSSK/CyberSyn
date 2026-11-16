/* ==========================================================================
   dom.js — small DOM helpers.

   Kept deliberately thin: create elements, escape text, format values. No
   page logic lives here, so every page script can share it.
   ========================================================================== */

(function (global) {
    "use strict";

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

    /** Relative time: "3 minutes ago". Falls back to a date for old items. */
    function timeAgo(iso) {
        if (!iso) return "";
        var then = new Date(iso);
        if (isNaN(then.getTime())) return "";
        var seconds = Math.floor((Date.now() - then.getTime()) / 1000);
        if (seconds < 45) return "just now";
        var units = [
            [60, "second"], [60, "minute"], [24, "hour"],
            [7, "day"], [4.35, "week"], [12, "month"]
        ];
        var value = seconds, unit = "second";
        for (var i = 0; i < units.length; i++) {
            if (value < units[i][0]) { unit = units[i][1]; break; }
            value = value / units[i][0];
            unit = units[i][1];
            if (i === units.length - 1) break;
        }
        var n = Math.max(1, Math.floor(value));
        return n + " " + unit + (n === 1 ? "" : "s") + " ago";
    }

    /** Absolute local time, for the audit trail where precision matters. */
    function stamp(iso) {
        if (!iso) return "";
        var d = new Date(iso);
        if (isNaN(d.getTime())) return String(iso);
        return d.toLocaleDateString(undefined, { day: "2-digit", month: "short" }) +
            " · " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    }

    function clockTime(iso) {
        if (!iso) return "";
        var d = new Date(iso);
        if (isNaN(d.getTime())) return "";
        return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    }

    function plural(n, one, many) {
        return n === 1 ? one : (many || one + "s");
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

       This walks text nodes rather than rewriting HTML, so it is safe to run
       over rendered markdown: element boundaries and attribute values are
       left exactly as the renderer produced them. Returns the number of
       matches highlighted, which callers use to report "3 of 10 results". */
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

    global.Dom = {
        el: el, fromHTML: fromHTML, esc: esc,
        $: $, $$: $$, on: on,
        timeAgo: timeAgo, stamp: stamp, clockTime: clockTime,
        plural: plural, debounce: debounce, copyText: copyText,
        highlightText: highlightText
    };
})(window);
