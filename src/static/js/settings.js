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
        saveConnection: $("#btn-save-connection"),
        disableAll: $("#btn-disable-all"),
        enableAll: $("#btn-enable-all")
    };

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
        return Api.post("/api/admin/employee/settings", {}).then(apply);
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
        }).catch(function (err) {
            Loading.toast(err.message, "error");
        });
    }

    function refreshModels() {
        var key = nodes.key.value.trim();
        if (!key) {
            Loading.toast("Paste your API key first, then refresh.", "warn");
            nodes.key.focus();
            return;
        }
        Loading.withButton(nodes.refresh, function () {
            return Api.post("/api/admin/employee/models", { API_KEY: key });
        }).then(function (data) {
            if (!data.models || !data.models.length) {
                Loading.toast(data.message || "That key returned no usable models.", "warn");
                return;
            }
            var current = nodes.model.value;
            nodes.model.innerHTML = data.models.map(function (name) {
                return '<option value="' + Dom.esc(name) + '">' + Dom.esc(name) + "</option>";
            }).join("");
            if (data.models.indexOf(current) !== -1) nodes.model.value = current;
            Loading.toast(data.models.length + " models available.", "success");
        }).catch(function (err) {
            Loading.toast(err.message, "error");
        });
    }

    function setAll(value) {
        nodes.check1.checked = value;
        nodes.check2.checked = value;
        nodes.check3.checked = value;
        markDirty();
    }

    /* ------------------------------------------------------------------
       Wiring
       ------------------------------------------------------------------ */

    ["check1", "check2", "check3"].forEach(function (key) {
        Dom.on(nodes[key], "change", markDirty);
    });

    Dom.on(nodes.saveChecks, "click", saveChecks);
    Dom.on(nodes.saveConnection, "click", saveConnection);
    Dom.on(nodes.refresh, "click", refreshModels);
    Dom.on(nodes.disableAll, "click", function () { setAll(false); });
    Dom.on(nodes.enableAll, "click", function () { setAll(true); });
    Dom.on(nodes.model, "change", markDirty);

    load().catch(function (err) { Loading.toast(err.message, "error"); });
})();
