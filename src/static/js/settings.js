/* ==========================================================================
   settings.js — local safety check toggles and the AI connection.

   The API key is write-only: it is stored encrypted on the server and the
   browser only ever receives a mask back. Changing checks or connection
   details requires a fresh administrator password confirmation every time.
   ========================================================================== */

(function () {
    "use strict";

    if (!window.Shell.guard()) return;

    var Api = window.Api;
    var Dom = window.Dom;
    var Loading = window.Loading;
    var Shell = window.Shell;
    var $ = Dom.$;

    function t(text) {
        return window.I18n && typeof window.I18n.t === "function"
            ? window.I18n.t(text)
            : text;
    }

    function isGreek() {
        return !!(window.I18n && window.I18n.current() === "el");
    }

    var checks = { check1: true, check2: true, check3: true };
    var savedMask = "";
    var dirty = false;

    var nodes = {
        check1: $("#setting-check1"),
        check2: $("#setting-check2"),
        check3: $("#setting-check3"),
        consequence: $("#checks-consequence"),
        allOff: $("#all-checks-off-note"),
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

    var probedKey = null;
    var BASE_NEEDED = {};

    var CHECK_CONSEQUENCES = [
        {
            key: "check1",
            name: "Personal data",
            body: " (AFM, AMKA, IBAN, phones, Greek IDs, names) will not be flagged."
        },
        {
            key: "check2",
            name: "Context:",
            body: " Legal, financial, HR and customer records will not be flagged."
        },
        {
            key: "check3",
            name: "Prompt-injection",
            body: " attempts will not be flagged."
        }
    ];

    function updateAllOff() {
        var off = CHECK_CONSEQUENCES.filter(function (item) {
            return nodes[item.key] && !nodes[item.key].checked;
        });
        var noneOn = off.length === CHECK_CONSEQUENCES.length;
        var partialOff = off.length > 0 && !noneOn;

        if (nodes.allOff) {
            nodes.allOff.classList.toggle("hidden", !noneOn);
        }
        if (nodes.consequence) {
            nodes.consequence.textContent = "";
            if (partialOff) {
                off.forEach(function (item) {
                    var line = Dom.el("p", "checks-consequence-item");
                    line.appendChild(Dom.el("strong", "", t(item.name)));
                    line.appendChild(document.createTextNode(t(item.body)));
                    nodes.consequence.appendChild(line);
                });
            }
            nodes.consequence.classList.toggle("hidden", !partialOff);
        }
    }

    function markDirty() {
        dirty = true;
        nodes.checksState.textContent = t("Unsaved changes");
        updateAllOff();
    }

    function paintKeyState() {
        if (savedMask) {
            nodes.keyState.textContent = isGreek()
                ? "Αποθηκευμένο κλειδί: " + savedMask + " — επικολλήστε νέο για αντικατάσταση."
                : "Saved key: " + savedMask + " — paste a new one to replace it.";
            nodes.key.placeholder = isGreek()
                ? "Αντικατάσταση κλειδιού " + savedMask
                : "Replace saved key " + savedMask;
        } else {
            nodes.keyState.textContent = t("No key saved yet.");
            nodes.key.placeholder = t("Paste your API key…");
        }
    }

    function apply(data) {
        ["check1", "check2", "check3"].forEach(function (key) {
            checks[key] = data[key] !== false;
            nodes[key].checked = checks[key];
        });
        updateAllOff();
        if (data.MODEL_NAME && !nodes.model.querySelector(
                'option[value="' + data.MODEL_NAME.replace(/"/g, "") + '"]')) {
            var option = document.createElement("option");
            option.value = data.MODEL_NAME;
            option.textContent = data.MODEL_NAME;
            nodes.model.appendChild(option);
        }
        if (data.MODEL_NAME) nodes.model.value = data.MODEL_NAME;
        if (data.PROVIDER) nodes.provider.value = data.PROVIDER;
        nodes.base.value = data.API_BASE || "";
        showBaseField(nodes.provider.value);
        savedMask = data.API_KEY_MASK || "";
        paintKeyState();
        dirty = false;
        nodes.checksState.textContent = "";
    }

    function load() {
        return Api.post("/api/admin/employee/settings", {}).then(function (data) {
            apply(data);
            return data;
        });
    }

    /* Changing checks or connection settings is confirmed with a fresh
       administrator password every time and logged in the audit trail. */
    function approveChange(titleKey, bodyKey) {
        return Shell.withAdmin({
            title: titleKey,
            what: bodyKey,
            confirmLabel: "Approve",
            cancelLabel: "Cancel",
            fresh: true
        }).catch(function (err) {
            if (!err.cancelled) Loading.toast(err.message, "error");
            throw err;
        });
    }

    function saveChecks() {
        approveChange(
            "Safety checks",
            "Changing the local safety checks requires the administrator password and is recorded in the audit log."
        ).then(function (token) {
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
            Loading.toast("Choose a model or paste an API key before saving.", "info");
            return;
        }

        approveChange(
            "AI connection",
            "Changing the provider, model or API key requires the administrator password and is recorded in the audit log."
        ).then(function (token) {
            payload.admin_token = token;
            return Loading.withButton(nodes.saveConnection, function () {
                return Api.post("/api/admin/employee/settings", payload);
            }).then(function (data) {
                nodes.key.value = "";
                apply(data);
                Loading.toast("Connection saved.", "success");
                probedKey = null;
                refreshModels();
            }).catch(function (err) {
                Loading.toast(err.message, "error");
            });
        }).catch(function () { });
    }

    /* ------------------------------------------------------------------
       Provider choice & model discovery
       ------------------------------------------------------------------ */

    function showBaseField(provider) {
        var needs = !!BASE_NEEDED[provider];
        nodes.baseField.classList.toggle("hidden", !needs);
    }

    function loadProviders() {
        return Api.post("/api/admin/employee/providers", {}).then(function (data) {
            (data.providers || []).forEach(function (item) {
                if (item.needs_base) BASE_NEEDED[item.key] = true;
            });
            var current = nodes.provider.value;
            nodes.provider.innerHTML = (data.providers || []).map(function (item) {
                var label = item.key === "auto" ? t("Detect automatically") : item.label;
                return '<option value="' + Dom.esc(item.key) + '">' +
                    Dom.esc(label) + "</option>";
            }).join("");
            nodes.provider.value = current;
        }).catch(function () { });
    }

    function setModelState(text, kind) {
        nodes.modelState.textContent = text;
        nodes.modelState.classList.remove("is-ok", "is-error");
        if (kind) nodes.modelState.classList.add(kind);
    }

    function showModels(models, providerLabel) {
        var current = nodes.model.value;
        nodes.model.innerHTML = models.map(function (name) {
            return '<option value="' + Dom.esc(name) + '">' + Dom.esc(name) + "</option>";
        }).join("");
        if (models.indexOf(current) !== -1) nodes.model.value = current;
        var where = providerLabel || (isGreek() ? "αυτόν τον πάροχο" : "that provider");
        var summary = isGreek()
            ? (models.length === 1 ? "1 μοντέλο" : Dom.formatNumber(models.length) + " μοντέλα") +
              " στον πάροχο " + where + "."
            : Dom.plural(models.length, "model") + " available on " + where + ".";
        setModelState(summary, "is-ok");
    }

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
        setModelState(t("Checking which models this key can reach…"));
        if (opts.button) {
            request = Loading.withButton(nodes.refresh, function () { return request; });
        }

        return request.then(function (data) {
            if (!data.models || !data.models.length) {
                setModelState(
                    t(data.message || "That key returned no usable models. Check the provider and key."),
                    "is-error"
                );
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

    var autoProbe = Dom.debounce(function () { refreshModels(); }, 900);

    /* ------------------------------------------------------------------
       Wiring
       ------------------------------------------------------------------ */

    ["check1", "check2", "check3"].forEach(function (key) {
        Dom.on(nodes[key], "change", markDirty);
    });

    Dom.on(nodes.saveChecks, "click", saveChecks);
    Dom.on(nodes.saveConnection, "click", saveConnection);
    Dom.on(nodes.refresh, "click", function () {
        refreshModels({ button: true, force: true });
    });
    Dom.on(nodes.model, "change", markDirty);
    Dom.on(nodes.provider, "change", function () {
        showBaseField(nodes.provider.value);
        markDirty();
        probedKey = null;
        refreshModels({ force: true });
    });

    Dom.on(nodes.key, "input", function () {
        if (nodes.key.value.trim().length >= 8) autoProbe();
    });

    Dom.on(document, "cybersyn:lang", function () {
        updateAllOff();
        paintKeyState();
        if (dirty) nodes.checksState.textContent = t("Unsaved changes");
        var autoOpt = nodes.provider.querySelector('option[value="auto"]');
        if (autoOpt) autoOpt.textContent = t("Detect automatically");
    });

    loadProviders()
        .then(load)
        .then(function (data) {
            if (data && data.API_KEY_MASK) refreshModels();
        })
        .catch(function (err) { Loading.toast(err.message, "error"); });
})();
