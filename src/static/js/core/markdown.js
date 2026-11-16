/* ==========================================================================
   markdown.js — render the small Markdown subset models actually return.

   Fenced code, headings, bullet and numbered lists, rules, bold, italic and
   inline code. Everything is escaped before it is styled: a model reply is
   untrusted input and must never be able to inject markup.
   ========================================================================== */

(function (global) {
    "use strict";

    var esc = global.Dom.esc;
    var FENCE = "```";

    function inline(text) {
        return String(text)
            .replace(/`([^`]+)`/g, "<code>$1</code>")
            .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
            .replace(/(^|[^*])\*([^*\s][^*]*)\*(?!\*)/g, "$1<em>$2</em>");
    }

    function render(source) {
        var parts = String(source || "").split(FENCE);
        var html = "";

        parts.forEach(function (part, index) {
            // Odd indexes are inside a fence: code, verbatim.
            if (index % 2 === 1) {
                var newline = part.indexOf("\n");
                var code = newline >= 0 ? part.slice(newline + 1) : part;
                html += "<pre><code>" + esc(code.replace(/\n$/, "")) + "</code></pre>";
                return;
            }

            var list = null;
            var closeList = function () {
                if (list) { html += "</" + list + ">"; list = null; }
            };

            part.split("\n").forEach(function (raw) {
                var m;
                if (!raw.trim()) { closeList(); return; }

                if ((m = raw.match(/^\s{0,3}(#{1,6})\s+(.*)$/))) {
                    closeList();
                    var level = Math.min(m[1].length + 1, 6);
                    html += "<h" + level + ">" + inline(esc(m[2])) + "</h" + level + ">";
                    return;
                }
                if (/^\s*([-*_])\1{2,}\s*$/.test(raw)) { closeList(); html += "<hr>"; return; }
                if ((m = raw.match(/^\s*[*+-]\s+(.*)$/))) {
                    if (list !== "ul") { closeList(); html += "<ul>"; list = "ul"; }
                    html += "<li>" + inline(esc(m[1])) + "</li>";
                    return;
                }
                if ((m = raw.match(/^\s*(\d+)[.)]\s+(.*)$/))) {
                    if (list !== "ol") {
                        closeList();
                        html += '<ol start="' + parseInt(m[1], 10) + '">';
                        list = "ol";
                    }
                    html += "<li>" + inline(esc(m[2])) + "</li>";
                    return;
                }
                closeList();
                html += "<p>" + inline(esc(raw)) + "</p>";
            });
            closeList();
        });

        return html;
    }

    /** Plain-text version, for excerpts and search results. */
    function strip(source) {
        return String(source || "")
            .replace(/```[\s\S]*?```/g, " ")
            .replace(/[#>*_`]/g, "")
            .replace(/\s+/g, " ")
            .trim();
    }

    global.Markdown = { render: render, strip: strip, inline: inline };
})(window);
