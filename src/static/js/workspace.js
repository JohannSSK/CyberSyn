/* ==========================================================================
   workspace.js — the chat screen.

   Owns: the conversation list, first-run starter prompts, live three-stage
   screening tracker, teaching-moment blocked cards, one-off administrator
   override, post-block grace note, per-message actions and in-chat search.
   ========================================================================== */

(function () {
    "use strict";

    if (!window.Shell.guard()) return;

    var Api = window.Api;
    var Dom = window.Dom;
    var Icons = window.Icons;
    var Loading = window.Loading;
    var Shell = window.Shell;
    var Stages = window.Stages;
    var $ = Dom.$;

    function t(text) {
        return window.I18n && typeof window.I18n.t === "function"
            ? window.I18n.t(text)
            : text;
    }

    function reducedMotion() {
        return !!(window.matchMedia &&
            window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    }

    var DRAFT_CHAT_KEY = "__draft__";

    var state = {
        chats: [],
        chatsLoaded: false,
        chatId: null,
        messages: [],
        settings: { check1: true, check2: true, check3: true },
        checksCount: null,
        query: "",
        busy: false,
        // Per-chat session memory for D4 grace note and override receipts.
        blockedChats: {},
        gracedChats: {},
        gracedMessages: {},
        overriddenMessages: {}
    };

    var nodes = {
        list: $("#chat-list"),
        stream: $("#chat-messages"),
        viewport: $("#chat-stream"),
        title: $("#active-chat-title"),
        input: $("#prompt-input"),
        form: $("#form-send"),
        send: $("#btn-send"),
        newChat: $("#btn-new-chat"),
        deleteChat: $("#btn-delete-chat"),
        rename: $("#btn-rename-chat"),
        search: $("#chat-search"),
        searchBox: $(".search-box"),
        searchClear: $("#search-clear"),
        searchCount: $("#search-count"),
        checksSummary: $("#checks-summary"),
        checksStatus: $("#checks-status"),
        firstRunTpl: $("#first-run-template")
    };

    function currentChatKey() {
        return state.chatId ? String(state.chatId) : DRAFT_CHAT_KEY;
    }

    /* ------------------------------------------------------------------
       Helpers
       ------------------------------------------------------------------ */

    function iconButton(name, title, action, danger) {
        var label = t(title);
        var btn = Dom.el("button", "icon-btn" + (danger ? " danger" : ""));
        btn.type = "button";
        btn.title = label;
        btn.setAttribute("aria-label", label);
        btn.innerHTML = Icons.html(name);
        Dom.on(btn, "click", action);
        return btn;
    }

    function autoGrow() {
        nodes.input.style.height = "auto";
        nodes.input.style.height = Math.min(nodes.input.scrollHeight, 180) + "px";
    }

    function fillComposer(text) {
        nodes.input.value = text;
        autoGrow();
        nodes.input.focus();
        nodes.input.setSelectionRange(text.length, text.length);
    }

    function scrollToEnd(smooth) {
        var useSmooth = smooth && !reducedMotion();
        requestAnimationFrame(function () {
            nodes.viewport.scrollTo({
                top: nodes.viewport.scrollHeight,
                behavior: useSmooth ? "smooth" : "auto"
            });
        });
    }

    /* ------------------------------------------------------------------
       Three-stage tracker — shared by the in-flight card and the blocked
       receipt so order, labels and state come from one source (Stages).
       ------------------------------------------------------------------ */

    function buildTracker(outcome) {
        return Stages.tracker(state.settings, outcome);
    }

    /* ------------------------------------------------------------------
       In-flight screening receipt (D2)

       Shows the three checks in configured order (personal data -> context
       -> injection) with neutral warm-grey dots while the request is open,
       and resolves straight from the server verdict (--danger on the
       blocking stage, --success on clean completion) with no fake timers.
       ------------------------------------------------------------------ */

    var LONG_WAIT_MS = 8000;
    var pending = null;

    function showPending(promptText, bypass) {
        hidePending();

        var enabled = ["check1", "check2", "check3"].filter(function (id) {
            return state.settings[id] !== false;
        });
        var checking = !bypass && enabled.length > 0;

        var wrap = Dom.el("div", "msg");
        var head = Dom.el("div", "msg-head");
        head.innerHTML = Icons.html("profile") +
            '<span class="who">' + Dom.esc(t("You")) + "</span>";
        wrap.appendChild(head);
        wrap.appendChild(Dom.el("div", "bubble bubble-user", promptText));

        var note = Dom.el("div", "msg-pending");

        var tracker = null;
        if (checking) {
            tracker = buildTracker({ checking: true });
            note.appendChild(tracker);
        }

        var line = Dom.el("div", "pending-line");
        var label = Dom.el("span", "pending-text");
        label.setAttribute("role", "status");
        label.setAttribute("aria-live", "polite");

        var labelKey = bypass
            ? "Sending once with administrator approval…"
            : (!enabled.length
                ? "Waiting for the AI reply…"
                : "Checking locally before sending…");
        var slowKey = checking
            ? "Still checking — normal on a long paste."
            : "Still waiting — normal on a long paste.";
        var resolvedClean = false;

        label.textContent = t(labelKey);
        line.appendChild(label);

        var elapsed = Dom.el("span", "pending-elapsed", "0.0s");
        elapsed.setAttribute("aria-hidden", "true");
        elapsed.setAttribute("data-no-i18n", "");
        line.appendChild(elapsed);

        var slow = Dom.el("span", "pending-slow hidden");
        slow.setAttribute("aria-hidden", "true");
        line.appendChild(slow);

        note.appendChild(line);
        wrap.appendChild(note);
        nodes.stream.appendChild(wrap);
        scrollToEnd(true);

        var startedAt = Date.now();
        var slowShown = false;
        var elapsedTimer = setInterval(function () {
            var ms = Math.max(0, Date.now() - startedAt);
            elapsed.textContent = (ms / 1000).toFixed(1) + "s";
            if (!slowShown && ms >= LONG_WAIT_MS) {
                slowShown = true;
                slow.textContent = t(slowKey);
                slow.classList.remove("hidden");
            }
        }, 100);

        function stopTimer() {
            if (elapsedTimer !== null) {
                clearInterval(elapsedTimer);
                elapsedTimer = null;
            }
        }

        pending = {
            wrap: wrap,
            relocalise: function () {
                label.textContent = t(resolvedClean ? "All checks passed." : labelKey);
                if (slowShown) slow.textContent = t(slowKey);
            },
            resolve: function (blockedStage) {
                stopTimer();
                slow.classList.add("hidden");
                if (!tracker) return;
                var replacement = buildTracker(
                    blockedStage ? { blockedStage: blockedStage } : { passedAll: true }
                );
                tracker.replaceWith(replacement);
                tracker = replacement;
                if (!blockedStage) {
                    resolvedClean = true;
                    label.textContent = t("All checks passed.");
                }
            },
            stop: function () {
                stopTimer();
                if (wrap.parentNode) wrap.remove();
            }
        };
        return pending;
    }

    function hidePending() {
        if (pending) pending.stop();
        pending = null;
    }

    /* ------------------------------------------------------------------
       Checks status pill (B6 + D7 off -> on ring pulse)
       ------------------------------------------------------------------ */

    function updateChecksBadge() {
        var on = ["check1", "check2", "check3"].filter(function (k) {
            return state.settings[k];
        }).length;
        var summary = t(on + " of 3 checks active");
        nodes.checksSummary.textContent = summary;
        nodes.checksStatus.title = summary;
        nodes.checksStatus.setAttribute("aria-label", summary);
        nodes.checksStatus.classList.toggle("off", on === 0);
        nodes.checksStatus.classList.toggle("is-all-on", on === 3);

        if (state.checksCount === 0 && on > 0 && !reducedMotion()) {
            nodes.checksStatus.classList.remove("is-pulsing");
            void nodes.checksStatus.offsetWidth;
            nodes.checksStatus.classList.add("is-pulsing");
        }
        state.checksCount = on;
    }

    Dom.on(nodes.checksStatus, "animationend", function () {
        nodes.checksStatus.classList.remove("is-pulsing");
    });

    /* ------------------------------------------------------------------
       Conversation list
       ------------------------------------------------------------------ */

    function renderChatList() {
        nodes.list.innerHTML = "";
        if (!state.chats.length) {
            nodes.list.appendChild(Dom.el(
                "p",
                "chat-list-empty",
                t("No conversations yet — your chats appear here once you send a message.")
            ));
            return;
        }
        state.chats.forEach(function (chat) {
            var item = Dom.el("button", "chat-item");
            item.type = "button";
            item.title = chat.title || t("New chat");
            if (chat.id === state.chatId) item.classList.add("is-active");
            item.innerHTML = Icons.html("chat") +
                '<span class="chat-item-title">' + Dom.esc(chat.title) + "</span>" +
                '<span class="chat-item-meta">' + Dom.esc(Dom.timeAgo(chat.updated_at)) + "</span>";
            Dom.on(item, "click", function () { openChat(chat.id); });
            nodes.list.appendChild(item);
        });
    }

    function loadChats() {
        return Api.post("/api/admin/employee/chats", {}).then(function (data) {
            state.chats = data.chats || [];
            state.chatsLoaded = true;
            renderChatList();
        });
    }

    /* ------------------------------------------------------------------
       Message rendering & empty states (D1, D4, D5)
       ------------------------------------------------------------------ */

    function renderMessage(message) {
        var wrap = Dom.el("div", "msg");
        wrap.dataset.id = message.id || "";

        var head = Dom.el("div", "msg-head");
        head.innerHTML = Icons.html("profile") +
            '<span class="who">' + Dom.esc(t("You")) + "</span>" +
            "<span>·</span><span>" + Dom.esc(Dom.stamp(message.created_at)) + "</span>" +
            (message.edited ? "<span>· " + Dom.esc(t("edited")) + "</span>" : "");
        wrap.appendChild(head);

        var mine = Dom.el("div", "bubble bubble-user");
        var mineText = Dom.el("p");
        mineText.textContent = message.prompt || "";
        mine.appendChild(mineText);
        Dom.highlightText(mineText, state.query);
        wrap.appendChild(mine);

        var hasAnswer = message.answer && String(message.answer).trim() !== "" &&
            String(message.answer) !== "NULL";
        if (hasAnswer) {
            var reply = Dom.el("div", "bubble bubble-ai");
            reply.innerHTML = window.Markdown.render(message.answer);
            Dom.highlightText(reply, state.query);
            wrap.appendChild(reply);
        }

        // Approved override amber receipt (Section 6)
        if (message.id && state.overriddenMessages[message.id]) {
            wrap.appendChild(Dom.el(
                "p",
                "msg-receipt msg-receipt-override",
                t("Sent once with administrator approval — this was logged.")
            ));
        } else if (message.id && state.gracedMessages[message.id]) {
            // Once-per-chat grace note after rewriting a blocked prompt (D4)
            wrap.appendChild(Dom.el(
                "p",
                "msg-receipt msg-receipt-grace",
                t("Nicely rewritten — that went through cleanly.")
            ));
        }

        var actions = Dom.el("div", "msg-actions");
        actions.appendChild(iconButton("copy", "Copy the answer", function () {
            Dom.copyText(message.answer || "")
                .then(function () { Loading.toast("Answer copied.", "success"); })
                .catch(function () {
                    Loading.toast("Clipboard access was blocked — select the text to copy it.", "error");
                });
        }));
        actions.appendChild(iconButton("edit", "Edit this message", function () {
            beginEdit(wrap, message);
        }));
        if (hasAnswer) {
            actions.appendChild(iconButton("regenerate", "Generate a different answer", function () {
                regenerate(message, actions);
            }));
        }
        actions.appendChild(iconButton("delete", "Delete this message", function () {
            removeMessage(message, actions);
        }, true));
        wrap.appendChild(actions);

        return wrap;
    }

    function matchesQuery(message) {
        if (!state.query) return true;
        var needle = state.query.toLowerCase();
        return String(message.prompt || "").toLowerCase().indexOf(needle) !== -1 ||
            String(message.answer || "").toLowerCase().indexOf(needle) !== -1;
    }

    function renderFirstRun() {
        if (!nodes.firstRunTpl || !nodes.firstRunTpl.content) return false;
        var fragment = nodes.firstRunTpl.content.cloneNode(true);
        Dom.$$("[data-starter]", fragment).forEach(function (chip) {
            Dom.on(chip, "click", function () {
                fillComposer(chip.textContent.trim());
            });
        });
        nodes.stream.appendChild(fragment);
        if (window.I18n && typeof window.I18n.apply === "function") {
            window.I18n.apply();
        }
        return true;
    }

    function emptyStream(title, body, icon) {
        nodes.stream.innerHTML =
            '<div class="empty">' + Icons.html(icon, "icon") +
            "<h2>" + Dom.esc(title) + "</h2><p>" + Dom.esc(body) + "</p></div>";
    }

    function renderMessages() {
        var query = state.query;
        var visible = query ? state.messages.filter(matchesQuery) : state.messages;
        nodes.stream.innerHTML = "";

        if (!visible.length) {
            if (query) {
                var missBody = (window.I18n && window.I18n.current() === "el")
                    ? "Κανένα μήνυμα σε αυτή τη συνομιλία δεν περιέχει «" + query +
                      "». Δοκιμάστε άλλη λέξη ή πατήστε Esc."
                    : 'No message in this chat mentions "' + query +
                      '". Try another word or press Esc to show all messages.';
                emptyStream(t("No messages match"), missBody, "search");
            } else if (state.chatsLoaded && state.chats.length === 0) {
                // D1: shown only when the member has zero conversations at all.
                if (!renderFirstRun()) {
                    emptyStream(
                        t("What are we working on today?"),
                        t("Every message is checked on this computer through three local checks before it reaches the AI."),
                        "chat"
                    );
                }
            } else {
                emptyStream(
                    t("Start the conversation"),
                    t("Write a message below. Every line is checked on this computer before it reaches the AI."),
                    "chat"
                );
            }
        } else {
            visible.forEach(function (message) {
                nodes.stream.appendChild(renderMessage(message));
            });
            if (!query) scrollToEnd(false);
        }

        nodes.searchCount.classList.toggle("hidden", !query);
        nodes.searchClear.classList.toggle("hidden", !query);
        if (nodes.searchBox) nodes.searchBox.classList.toggle("has-count", !!query);
        if (query) {
            nodes.searchCount.textContent = t(Dom.plural(visible.length, "message"));
        }
    }

    /* ------------------------------------------------------------------
       Per-message actions
       ------------------------------------------------------------------ */

    function beginEdit(wrap, message) {
        if (wrap.querySelector(".msg-edit")) return;
        wrap.classList.add("is-editing");
        var editor = Dom.el("div", "msg-edit");
        editor.innerHTML =
            '<textarea class="msg-edit-input" aria-label="' +
            Dom.esc(t("Edit this message")) + '"></textarea>' +
            '<div class="msg-edit-actions">' +
            '  <button type="button" class="btn btn-sm btn-ghost msg-edit-cancel">' +
            Dom.esc(t("Cancel")) + "</button>" +
            '  <button type="button" class="btn btn-sm btn-primary msg-edit-save">' +
            Dom.esc(t("Save")) + "</button>" +
            "</div>";

        var textarea = editor.querySelector("textarea");
        textarea.value = message.prompt;

        var cancel = editor.querySelector(".msg-edit-cancel");
        var save = editor.querySelector(".msg-edit-save");

        Dom.on(cancel, "click", function () {
            wrap.classList.remove("is-editing");
            editor.remove();
        });

        Dom.on(save, "click", function () {
            var next = textarea.value.trim();
            if (!next) {
                Loading.toast("That message was empty — type a line first.", "warn");
                textarea.focus();
                return;
            }
            if (next === message.prompt) {
                wrap.classList.remove("is-editing");
                editor.remove();
                return;
            }
            Loading.withButton(save, function () {
                return Api.post("/api/admin/employee/chats/message/edit", {
                    chat_id: state.chatId,
                    message_id: message.id,
                    text: next
                });
            }).then(function (data) {
                state.messages = data.messages || [];
                renderMessages();
                loadChats();
                Loading.toast("Message updated.", "success");
            }).catch(function (err) {
                Loading.toast(err.message, "error");
            });
        });

        wrap.appendChild(editor);
        textarea.focus();
    }

    function removeMessage(message, button) {
        Shell.confirm({
            eyebrow: "Remove message",
            title: "Delete this message?",
            lost: "Removed: this message and its reply leave the conversation.",
            kept: "Kept: workspace block and activity logs stay intact.",
            confirmLabel: "Delete message",
            cancelLabel: "Keep message",
            danger: true
        }).then(function (accepted) {
            if (!accepted) return null;
            return Loading.withButton(button, function () {
                return Api.post("/api/admin/employee/chats/message/delete", {
                    chat_id: state.chatId,
                    message_id: message.id
                });
            }).then(function (data) {
                state.messages = data.messages || [];
                renderMessages();
                loadChats();
                Loading.toast("Message deleted.", "success");
            }).catch(function (err) {
                Loading.toast(err.message, "error");
            });
        });
    }

    function regenerate(message, button) {
        Loading.withButton(button, function () {
            return Api.post("/api/admin/employee/chat/regenerate", {
                chat_id: state.chatId,
                message_id: message.id
            }, { timeout: requestBudget() });
        }).then(function (data) {
            if (data.blocked) {
                renderBlocked(data.block_info || {}, message.prompt || "");
                return;
            }
            state.messages = data.messages || [];
            renderMessages();
            Loading.toast("New answer ready.", "success");
        }).catch(function (err) {
            Loading.toast(err.message, "error");
        });
    }

    /* ------------------------------------------------------------------
       Blocked message card + "Why?" trace expander + one-off override (D3)
       ------------------------------------------------------------------ */

    function renderBlocked(blockInfo, promptText) {
        // Clear any empty-state notice if this was the chat's first attempt.
        var emptyNode = nodes.stream.querySelector(".first-run, .empty");
        if (emptyNode) emptyNode.remove();

        var wrap = Dom.el("div", "msg");

        var head = Dom.el("div", "msg-head");
        head.innerHTML = Icons.html("profile") +
            '<span class="who">' + Dom.esc(t("You")) + "</span>";
        wrap.appendChild(head);
        wrap.appendChild(Dom.el("div", "bubble bubble-user", promptText));

        var card = Dom.el("div", "bubble bubble-blocked");

        // Resolved three-stage receipt: shows where screening stopped.
        var receipt = buildTracker({ blockedStage: blockInfo.stage || "check1" });
        receipt.classList.add("blocked-tracker");
        card.appendChild(receipt);

        var header = Dom.el("div", "blocked-head");
        header.innerHTML = Icons.svg("warning", "icon") +
            '<h3 class="blocked-verdict">' +
            Dom.esc(Stages.verdict(blockInfo.stage)) + "</h3>";
        card.appendChild(header);

        card.appendChild(Dom.el(
            "p",
            "blocked-what",
            t("Nothing left this computer. Your message stayed here and was not sent to the AI.")
        ));
        card.appendChild(Dom.el("p", "blocked-why", Stages.reason(blockInfo)));

        // Every item the check flagged, with its category, line and snippet.
        var found = Array.isArray(blockInfo.matches) && blockInfo.matches.length
            ? blockInfo.matches
            : [{
                main_cause: blockInfo.main_cause,
                line: blockInfo.line,
                start_offset: blockInfo.start_offset,
                end_offset: blockInfo.end_offset,
                snippet: blockInfo.snippet
            }];

        var summary = Dom.el("div", "blocked-matches");
        summary.innerHTML = found.map(function (match) {
            var lineText = match.line
                ? "<span>" + Dom.esc(t("line " + match.line)) + "</span>"
                : "";
            var snippetText = match.snippet
                ? "<code>" + Dom.esc(match.snippet) + "</code>"
                : "";
            return '<div class="blocked-match">' +
                '<span class="badge badge-danger">' +
                Dom.esc(match.main_cause || t("match")) + "</span>" +
                lineText +
                snippetText +
                "</div>";
        }).join("");
        card.appendChild(summary);

        // "Why?" expander with labelled mono trace rows (stage, cause, line, offsets).
        var expander = Dom.el("details", "blocked-expander");
        var expSummary = Dom.el("summary", "blocked-summary", t("Why was this stopped?"));
        var details = Dom.el("div", "blocked-details");
        found.forEach(function (match) {
            details.appendChild(Dom.el(
                "div",
                "blocked-detail-row",
                Stages.detailLine(blockInfo.stage, {
                    main_cause: match.main_cause || blockInfo.main_cause,
                    line: match.line || blockInfo.line,
                    start_offset: typeof match.start_offset === "number"
                        ? match.start_offset
                        : blockInfo.start_offset,
                    end_offset: typeof match.end_offset === "number"
                        ? match.end_offset
                        : blockInfo.end_offset
                })
            ));
        });
        expander.appendChild(expSummary);
        expander.appendChild(details);
        card.appendChild(expander);

        // Constructive next step: edit & rephrase, or request one-off admin approval.
        var panel = Dom.el("div", "override-panel");
        panel.innerHTML =
            '<p class="blocked-next">' +
            Dom.esc(t("Ask an administrator to approve this once, or rephrase without the flagged details.")) +
            "</p>" +
            '<div class="blocked-cta-row">' +
            '  <button type="button" class="btn btn-sm rephrase-btn">' +
            Dom.esc(t("Edit in message box")) + "</button>" +
            '  <button type="button" class="btn btn-sm btn-outline override-ask">' +
            Dom.esc(t("Approve once")) + "</button>" +
            "</div>" +
            '<p class="override-note">' +
            Dom.esc(t("One-off approvals need the administrator password and are recorded in the audit log.")) +
            "</p>";

        var ctaRow = panel.querySelector(".blocked-cta-row");
        var rephrase = panel.querySelector(".rephrase-btn");
        var ask = panel.querySelector(".override-ask");

        Dom.on(rephrase, "click", function () {
            fillComposer(promptText);
        });

        Dom.on(ask, "click", function () {
            var passId = "override-password-" + Date.now();
            var form = Dom.el("div", "override-form");
            form.innerHTML =
                '<label class="override-label" for="' + passId + '">' +
                Dom.esc(t("Administrator password")) + "</label>" +
                '<input type="password" id="' + passId + '" class="input" ' +
                'placeholder="' + Dom.esc(t("Administrator password")) + '" autocomplete="off">' +
                '<div class="override-actions">' +
                '<button type="button" class="btn btn-sm btn-primary override-send">' +
                Dom.esc(t("Approve & send")) + "</button>" +
                '<button type="button" class="btn btn-sm btn-ghost override-cancel">' +
                Dom.esc(t("Cancel")) + "</button>" +
                "</div>";
            panel.replaceChild(form, ctaRow);

            var input = form.querySelector("input");
            var approve = form.querySelector(".override-send");
            input.focus();

            Dom.on(form.querySelector(".override-cancel"), "click", function () {
                panel.replaceChild(ctaRow, form);
                ask.focus();
            });

            function submit() {
                var password = input.value;
                if (!password) {
                    Loading.toast("Enter the administrator password.", "warn");
                    input.focus();
                    return;
                }
                Loading.withButton(approve, function () {
                    return Api.post("/api/admin/login", {
                        username: (Api.Session.getAdmin() || {}).username,
                        password: password
                    }, { member: false, onUnauthorised: false });
                }).then(function (data) {
                    var token = data.session_token;
                    Api.Session.setAdmin(token, {
                        parentId: parseInt(data.Parent_id, 10),
                        username: data.username
                    });
                    wrap.remove();
                    send(promptText, true, token);
                }).catch(function (err) {
                    Loading.toast(
                        err.message || "That password did not match. Check it and try again.",
                        "error"
                    );
                    input.select();
                });
            }

            Dom.on(approve, "click", submit);
            Dom.on(input, "keydown", function (e) {
                if (e.key === "Escape") {
                    e.preventDefault();
                    panel.replaceChild(ctaRow, form);
                    ask.focus();
                    return;
                }
                if (e.key === "Enter") { e.preventDefault(); submit(); }
            });
        });

        card.appendChild(panel);
        wrap.appendChild(card);
        nodes.stream.appendChild(wrap);
        scrollToEnd(true);
    }

    /* ------------------------------------------------------------------
       Sending
       ------------------------------------------------------------------ */

    function requestBudget() {
        var body = document.body || {};
        var seconds = parseInt(body.getAttribute("data-request-timeout"), 10);
        if (!seconds || seconds < 30) seconds = 135;
        return seconds * 1000;
    }

    function send(text, bypass, adminToken) {
        if (state.busy) return;
        state.busy = true;
        nodes.send.disabled = true;

        var preSendKey = currentChatKey();
        var emptyNode = nodes.stream.querySelector(".first-run, .empty");
        if (emptyNode) emptyNode.remove();

        var waiting = showPending(text, bypass);

        var payload = {
            prompt: text,
            chat_id: state.chatId,
            bypass: !!bypass,
            check1: state.settings.check1,
            check2: state.settings.check2,
            check3: state.settings.check3
        };
        if (adminToken) payload.admin_token = adminToken;

        Api.post("/api/admin/employee/chat", payload, { timeout: requestBudget() })
            .then(function (data) {
                if (data.blocked) {
                    waiting.resolve((data.block_info || {}).stage || "check1");
                    hidePending();
                    state.blockedChats[preSendKey] = true;
                    renderBlocked(data.block_info || {}, text);
                    return null;
                }

                waiting.resolve(null);

                var nextChatId = data.chat_id || state.chatId;
                var nextKey = nextChatId ? String(nextChatId) : preSendKey;
                // Carry a draft chat's prior block forward once the chat gets its id.
                if (preSendKey === DRAFT_CHAT_KEY && state.blockedChats[DRAFT_CHAT_KEY]) {
                    state.blockedChats[nextKey] = true;
                    delete state.blockedChats[DRAFT_CHAT_KEY];
                }
                state.chatId = nextChatId;

                if (data.message_id) {
                    if (bypass) {
                        state.overriddenMessages[data.message_id] = true;
                    } else if (state.blockedChats[nextKey] && !state.gracedChats[nextKey]) {
                        // D4: fires once per chat, only after a prior block in it.
                        state.gracedChats[nextKey] = true;
                        state.gracedMessages[data.message_id] = true;
                    }
                    state.messages.push({
                        id: data.message_id,
                        prompt: text,
                        answer: data.reply_message,
                        created_at: new Date().toISOString(),
                        edited: false
                    });
                    return loadChats().then(function () {
                        hidePending();
                        var current = state.chats.filter(function (c) {
                            return c.id === state.chatId;
                        })[0];
                        if (current && current.title) nodes.title.textContent = current.title;
                        renderMessages();
                    });
                }

                return openChat(state.chatId).then(function () {
                    hidePending();
                    return loadChats();
                });
            })
            .catch(function (err) {
                waiting.stop();
                pending = null;
                if (!nodes.stream.children.length) renderMessages();
                Loading.toast(err.message, "error");
            })
            .finally(function () {
                state.busy = false;
                nodes.send.disabled = false;
                nodes.input.focus();
            });
    }

    function onSend(event) {
        event.preventDefault();
        if (state.busy) return;
        var text = nodes.input.value.trim();
        if (!text) {
            Loading.toast("That message was empty — type a line first.", "info");
            nodes.input.focus();
            return;
        }
        nodes.input.value = "";
        autoGrow();
        clearSearch();
        send(text, false, null);
    }

    /* ------------------------------------------------------------------
       Chat management
       ------------------------------------------------------------------ */

    function openChat(chatId) {
        return Api.post("/api/admin/employee/chats/open", { chat_id: chatId })
            .then(function (data) {
                state.chatId = chatId;
                state.messages = (data.chat && data.chat.messages) || [];
                var chat = data.chat || {};
                nodes.title.textContent = chat.title || t("New chat");
                state.chats.forEach(function (c) {
                    if (c.id === chatId) c.title = chat.title || c.title;
                });
                renderChatList();
                renderMessages();
            })
            .catch(function (err) { Loading.toast(err.message, "error"); });
    }

    function newChat() {
        state.chatId = null;
        state.messages = [];
        delete state.blockedChats[DRAFT_CHAT_KEY];
        nodes.title.textContent = t("New chat");
        renderChatList();
        renderMessages();
        nodes.input.focus();
    }

    function deleteChat(button) {
        if (!state.chatId) {
            Loading.toast("Nothing to delete yet — this chat has no saved messages.", "info");
            return;
        }
        Shell.confirm({
            eyebrow: "Remove conversation",
            title: "Delete this chat?",
            lost: "Removed: every message in this conversation is deleted.",
            kept: "Kept: workspace block and activity logs stay intact.",
            confirmLabel: "Delete chat",
            cancelLabel: "Keep chat",
            danger: true
        }).then(function (accepted) {
            if (!accepted) return null;
            return Loading.withButton(button, function () {
                return Api.post("/api/admin/employee/chats/delete", { chat_id: state.chatId });
            }).then(function () {
                Loading.toast("Chat deleted.", "success");
                return loadChats();
            }).then(function () {
                newChat();
            }).catch(function (err) { Loading.toast(err.message, "error"); });
        });
    }

    function renameChat() {
        var current = nodes.title.textContent.trim();
        var isDefault = current === "New chat" || current === t("New chat");
        Shell.prompt({
            eyebrow: "Conversation",
            title: "Rename this chat",
            label: "Chat title",
            value: isDefault ? "" : current,
            placeholder: "Short title for this conversation",
            maxLength: 80,
            confirmLabel: "Save title",
            cancelLabel: "Cancel"
        }).then(function (raw) {
            if (raw === null) return null;
            var next = raw.trim().slice(0, 80);
            if (!next || next === current) return null;
            if (!state.chatId) { nodes.title.textContent = next; return null; }
            return Api.post("/api/admin/employee/chats/rename", {
                chat_id: state.chatId,
                title: next
            }).then(function () {
                nodes.title.textContent = next;
                return loadChats();
            }).then(function () {
                Loading.toast("Chat renamed.", "success");
            }).catch(function (err) { Loading.toast(err.message, "error"); });
        });
    }

    /* ------------------------------------------------------------------
       Search within the current chat
       ------------------------------------------------------------------ */

    function applySearch() {
        state.query = nodes.search.value.trim();
        renderMessages();
    }

    function clearSearch() {
        if (!nodes.search.value && !state.query) return;
        nodes.search.value = "";
        state.query = "";
        renderMessages();
    }

    /* ------------------------------------------------------------------
       Wiring
       ------------------------------------------------------------------ */

    Dom.on(nodes.form, "submit", onSend);
    Dom.on(nodes.input, "input", autoGrow);
    Dom.on(nodes.input, "keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(e); }
    });

    Dom.on(nodes.newChat, "click", newChat);
    Dom.on(nodes.deleteChat, "click", function () { deleteChat(nodes.deleteChat); });
    Dom.on(nodes.rename, "click", renameChat);

    Dom.on(nodes.search, "input", Dom.debounce(applySearch, 180));
    Dom.on(nodes.search, "keydown", function (e) {
        if (e.key === "Escape") clearSearch();
    });
    Dom.on(nodes.searchClear, "click", function () {
        clearSearch();
        nodes.search.focus();
    });

    Dom.on(document, "cybersyn:lang", function () {
        updateChecksBadge();
        renderChatList();
        if (pending && pending.relocalise) pending.relocalise();
        if (!state.busy) renderMessages();
    });

    /* ------------------------------------------------------------------
       Start
       ------------------------------------------------------------------ */

    (function start() {
        Api.post("/api/admin/employee/settings", {}).then(function (data) {
            state.settings.check1 = data.check1 !== false;
            state.settings.check2 = data.check2 !== false;
            state.settings.check3 = data.check3 !== false;
            updateChecksBadge();
        }).catch(function () { updateChecksBadge(); });

        loadChats()
            .then(function () {
                if (state.chats.length) return openChat(state.chats[0].id);
                renderMessages();
                return null;
            })
            .catch(function (err) { Loading.toast(err.message, "error"); });

        autoGrow();
        nodes.input.focus();
    })();
})();
