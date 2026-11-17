/* ==========================================================================
   loading.js — button spinners and toasts.

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
       Toasts
       ------------------------------------------------------------------ */

    var ICONS = { success: "check", error: "warning", warn: "warning", info: "shield" };

    function toast(message, type) {
        var container = document.getElementById("toast-container");
        if (!container) return;
        var kind = type || "info";
        var text = global.I18n ? global.I18n.t(message) : message;
        var node = document.createElement("div");
        node.className = "toast toast-" + kind;
        node.innerHTML = Icons.svg(ICONS[kind] || "shield", "icon") +
            "<span>" + global.Dom.esc(text) + "</span>";
        container.appendChild(node);

        var life = kind === "error" ? 6000 : 3800;
        setTimeout(function () {
            node.classList.add("out");
            setTimeout(function () { node.remove(); }, 240);
        }, life);
    }

    global.Loading = {
        setLoading: setLoading,
        withButton: withButton,
        toast: toast
    };
})(window);
