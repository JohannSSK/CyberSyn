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

    var flags = ["check1", "check2", "check3", "block_code"];

    var Shell = window.Shell;

    var nodes = {
        block_code: $("#setting-block-code"),
        alsoDefault: $("#also-default"),
        connectionDefault: $("#connection-also-default"),
        clearKey: $("#btn-clear-key"),
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
        base: $("#setting-base")
    };

    var savedConnection = { provider: "auto", base: "", hasKey: false };
    var discoveryVersion = 0;

    function markDirty() {
        nodes.checksState.textContent = "Unsaved changes";
    }

    function apply(data) {
        flags.forEach(function (key) {
            nodes[key].checked = !!data[key];
        });
        if (data.MODEL_NAME && !Array.from(nodes.model.options).some(function (o) { return o.value === data.MODEL_NAME; })) {
            // Keep the saved model visible even before the list is fetched.
            var option = document.createElement("option");
            option.value = data.MODEL_NAME;
            option.textContent = data.MODEL_NAME;
            nodes.model.appendChild(option);
        }
        if (data.MODEL_NAME) nodes.model.value = data.MODEL_NAME;
        if (data.PROVIDER) nodes.provider.value = data.PROVIDER;
        nodes.base.value = data.API_BASE || "";
        var mask = data.API_KEY_MASK;
        savedConnection = { provider: data.PROVIDER || "auto", base: nodes.base.value, hasKey: !!mask };
        nodes.clearKey.classList.toggle("hidden", !mask);
        nodes.keyState.textContent = mask
            ? "Saved key: " + mask + " — paste a new one to replace it."
            : "No key saved yet.";
        nodes.key.placeholder = mask ? "Replace saved key " + mask : "Paste your API key…";
        nodes.checksState.textContent = "";
    }

    function load() {
        return Api.post("SETTINGS", {}).then(function (data) {
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
                return Api.post("SETTINGS", {
                    check1: nodes.check1.checked,
                    check2: nodes.check2.checked,
                    check3: nodes.check3.checked,
                    block_code: nodes.block_code.checked,
                    also_default: nodes.alsoDefault.checked,
                    admin_token: token
                });
            }).then(function (data) {
                apply(data);
                nodes.alsoDefault.checked = false;
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
        payload.API_BASE = nodes.base.value.trim();
        payload.also_default = nodes.connectionDefault.checked;
        var key = nodes.key.value.trim();
        if (key) payload.API_KEY = key;
        if (!Object.keys(payload).length) {
            Loading.toast("Nothing to save yet.", "warn");
            return;
        }

        approveChange("the AI connection").then(function (token) {
            payload.admin_token = token;
            return Loading.withButton(nodes.saveConnection, function () {
                return Api.post("SETTINGS", payload);
            }).then(function (data) {
                nodes.key.value = "";
                apply(data);
                Loading.toast("Connection saved.", "success");
                // The stored key just changed, so the list has to be re-asked for.
                nodes.connectionDefault.checked = false;
                if (savedConnection.hasKey) refreshModels();
            }).catch(function (err) {
                Loading.toast(err.message, "error");
            });
        }).catch(function () { });
    }

    /* ------------------------------------------------------------------
       Provider choice

       Automatic detection only contacts the service matching the key prefix.
       ------------------------------------------------------------------ */

    function loadProviders() {
        return Api.post("PROVIDERS", {}).then(function (data) {
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
            models.length + " " + Dom.plural(models.length, "model") + " on " +
            (providerLabel || "that provider") + ".", "is-ok");
    }

    // An empty field is not an error: the server falls back to the key already
    // saved for this member, which is what makes the on-load probe work.
    function refreshModels(options) {
        var opts = options || {};
        var key = nodes.key.value.trim();
        var body = { provider: nodes.provider.value || "auto", API_BASE: nodes.base.value.trim() };
        var version = ++discoveryVersion;
        if (key) body.API_KEY = key;
        if (!key && !savedConnection.hasKey) {
            setModelState("Paste a key first to load the models it can reach.");
            return Promise.resolve(null);
        }
        var changed = !key && (body.API_BASE !== savedConnection.base ||
            body.provider !== savedConnection.provider);
        if (changed && !opts.button) {
            setModelState("Refresh the list with administrator approval to use the saved key here.");
            return Promise.resolve(null);
        }
        function request() {
            // Confirm the actual destination, not just a generic connection change.
            var grant = changed ? Shell.withAdmin({ title: "Model discovery", fresh: true,
                what: "Use the saved key at " + body.provider + " · " + (body.API_BASE || "hosted address") + "?",
                confirmLabel: "Approve", cancelLabel: "Cancel" }) : Promise.resolve(null);
            return grant.then(function (token) {
                if (version !== discoveryVersion) return null;
                if (token) body.admin_token = token;
                return Api.post("MODELS", body);
            });
        }
        setModelState("Asking the provider which models this key can reach…");
        return (opts.button ? Loading.withButton(nodes.refresh, request) : request()).then(function (data) {
            if (!data || version !== discoveryVersion) return null;
            if (!data.models || !data.models.length) {
                setModelState(data.message || "That key returned no usable models.", "is-error");
                return null;
            }
            showModels(data.models, data.provider_label);
            if (key && data.provider && data.provider !== "auto") {
                nodes.provider.value = data.provider;
            }
            return data.models;
        }).catch(function (err) {
            if (version === discoveryVersion && !err.cancelled) setModelState(err.message, "is-error");
            return null;
        });
    }

    // Keys are long; wait until typing settles rather than firing per keystroke.
    var autoProbe = Dom.debounce(function () { refreshModels(); }, 900);

    /* ------------------------------------------------------------------
       Wiring
       ------------------------------------------------------------------ */

    flags.forEach(function (key) {
        Dom.on(nodes[key], "change", markDirty);
    });

    Dom.on(nodes.clearKey, "click", function () {
        approveChange("the saved key").then(function (token) {
            return Api.post("SETTINGS", { CLEAR_API_KEY: true, admin_token: token, also_default: nodes.connectionDefault.checked });
        }).then(function (data) {
            nodes.key.value = "";
            discoveryVersion++;
            nodes.connectionDefault.checked = false;
            apply(data);
            setModelState("No key saved yet.");
        }).catch(function (err) { if (!err.cancelled) Loading.toast(err.message, "error"); });
    });
    Dom.on(nodes.saveChecks, "click", saveChecks);
    Dom.on(nodes.saveConnection, "click", saveConnection);
    Dom.on(nodes.refresh, "click", function () { refreshModels({ button: true }); });
    Dom.on(nodes.model, "change", markDirty);
    Dom.on(nodes.provider, "change", function () {
        nodes.base.value = nodes.provider.value === savedConnection.provider ? savedConnection.base : "";
        markDirty();
        refreshModels();
    });

    // Probe as the key is typed, but only once it looks like a real key —
    // a couple of characters would only produce a provider rejection.
    Dom.on(nodes.base, "input", function () { discoveryVersion++; });
    Dom.on(nodes.key, "input", function () {
        discoveryVersion++;
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
