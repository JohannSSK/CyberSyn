/* ==========================================================================
   settings.js — policy toggles and the AI connection.

   The API key is write-only: it is stored encrypted server-side and the
   browser only ever receives a mask back. Typing a key and saving it never
   reveals the one already saved.
   ========================================================================== */

(function () {
    "use strict";

    if (!window.Shell.guard()) return;

    var Api = window.Api;
    var Dom = window.Dom;
    var Loading = window.Loading;
    var $ = Dom.$;

    var checks = { check1: true, check2: true, check3: true };

    var nodes = {
        check1: $("#setting-check1"),
        check2: $("#setting-check2"),
        check3: $("#setting-check3"),
        saveChecks: $("#btn-save-checks"),
        checksState: $("#checks-state"),
        model: $("#setting-model"),
        refresh: $("#btn-refresh-models"),
        key: $("#setting-api-key"),
        keyState: $("#key-state"),
        modelState: $("#model-state"),
        saveConnection: $("#btn-save-connection")
    };

    // The last key we asked about, so a debounced keystroke does not refetch
    // the same thing, and the saved key is only probed once per page load.
    var probedKey = null;

    function markDirty() {
        nodes.checksState.textContent = "Unsaved changes";
    }

    function apply(data) {
        ["check1", "check2", "check3"].forEach(function (key) {
            checks[key] = data[key] !== false;
            nodes[key].checked = checks[key];
        });
        if (data.MODEL_NAME) nodes.model.value = data.MODEL_NAME;
        var mask = data.API_KEY_MASK;
        nodes.keyState.textContent = mask
            ? "Saved key: " + mask + " — paste a new one to replace it."
            : "No key saved yet.";
        nodes.key.placeholder = mask ? "Replace saved key " + mask : "Paste your API key…";
        nodes.checksState.textContent = "";
    }

    function load() {
        return Api.post("/api/admin/employee/settings", {}).then(function (data) {
            apply(data);
            return data;
        });
    }

    function saveChecks() {
        Loading.withButton(nodes.saveChecks, function () {
            return Api.post("/api/admin/employee/settings", {
                check1: nodes.check1.checked,
                check2: nodes.check2.checked,
                check3: nodes.check3.checked
            });
        }).then(function (data) {
            apply(data);
            Loading.toast("Safety checks saved.", "success");
        }).catch(function (err) {
            Loading.toast(err.message, "error");
        });
    }

    function saveConnection() {
        var payload = { MODEL_NAME: nodes.model.value.trim() || "gpt-4o-mini" };
        var key = nodes.key.value.trim();
        if (key) payload.API_KEY = key;

        Loading.withButton(nodes.saveConnection, function () {
            return Api.post("/api/admin/employee/settings", payload);
        }).then(function (data) {
            nodes.key.value = "";
            apply(data);
            Loading.toast("Connection saved.", "success");
            // The stored key just changed, so the list has to be re-asked for.
            probedKey = null;
            refreshModels();
        }).catch(function (err) {
            Loading.toast(err.message, "error");
        });
    }

    /* ------------------------------------------------------------------
       Model discovery

       Listing the models a key can reach is the whole point of pasting one,
       so it happens on its own: as soon as a plausible key is in the field,
       after a save, and once on load for the key already stored. The Refresh
       button stays for when a provider changes underneath you.
       ------------------------------------------------------------------ */

    function setModelState(text, kind) {
        nodes.modelState.textContent = text;
        nodes.modelState.classList.remove("is-ok", "is-error");
        if (kind) nodes.modelState.classList.add(kind);
    }

    function showModels(models) {
        var current = nodes.model.value;
        nodes.model.innerHTML = models.map(function (name) {
            return '<option value="' + Dom.esc(name) + '">' + Dom.esc(name) + "</option>";
        }).join("");
        // Keep the member's choice if the new list still has it.
        if (models.indexOf(current) !== -1) nodes.model.value = current;
        setModelState(Dom.plural(models.length, "model") + " available for this key.", "is-ok");
    }

    // An empty field is not an error: the server falls back to the key already
    // saved for this member, which is what makes the on-load probe work.
    function refreshModels(options) {
        var opts = options || {};
        var key = nodes.key.value.trim();
        if (key === probedKey && !opts.force) return Promise.resolve(null);
        probedKey = key;

        var request = Api.post("/api/admin/employee/models", key ? { API_KEY: key } : {});
        if (opts.button) {
            setModelState("Asking the provider which models this key can reach…");
            request = Loading.withButton(nodes.refresh, function () { return request; });
        } else {
            setModelState("Asking the provider which models this key can reach…");
        }

        return request.then(function (data) {
            if (!data.models || !data.models.length) {
                setModelState(data.message || "That key returned no usable models.", "is-error");
                return null;
            }
            showModels(data.models);
            return data.models;
        }).catch(function (err) {
            setModelState(err.message, "is-error");
            return null;
        });
    }

    // Keys are long; wait until typing settles rather than firing per keystroke.
    var autoProbe = Dom.debounce(function () { refreshModels(); }, 900);

    /* ------------------------------------------------------------------
       Wiring
       ------------------------------------------------------------------ */

    ["check1", "check2", "check3"].forEach(function (key) {
        Dom.on(nodes[key], "change", markDirty);
    });

    Dom.on(nodes.saveChecks, "click", saveChecks);
    Dom.on(nodes.saveConnection, "click", saveConnection);
    Dom.on(nodes.refresh, "click", function () { refreshModels({ button: true, force: true }); });
    Dom.on(nodes.model, "change", markDirty);

    // Probe as the key is typed, but only once it looks like a real key —
    // a couple of characters would only produce a provider rejection.
    Dom.on(nodes.key, "input", function () {
        if (nodes.key.value.trim().length >= 8) autoProbe();
    });

    load()
        .then(function (data) {
            // A key is already stored: list what it reaches, without a click.
            if (data && data.API_KEY_MASK) refreshModels();
        })
        .catch(function (err) { Loading.toast(err.message, "error"); });
})();
