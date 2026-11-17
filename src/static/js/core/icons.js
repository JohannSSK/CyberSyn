/* ==========================================================================
   icons.js — one registry for every icon in the app.

   Icons ship as PNGs under /assets/icons (see tools/build_icons.py, which
   normalises them to transparent single-colour 72px files). Where a PNG is
   not available yet, an inline SVG of the same design is used, so a missing
   asset degrades to a crisp icon instead of a broken image.

   Usage:  Icons.el("settings")            -> an element
           Icons.html("edit", "icon")      -> markup string
   ========================================================================== */

(function (global) {
    "use strict";

    var BASE = "/assets/icons/";

    /* Icons that ship as PNGs. Every name here must exist under
       assets/icons/ — tools/build_icons.py renders one per entry of the SVG
       table below, and `tools/build_icons.py --check` fails if they drift.
       A PNG carries its own colour, so it cannot follow `currentColor`;
       anywhere the colour must change, dim it with opacity instead. */
    var PNG = {
        chat: "chat.png",
        check: "check.png",
        chevron: "chevron.png",
        clock: "clock.png",
        close: "close.png",
        copy: "copy.png",
        delete: "delete.png",
        download: "download.png",
        edit: "edit.png",
        filter: "filter.png",
        help: "help.png",
        history: "history.png",
        key: "key.png",
        lock: "lock.png",
        logout: "logout.png",
        menu: "menu.png",
        plus: "plus.png",
        profile: "profile.png",
        regenerate: "regenerate.png",
        search: "search.png",
        send: "send.png",
        settings: "settings.png",
        shield: "shield.png",
        spark: "spark.png",
        stats: "stats.png",
        team: "team.png",
        warning: "warning.png"
    };

    /* Fallback vector paths, drawn on a 24x24 grid with 1.8 stroke. */
    var SVG = {
        shield: '<path d="M12 3l7 3v5.5c0 4.6-3.1 8.4-7 9.5-3.9-1.1-7-4.9-7-9.5V6l7-3z"/><path d="M9 12l2 2 4-4"/>',
        chat: '<path d="M21 12a8 8 0 01-8 8H8l-5 3 1.2-4.2A8 8 0 1121 12z"/>',
        settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-2.9 1.2v.2a2 2 0 11-4 0v-.1A1.7 1.7 0 007 19.4a1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00-1.2-2.9H1a2 2 0 110-4h.2A1.7 1.7 0 002.6 7a1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1A1.7 1.7 0 008 2.6h.1A1.7 1.7 0 009.8 1V.9a2 2 0 114 0V1a1.7 1.7 0 002.9 1.2l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 001.2 2.9h.2a2 2 0 110 4h-.2a1.7 1.7 0 00-1.5 1z"/>',
        profile: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0116 0"/>',
        stats: '<path d="M3 21h18"/><rect x="5" y="11" width="4" height="7" rx="1"/><rect x="11" y="6" width="4" height="12" rx="1"/><rect x="17" y="14" width="4" height="4" rx="1"/>',
        team: '<circle cx="9" cy="8" r="3.2"/><path d="M2.5 20a6.5 6.5 0 0113 0"/><circle cx="17" cy="9" r="2.4"/><path d="M15.5 20a5 5 0 016-3.6"/>',
        key: '<circle cx="8" cy="15" r="4"/><path d="M10.8 12.2L20 3M17 6l2.5 2.5M14.5 8.5L17 11"/>',
        search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.6-3.6"/>',
        edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4 12.5-12.5z"/>',
        delete: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v5M14 11v5"/>',
        regenerate: '<path d="M21 12a9 9 0 11-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
        plus: '<path d="M12 5v14M5 12h14"/>',
        send: '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>',
        logout: '<path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/>',
        help: '<circle cx="12" cy="12" r="9"/><path d="M9.2 9a2.9 2.9 0 015.6 1c0 2-2.8 2.4-2.8 4"/><path d="M12 17.5h.01"/>',
        close: '<path d="M18 6L6 18M6 6l12 12"/>',
        check: '<path d="M20 6L9 17l-5-5"/>',
        clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>',
        warning: '<path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
        lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 018 0v4"/>',
        chevron: '<path d="M6 9l6 6 6-6"/>',
        menu: '<path d="M3 6h18M3 12h18M3 18h18"/>',
        copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>',
        download: '<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/>',
        spark: '<path d="M12 2l2.1 6.3L20.5 10l-6.4 1.7L12 18l-2.1-6.3L3.5 10l6.4-1.7L12 2z"/>',
        history: '<path d="M3 3v6h6"/><path d="M3.5 13a9 9 0 102.2-6.4L3 9"/>',
        filter: '<path d="M22 3H2l8 9.5V19l4 2v-8.5L22 3z"/>',
        image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M3 17l5-4 4 3 4-3 5 4"/>'
    };

    var failed = {};

    function svgMarkup(name, cls) {
        var body = SVG[name] || SVG.help;
        return '<svg class="' + (cls || "icon") + '" viewBox="0 0 24 24" fill="none" ' +
            'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" ' +
            'stroke-linejoin="round" aria-hidden="true">' + body + "</svg>";
    }

    function pngMarkup(name, cls) {
        return '<img class="' + (cls || "icon") + '" src="' + BASE + PNG[name] +
            '" alt="" aria-hidden="true" data-icon="' + name + '">';
    }

    /* PNGs carry their own colour, so they cannot follow `currentColor`.
       A missing file switches to the SVG for the rest of the page load. */
    function html(name, cls) {
        if (PNG[name] && !failed[name]) {
            return pngMarkup(name, cls);
        }
        return svgMarkup(name, cls);
    }

    function el(name, cls) {
        var wrap = document.createElement("span");
        wrap.style.display = "contents";
        wrap.innerHTML = html(name, cls);
        return wrap.firstElementChild;
    }

    /* Swap in the SVG if a PNG 404s, so one missing file cannot leave a
       broken-image box in the UI. */
    document.addEventListener(
        "error",
        function (event) {
            var img = event.target;
            if (!img || img.tagName !== "IMG" || !img.dataset || !img.dataset.icon) return;
            failed[img.dataset.icon] = true;
            var name = img.dataset.icon;
            var holder = document.createElement("span");
            holder.innerHTML = svgMarkup(name, img.className);
            if (img.parentNode) img.parentNode.replaceChild(holder.firstElementChild, img);
        },
        true
    );

    global.Icons = {
        html: html,
        el: el,
        svg: svgMarkup,
        has: function (name) { return !!(SVG[name] || PNG[name]); }
    };
})(window);
