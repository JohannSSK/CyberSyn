/* ==========================================================================
   settings.js — local policy actions and the AI connection.

   The API key is write-only: it is stored encrypted on the server and the
   browser only ever receives a mask back. Changing checks, removing the key,
   or probing a saved key at another destination asks for fresh administrator
   approval and is recorded in the audit log.
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

    var rules = Object.keys(Dom.policyFields);
    var savedMask = "";
    var dirty = false;
    var contextDirty = false;
    var connectionDirty = false;
    var savedConnection = { provider: "auto", base: "", hasKey: false };
    var discoveryVersion = 0;

    var nodes = {
        check1: $("#setting-check1"),
        check2: $("#setting-check2"),
        check3: $("#setting-check3"),
        block_code: $("#setting-block-code"),
        restore: $("#setting-restore-redactions"),
        alsoDefault: $("#also-default"),
        context: $("#setting-context"),
        contextDefault: $("#context-also-default"),
        saveContext: $("#btn-save-context"),
        contextState: $("#context-state"),
        connectionDefault: $("#connection-also-default"),
        clearKey: $("#btn-clear-key"),
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
        connectionState: $("#connection-state"),
        provider: $("#setting-provider"),
        base: $("#setting-base")
    };

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
        },
        {
            key: "block_code",
            name: "Proprietary source code",
            body: " will not be flagged by the code rule."
        }
    ];

    function updateAllOff() {
        var off = CHECK_CONSEQUENCES.filter(function (item) {
            return nodes[item.key].value === "allow";
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

    var SAVED_FLASH_MS = 1500;
    var checksSavedTimer = null;
    var contextSavedTimer = null;
    var connectionSavedTimer = null;

    function clearChecksSaved() {
        if (checksSavedTimer) {
            clearTimeout(checksSavedTimer);
            checksSavedTimer = null;
        }
    }

    function flashChecksSaved() {
        if (!nodes.checksState) return;
        clearChecksSaved();
        nodes.checksState.textContent = t("Saved.");
        checksSavedTimer = setTimeout(function () {
            checksSavedTimer = null;
            if (!dirty && nodes.checksState) nodes.checksState.textContent = "";
        }, SAVED_FLASH_MS);
    }

    function clearContextSaved() {
        if (contextSavedTimer) {
            clearTimeout(contextSavedTimer);
            contextSavedTimer = null;
        }
    }

    function flashContextSaved() {
        if (!nodes.contextState) return;
        clearContextSaved();
        contextDirty = false;
        nodes.contextState.textContent = t("Saved.");
        contextSavedTimer = setTimeout(function () {
            contextSavedTimer = null;
            if (nodes.contextState) nodes.contextState.textContent = "";
        }, SAVED_FLASH_MS);
    }

    function markContextDirty() {
        clearContextSaved();
        contextDirty = true;
        if (nodes.contextState) nodes.contextState.textContent = t("Unsaved changes");
    }

    function flashConnectionSaved() {
        if (!nodes.connectionState) return;
        if (connectionSavedTimer) clearTimeout(connectionSavedTimer);
        connectionDirty = false;
        nodes.connectionState.textContent = t("Saved.");
        connectionSavedTimer = setTimeout(function () {
            connectionSavedTimer = null;
            if (nodes.connectionState) nodes.connectionState.textContent = "";
        }, SAVED_FLASH_MS);
    }

    function markDirty() {
        clearChecksSaved();
        dirty = true;
        nodes.checksState.textContent = t("Unsaved changes");
        updateAllOff();
    }

    function markConnectionDirty() {
        if (connectionSavedTimer) clearTimeout(connectionSavedTimer);
        connectionSavedTimer = null;
        connectionDirty = true;
        if (nodes.connectionState) nodes.connectionState.textContent = t("Unsaved changes");
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

    function applyChecks(data) {
        rules.forEach(function (key) { nodes[key].value = Dom.policyAction(data, key); });
        nodes.restore.checked = data.restore_redactions === true;
        updateAllOff();
        clearChecksSaved();
        dirty = false;
        nodes.checksState.textContent = "";
    }

    function applyContext(data) {
        if (!nodes.context) return;
        var wanted = String(Number(data.CONTEXT_MESSAGES) || 0);
        if (!Array.from(nodes.context.options).some(function (o) { return o.value === wanted; })) {
            var extra = Dom.el("option", "", wanted + " " + t("previous messages"));
            extra.value = wanted;
            nodes.context.appendChild(extra);
        }
        nodes.context.value = wanted;
        clearContextSaved();
        contextDirty = false;
        if (nodes.contextState) nodes.contextState.textContent = "";
    }

    function applyConnection(data) {
        if (data.MODEL_NAME && !Array.from(nodes.model.options).some(function (o) {
            return o.value === data.MODEL_NAME;
        })) {
            nodes.model.appendChild(modelOption(data.MODEL_NAME));
        }
        if (data.MODEL_NAME) nodes.model.value = data.MODEL_NAME;
        if (data.PROVIDER) nodes.provider.value = data.PROVIDER;
        nodes.base.value = data.API_BASE || "";
        updateSavedConnection(data);
    }

    function updateSavedConnection(data) {
        savedMask = data.API_KEY_MASK || "";
        savedConnection = {
            provider: data.PROVIDER || "auto",
            base: data.API_BASE || "",
            hasKey: !!savedMask
        };
        if (nodes.clearKey) nodes.clearKey.classList.toggle("hidden", !savedMask);
        paintKeyState();
    }

    function load() {
        return Api.post("SETTINGS", {}).then(function (data) {
            applyChecks(data);
            applyContext(data);
            applyConnection(data);
            return data;
        });
    }

    /* Changing checks or connection settings is confirmed with a fresh
       administrator password every time and logged in the audit log. */
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
                var payload = {
                    restore_redactions: nodes.restore.checked,
                    also_default: nodes.alsoDefault.checked,
                    admin_token: token
                };
                rules.forEach(function (rule) { payload[Dom.policyFields[rule]] = nodes[rule].value; });
                return Api.post("SETTINGS", payload);
            }).then(function (data) {
                applyChecks(data);
                nodes.alsoDefault.checked = false;
                flashChecksSaved();
                Loading.toast("Safety checks saved.", "success");
            }).catch(function (err) {
                Loading.toast(err.message, "error");
            });
        }).catch(function () { });
    }

    /* How many earlier messages travel with the next prompt. The choice is
       per member, can be copied to the workspace default, and is audited
       like every other setting. */
    function saveContext() {
        approveChange(
            "Conversation context",
            "Changing how much of the conversation is sent to the AI requires the administrator password and is recorded in the audit log."
        ).then(function (token) {
            return Loading.withButton(nodes.saveContext, function () {
                return Api.post("SETTINGS", {
                    CONTEXT_MESSAGES: Number(nodes.context.value),
                    also_default: nodes.contextDefault.checked,
                    admin_token: token
                });
            }).then(function (data) {
                applyContext(data);
                nodes.contextDefault.checked = false;
                flashContextSaved();
                Loading.toast("Conversation context saved.", "success");
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

        approveChange(
            "AI connection",
            "Changing the provider, model or API key requires the administrator password and is recorded in the audit log."
        ).then(function (token) {
            payload.admin_token = token;
            return Loading.withButton(nodes.saveConnection, function () {
                return Api.post("SETTINGS", payload);
            }).then(function (data) {
                nodes.key.value = "";
                discoveryVersion++;
                applyConnection(data);
                nodes.connectionDefault.checked = false;
                flashConnectionSaved();
                Loading.toast("Connection saved.", "success");
                refreshModels();
            }).catch(function (err) {
                Loading.toast(err.message, "error");
            });
        }).catch(function () { });
    }

    /* ------------------------------------------------------------------
       Provider choice & model discovery
       ------------------------------------------------------------------ */

    function loadProviders() {
        return Api.post("PROVIDERS", {}).then(function (data) {
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

    function modelOption(name) {
        var option = Dom.el("option", "", name);
        option.value = name;
        option.setAttribute("data-no-i18n", "");
        return option;
    }

    function showModels(models, providerLabel, keepCurrent) {
        var current = nodes.model.value;
        var retained = keepCurrent && current && models.indexOf(current) === -1;
        nodes.model.replaceChildren();
        if (retained) nodes.model.appendChild(modelOption(current));
        models.forEach(function (name) { nodes.model.appendChild(modelOption(name)); });
        if (retained || models.indexOf(current) !== -1) nodes.model.value = current;
        var where = providerLabel || (isGreek() ? "αυτόν τον πάροχο" : "that provider");
        var summary = isGreek()
            ? (models.length === 1 ? "1 μοντέλο" : Dom.formatNumber(models.length) + " μοντέλα") +
              " στον πάροχο " + where + "."
            : Dom.plural(models.length, "model") + " available on " + where + ".";
        if (retained) summary += " " + t("The current model was kept because it is not in this list.");
        setModelState(summary, "is-ok");
    }

    function refreshModels(options) {
        var opts = options || {};
        var key = nodes.key.value.trim();
        var body = {
            provider: nodes.provider.value || "auto",
            API_BASE: nodes.base.value.trim()
        };
        var version = ++discoveryVersion;
        if (key) body.API_KEY = key;
        if (!key && !savedConnection.hasKey) {
            setModelState(t("Paste a key first to load the models it can reach."));
            return Promise.resolve(null);
        }

        var changed = !key && (
            body.API_BASE !== savedConnection.base ||
            body.provider !== savedConnection.provider
        );
        if (changed && !opts.button) {
            setModelState(t("Refresh the list with administrator approval to use the saved key here."));
            return Promise.resolve(null);
        }

        function request() {
            var grant = changed
                ? Shell.withAdmin({
                    title: "Model discovery",
                    fresh: true,
                    what: "Use the saved key at " + body.provider + " · " +
                        (body.API_BASE || t("Hosted address")) + "?",
                    confirmLabel: "Approve",
                    cancelLabel: "Cancel"
                })
                : Promise.resolve(null);
            return grant.then(function (token) {
                if (version !== discoveryVersion) return null;
                if (token) body.admin_token = token;
                return Api.post("MODELS", body);
            });
        }

        setModelState(t("Checking which models this key can reach…"));
        return (opts.button ? Loading.withButton(nodes.refresh, request) : request())
            .then(function (data) {
                if (!data || version !== discoveryVersion) return null;
                if (!data.models || !data.models.length) {
                    var emptyMsg = data.message && Api.withRemedy
                        ? Api.withRemedy(data.message)
                        : (data.message || "That key returned no usable models. Check the provider and key.");
                    setModelState(t(emptyMsg), "is-error");
                    return null;
                }
                // A saved connection may use a model the listing omits (or
                // spells with a provider prefix). Do not silently replace it.
                showModels(data.models, data.provider_label, !key && !changed);
                if (key && data.provider && data.provider !== "auto") {
                    nodes.provider.value = data.provider;
                }
                return data.models;
            })
            .catch(function (err) {
                if (version === discoveryVersion && !err.cancelled) {
                    setModelState(
                        t(err.message || "Could not load models. Check the key and try again."),
                        "is-error"
                    );
                }
                return null;
            });
    }

    var autoProbe = Dom.debounce(function () {
        if (nodes.key.value.trim().length >= 8) refreshModels();
    }, 900);

    function destinationEdited() {
        discoveryVersion++;
        markConnectionDirty();
        setModelState(t("Refresh the list to check this connection."));
    }

    /* ------------------------------------------------------------------
       Wiring
       ------------------------------------------------------------------ */

    rules.forEach(function (key) {
        if (nodes[key]) Dom.on(nodes[key], "change", markDirty);
    });

    if (nodes.clearKey) {
        Dom.on(nodes.clearKey, "click", function () {
            approveChange(
                "Saved key",
                "Removing the saved API key requires the administrator password and is recorded in the audit log."
            ).then(function (token) {
                return Loading.withButton(nodes.clearKey, function () {
                    return Api.post("SETTINGS", {
                        CLEAR_API_KEY: true,
                        admin_token: token,
                        also_default: nodes.connectionDefault.checked
                    });
                });
            }).then(function (data) {
                nodes.key.value = "";
                discoveryVersion++;
                nodes.connectionDefault.checked = false;
                updateSavedConnection(data);
                setModelState(t("No key saved yet."));
                Loading.toast("Saved key removed.", "success");
            }).catch(function (err) {
                if (err && !err.cancelled) Loading.toast(err.message, "error");
            });
        });
    }

    Dom.on(nodes.restore, "change", markDirty);
    Dom.on(nodes.saveChecks, "click", saveChecks);
    if (nodes.context) Dom.on(nodes.context, "change", markContextDirty);
    Dom.on(nodes.saveContext, "click", saveContext);
    Dom.on(nodes.saveConnection, "click", saveConnection);
    Dom.on(nodes.refresh, "click", function () { refreshModels({ button: true }); });
    Dom.on(nodes.model, "change", markConnectionDirty);
    Dom.on(nodes.provider, "change", function () {
        nodes.base.value = nodes.provider.value === savedConnection.provider
            ? savedConnection.base
            : "";
        markConnectionDirty();
        refreshModels();
    });

    Dom.on(nodes.base, "input", destinationEdited);
    Dom.on(nodes.key, "input", function () {
        destinationEdited();
        if (nodes.key.value.trim().length >= 8) autoProbe();
    });

    Dom.on(document, "cybersyn:lang", function () {
        updateAllOff();
        paintKeyState();
        if (dirty) {
            nodes.checksState.textContent = t("Unsaved changes");
        } else if (checksSavedTimer && nodes.checksState) {
            nodes.checksState.textContent = t("Saved.");
        }
        if (nodes.contextState) {
            if (contextDirty) nodes.contextState.textContent = t("Unsaved changes");
            else if (contextSavedTimer) nodes.contextState.textContent = t("Saved.");
        }
        if (nodes.connectionState) {
            if (connectionDirty) nodes.connectionState.textContent = t("Unsaved changes");
            else if (connectionSavedTimer) nodes.connectionState.textContent = t("Saved.");
        }
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
