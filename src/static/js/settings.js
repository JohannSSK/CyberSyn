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

    var Shell = window.Shell;

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
        saveConnection: $("#btn-save-connection"),
        provider: $("#setting-provider"),
        base: $("#setting-base"),
        baseField: $("#field-base")
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
        if (data.MODEL_NAME && !nodes.model.querySelector(
                'option[value="' + data.MODEL_NAME.replace(/"/g, "") + '"]')) {
            // Keep the saved model visible even before the list is fetched.
            var option = document.createElement("option");
            option.value = data.MODEL_NAME;
            option.textContent = data.MODEL_NAME;
            nodes.model.appendChild(option);
        }
        if (data.MODEL_NAME) nodes.model.value = data.MODEL_NAME;
        if (data.PROVIDER) nodes.provider.value = data.PROVIDER;
        nodes.base.value = data.API_BASE || "";
        showBaseField(nodes.provider.value);
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

    /* Turning a check off weakens the gate for everyone sending through this
       account, so it is confirmed with the administrator password every time
       — never remembered from an earlier approval. */
    function approveChange(what) {
        return Shell.withAdmin({
            title: "Change " + what,
            what: "Changing " + what +
                  " needs the administrator password. It is recorded in the audit trail.",
            confirmLabel: "Approve",
            cancelLabel: "Cancel",
            fresh: true
        }).catch(function (err) {
            if (!err.cancelled) Loading.toast(err.message, "error");
            throw err;
        });
    }

    function saveChecks() {
        approveChange("the safety checks").then(function (token) {
            return Loading.withButton(nodes.saveChecks, function () {
                return Api.post("/api/admin/employee/settings", {
                    check1: nodes.check1.checked,
                    check2: nodes.check2.checked,
                    check3: nodes.check3.checked,
                    admin_token: token
                });
            }).then(function (data) {
                apply(data);
                Loading.toast("Safety checks saved.", "success");
            }).catch(function (err) {
                Loading.toast(err.message, "error");
            });
        }).catch(function () { });
    }

    function saveConnection() {
        var payload = {};
        if (nodes.model.value.trim()) payload.MODEL_NAME = nodes.model.value.trim();
        if (nodes.provider.value) payload.PROVIDER = nodes.provider.value;
        if (nodes.base.value.trim()) payload.API_BASE = nodes.base.value.trim();
        var key = nodes.key.value.trim();
        if (key) payload.API_KEY = key;
        if (!Object.keys(payload).length) {
            Loading.toast("Nothing to save yet.", "warn");
            return;
        }

        approveChange("the AI connection").then(function (token) {
            payload.admin_token = token;
            return Loading.withButton(nodes.saveConnection, function () {
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
        }).catch(function () { });
    }

    /* ------------------------------------------------------------------
       Provider choice

       "Detect" is the default and needs no thought: the key is offered to
       each provider in turn and the one that answers is used. Naming one
       explicitly is there for the cases detection cannot tell apart —
       several providers hand out `sk-`-shaped keys.
       ------------------------------------------------------------------ */

    function showBaseField(provider) {
        var needs = !!BASE_NEEDED[provider];
        nodes.baseField.classList.toggle("hidden", !needs);
    }

    var BASE_NEEDED = {};

    function loadProviders() {
        return Api.post("/api/admin/employee/providers", {}).then(function (data) {
            (data.providers || []).forEach(function (item) {
                if (item.needs_base) BASE_NEEDED[item.key] = true;
            });
            var current = nodes.provider.value;
            nodes.provider.innerHTML = (data.providers || []).map(function (item) {
                return '<option value="' + Dom.esc(item.key) + '">' +
                    Dom.esc(item.label) + "</option>";
            }).join("");
            nodes.provider.value = current;
        }).catch(function () {
            // The page still works: "detect" is enough on its own.
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

    function showModels(models, providerLabel) {
        var current = nodes.model.value;
        // Names arrive namespaced ("groq/llama-3.3-70b"), which is both what
        // gets sent to the model and a reminder of where it is going.
        nodes.model.innerHTML = models.map(function (name) {
            return '<option value="' + Dom.esc(name) + '">' + Dom.esc(name) + "</option>";
        }).join("");
        // Keep the member's choice if the new list still has it.
        if (models.indexOf(current) !== -1) nodes.model.value = current;
        setModelState(
            Dom.plural(models.length, "model") + " on " +
            (providerLabel || "that provider") + ".", "is-ok");
    }

    // An empty field is not an error: the server falls back to the key already
    // saved for this member, which is what makes the on-load probe work.
    function refreshModels(options) {
        var opts = options || {};
        var key = nodes.key.value.trim();
        if (key === probedKey && !opts.force) return Promise.resolve(null);
        probedKey = key;

        var body = key ? { API_KEY: key } : {};
        if (nodes.provider.value && nodes.provider.value !== "auto") {
            body.provider = nodes.provider.value;
        }
        if (nodes.base.value.trim()) body.API_BASE = nodes.base.value.trim();
        var request = Api.post("/api/admin/employee/models", body);
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
            showModels(data.models, data.provider_label);
            if (data.provider && data.provider !== "auto") {
                nodes.provider.value = data.provider;
                showBaseField(data.provider);
            }
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
    Dom.on(nodes.provider, "change", function () {
        showBaseField(nodes.provider.value);
        markDirty();
        // Naming a provider can only narrow the list, so it is worth asking.
        probedKey = null;
        refreshModels({ force: true });
    });

    // Probe as the key is typed, but only once it looks like a real key —
    // a couple of characters would only produce a provider rejection.
    Dom.on(nodes.key, "input", function () {
        if (nodes.key.value.trim().length >= 8) autoProbe();
    });

    loadProviders()
        .then(load)
        .then(function (data) {
            // A key is already stored: list what it reaches, without a click.
            if (data && data.API_KEY_MASK) refreshModels();
        })
        .catch(function (err) { Loading.toast(err.message, "error"); });
})();
