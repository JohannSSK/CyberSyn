/* ==========================================================================
   loading.js — button spinners, the scanning overlay, toasts.

   Every action in the app gives feedback. `withButton` locks the button and
   shows a spinner for the duration of a request, so a second click cannot
   fire the same action twice and the user can see something is happening.
   ========================================================================== */

(function (global) {
    "use strict";

    var Icons = global.Icons;

    /* ------------------------------------------------------------------
       Button loading state
       ------------------------------------------------------------------ */

    function setLoading(button, isLoading, label) {
        if (!button) return;
        if (isLoading) {
            if (button.dataset.busy === "1") return;
            button.dataset.busy = "1";
            button.dataset.label = button.dataset.label || button.textContent;
            if (!button.querySelector(".btn-spinner")) {
                var spinner = document.createElement("span");
                spinner.className = "btn-spinner";
                button.appendChild(spinner);
            }
            button.classList.add("is-loading");
            button.disabled = true;
            if (label) button.setAttribute("aria-label", label);
        } else {
            button.classList.remove("is-loading");
            button.disabled = false;
            delete button.dataset.busy;
        }
    }

    /**
     * Run an async task with the button locked and spinning.
     *   Loading.withButton(btn, () => Api.post(...)).then(...)
     */
    function withButton(button, task, label) {
        setLoading(button, true, label);
        return Promise.resolve()
            .then(task)
            .finally(function () { setLoading(button, false); });
    }

    /* ------------------------------------------------------------------
       Scanning overlay
       ------------------------------------------------------------------ */

    var STEPS = [
        { id: "check1", title: "Personal & Greek IDs", sub: "AFM, AMKA, phone numbers and names" },
        { id: "check2", title: "Confidential context", sub: "Contracts, finances, HR and source code" },
        { id: "check3", title: "Prompt safety", sub: "Injection and override attempts" },
        { id: "ai", title: "AI response", sub: "Sending the approved message" }
    ];

    var overlay = null;
    var ticker = null;

    function build() {
        var steps = STEPS.map(function (step) {
            return '' +
                '<div class="scan-step" data-step="' + step.id + '">' +
                '  <span class="mark">' + Icons.svg("check") + '</span>' +
                '  <span class="scan-step-body">' +
                '    <strong>' + step.title + '</strong>' +
                '    <small>' + step.sub + '</small>' +
                '  </span>' +
                '  <span class="status">Waiting</span>' +
                '</div>';
        }).join("");

        var node = document.createElement("div");
        node.className = "scan-overlay";
        node.innerHTML = '' +
            '<div class="scan-card">' +
            '  <div class="scan-ring">' +
            '    <svg class="ring" viewBox="0 0 64 64"><circle class="track" cx="32" cy="32" r="28"/>' +
            '    <circle class="bar" cx="32" cy="32" r="28"/></svg>' +
            '    <span class="glyph">' + Icons.svg("shield") + '</span>' +
            '  </div>' +
            '  <h3 id="scan-title">Checking your message</h3>' +
            '  <p class="small muted" id="scan-sub">Running local privacy checks before anything leaves this machine</p>' +
            '  <div class="scan-steps">' + steps + '</div>' +
            '  <div class="scan-timer">Elapsed <b id="scan-elapsed">0.0s</b></div>' +
            '</div>';
        document.body.appendChild(node);
        overlay = node;
        return node;
    }

    function markStep(id, state) {
        if (!overlay) return;
        var row = overlay.querySelector('[data-step="' + id + '"]');
        if (!row) return;
        row.classList.remove("active", "done");
        if (state) {
            row.classList.add(state);
            row.querySelector(".status").textContent =
                state === "done" ? "Done" : "Running";
        }
    }

    function resetSteps() {
        STEPS.forEach(function (step) {
            var row = overlay && overlay.querySelector('[data-step="' + step.id + '"]');
            if (row) {
                row.classList.remove("active", "done");
                row.querySelector(".status").textContent = "Waiting";
            }
        });
    }

    /**
     * Show the scanning overlay.
     * @param {object} flags   which checks are on: {check1, check2, check3}
     * @param {boolean} bypass true when an administrator approved the send
     */
    function showScan(flags, bypass) {
        var node = overlay || build();
        resetSteps();
        node.classList.remove("hidden");
        node.style.display = "flex";

        var title = bypass ? "Sending with approval" : "Checking your message";
        node.querySelector("#scan-title").textContent = title;

        var active = STEPS.filter(function (s) {
            if (s.id === "ai") return true;
            return flags ? flags[s.id] !== false : true;
        });

        var index = 0;
        var startedAt = Date.now();

        function advance() {
            if (index > 0) markStep(active[index - 1].id, "done");
            if (index < active.length) {
                markStep(active[index].id, "active");
                index += 1;
                ticker = setTimeout(advance, 380);
            }
        }
        advance();

        var timer = node.querySelector("#scan-elapsed");
        var clock = setInterval(function () {
            timer.textContent = ((Date.now() - startedAt) / 1000).toFixed(1) + "s";
        }, 100);

        return {
            finish: function (stepId) {
                if (stepId) markStep(stepId, "done");
                clearInterval(clock);
                clearTimeout(ticker);
            },
            hide: function () {
                clearInterval(clock);
                clearTimeout(ticker);
                node.style.display = "none";
            }
        };
    }

    function hideScan() {
        if (!overlay) return;
        clearInterval(ticker);
        overlay.style.display = "none";
    }

    /* ------------------------------------------------------------------
       Toasts
       ------------------------------------------------------------------ */

    var ICONS = { success: "check", error: "warning", warn: "warning", info: "spark" };

    function toast(message, type) {
        var container = document.getElementById("toast-container");
        if (!container) return;
        var kind = type || "info";
        var node = document.createElement("div");
        node.className = "toast toast-" + kind;
        node.innerHTML = Icons.svg(ICONS[kind] || "spark", "icon") +
            '<span>' + global.Dom.esc(message) + '</span>';
        container.appendChild(node);

        var life = kind === "error" ? 6000 : 3800;
        setTimeout(function () {
            node.classList.add("out");
            setTimeout(function () { node.remove(); }, 260);
        }, life);
    }

    global.Loading = {
        setLoading: setLoading,
        withButton: withButton,
        showScan: showScan,
        hideScan: hideScan,
        toast: toast
    };
})(window);
