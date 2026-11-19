/* ==========================================================================
   workspace.js — the chat screen.

   Owns: the conversation list, the four demo tiles on an empty conversation,
   live three-stage screening tracker, teaching-moment blocked cards, one-off
   administrator override, post-block grace note, per-message actions and
   in-chat search.
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

    var DRAFT_CHAT_KEY = "__draft__";

    var state = {
        chats: [],
        chatsLoaded: false,
        chatId: null,
        viewVersion: 0,
        composerVersion: 0,
        draftTitle: null,
        messages: [],
        settings: { check1: true, check2: true, check3: true },
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
        chatError: $("#chat-error"),
        trust: $(".composer-trust"),
        form: $("#form-send"),
        send: $("#btn-send"),
        newChat: $("#btn-new-chat"),
        deleteChat: $("#btn-delete-chat"),
        rename: $("#btn-rename-chat"),
        search: $("#chat-search"),
        searchBox: $(".search-box"),
        searchClear: $("#search-clear"),
        searchCount: $("#search-count"),
        otherResults: $("#other-chat-results"),
        checksSummary: $("#checks-summary"),
        checksStatus: $("#checks-status"),
        missingKeyNote: $("#missing-key-note"),
        dismissKeyNote: $("#btn-dismiss-key-note"),
        firstRunTpl: $("#first-run-template"),
        menuButton: $("#btn-chat-menu"),
        menu: $("#chat-menu"),
        menuWrap: $(".topbar-menu-wrap"),
        menuRename: $("#menu-rename-chat"),
        menuDelete: $("#menu-delete-chat")
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

    /* The assistant's face is the app's own outline shield, never a vendor
       mark: a quiet circle of --surface-2 with the cream glyph inside. */
    function aiAvatar() {
        var node = Dom.el("span", "turn-avatar turn-avatar-ai");
        node.setAttribute("aria-hidden", "true");
        node.innerHTML = Icons.svg("shield", "icon");
        return node;
    }

    function memberName() {
        var member = (Api.Session && Api.Session.getMember) ? Api.Session.getMember() : null;
        return (member && member.username) || "";
    }

    function memberAvatar() {
        var node = Dom.fromHTML(Dom.avatarHTML(memberName(), "turn-avatar turn-avatar-user"));
        node.setAttribute("aria-hidden", "true");
        return node;
    }

    /** A turn head: the speaker in --text-dim, then the time alone.
     *  The day itself is carried by the date divider between days. */
    function turnHead(speaker, iso, extra) {
        var head = Dom.el("div", "msg-head");
        head.appendChild(Dom.el("span", "who", speaker));
        if (iso) {
            head.appendChild(Dom.el("span", "msg-time", Dom.clockTime(iso)));
        }
        if (extra) head.appendChild(Dom.el("span", "msg-time", extra));
        return head;
    }

    function dateDivider(iso) {
        var row = Dom.el("div", "stream-date");
        row.appendChild(Dom.el("span", "", Dom.dayStamp(iso)));
        return row;
    }

    /* The paper plane trades places with a spinner while a request is open. */
    function setSendBusy(busy) {
        if (!nodes.send) return;
        nodes.send.disabled = !!busy;
        nodes.send.classList.toggle("is-loading", !!busy);
        if (busy && !nodes.send.querySelector(".btn-spinner")) {
            var spinner = Dom.el("span", "btn-spinner");
            spinner.setAttribute("aria-hidden", "true");
            nodes.send.appendChild(spinner);
        }
    }

    function autoGrow() {
        nodes.input.style.height = "auto";
        nodes.input.style.height = Math.min(nodes.input.scrollHeight, 180) + "px";
    }

    function fillComposer(text) {
        state.composerVersion++;
        nodes.input.value = text;
        autoGrow();
        nodes.input.focus();
        nodes.input.setSelectionRange(text.length, text.length);
        if (typeof nodes.input.scrollIntoView === "function") {
            nodes.input.scrollIntoView({
                block: "nearest",
                behavior: "auto"
            });
        }
    }

    function showChatError(err) {
        var code = err.body && err.body.error_code;
        if (!nodes.chatError || (code !== "screening_failed" && code !== "missing_api_key")) {
            Loading.toast(err.message, "error");
            return;
        }
        // Keep a refusal visible until retry/navigation, even if it lists
        // several checks. Use text, never scanner output as HTML.
        nodes.chatError.hidden = false;
        nodes.chatError.textContent = code === "screening_failed"
            ? err.message.replace(/\b(check[123]): /g, function (_, stage) { return Stages.title(stage) + ": "; })
            : err.message;
        if (window.I18n) window.I18n.apply();
    }

    function clearChatError() {
        if (!nodes.chatError) return;
        nodes.chatError.hidden = true;
        nodes.chatError.textContent = "";
    }

    function scrollToEnd() {
        requestAnimationFrame(function () {
            var viewport = nodes.viewport;
            viewport.scrollTo({ top: viewport.scrollHeight, behavior: "auto" });
        });
    }

    /* ------------------------------------------------------------------
       In-flight waiting card — anonymous copy with no stage names,
       resolving straight from the server verdict with no fake timers.
       ------------------------------------------------------------------ */

    var LONG_WAIT_MS = 8000;
    var pending = null;

    function showPending(promptText, bypass) {
        hidePending();

        var enabled = Dom.activeChecks(state.settings);
        var checking = !bypass && enabled > 0;

        var wrap = Dom.el("div", "msg");

        var userTurn = Dom.el("div", "turn turn-user");
        userTurn.appendChild(memberAvatar());
        userTurn.appendChild(turnHead(t("You")));
        var userBody = Dom.el("div", "turn-body");
        userBody.appendChild(Dom.el("div", "bubble bubble-user", promptText));
        userTurn.appendChild(userBody);
        wrap.appendChild(userTurn);

        var note = Dom.el("div", "msg-pending");

        var line = Dom.el("div", "pending-line");
        var dots = null;
        if (checking) {
            dots = Dom.el("span", "pending-dots");
            dots.setAttribute("aria-hidden", "true");
            for (var d = 0; d < 3; d++) {
                dots.appendChild(Dom.el("span", "pending-dot"));
            }
            line.appendChild(dots);
        }

        var label = Dom.el("span", "pending-text");
        label.setAttribute("role", "status");
        label.setAttribute("aria-live", "polite");

        var labelKey = bypass
            ? "Sending once with administrator approval."
            : (!enabled
                ? "Waiting for the AI reply."
                : "Checking…");
        var slowKey = "Still working — normal on a long paste.";
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

        var aiTurn = Dom.el("div", "turn turn-ai");
        aiTurn.appendChild(aiAvatar());
        aiTurn.appendChild(turnHead("CyberSyn"));
        var aiBody = Dom.el("div", "turn-body");
        aiBody.appendChild(note);
        aiTurn.appendChild(aiBody);
        wrap.appendChild(aiTurn);
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
                if (dots) dots.remove();
                if (!checking) return;
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
       Flat local-checks status indicator
       ------------------------------------------------------------------ */

    function checksSummaryText(on) {
        if (on === 4) return t("All checks on");
        if (on === 0) return t("All checks off");
        return t("Checks: " + on + " of 4 on");
    }

    function updateChecksBadge() {
        var on = Dom.activeChecks(state.settings);
        var summary = checksSummaryText(on);
        nodes.checksSummary.textContent = summary;
        nodes.checksStatus.removeAttribute("title");
        nodes.checksStatus.setAttribute("aria-label", summary);
        nodes.checksStatus.classList.toggle("is-all-on", on === 4);
        nodes.checksStatus.classList.toggle("is-partial", on > 0 && on < 4);
        nodes.checksStatus.classList.toggle("is-off", on === 0);
        if (nodes.trust) {
            nodes.trust.textContent = t(on === 0
                ? "Local safety checks are off. Prompts are not screened."
                : "Enabled checks run on this computer before the prompt goes to the AI.");
        }
    }

    /* ------------------------------------------------------------------
       Demo tiles

       Four tiles appear whenever the conversation is empty: one clean prompt
       and one that trips each of the three local checks. A tile for a check
       that is set to Allow is faded and completely inert, and the state is
       refreshed whenever SETTINGS resolves or the language changes.
       ------------------------------------------------------------------ */

    function checkEnabled(rule) {
        var flag = state.settings ? state.settings[rule] : undefined;
        if (typeof flag === "boolean") return flag;
        if (typeof flag === "number") return flag !== 0;
        return Dom.policyAction(state.settings || {}, rule) !== "allow";
    }

    function applyStarterStates() {
        if (!nodes.stream) return;
        Dom.$$(".demo-tile[data-starter]", nodes.stream).forEach(function (tile) {
            var rule = tile.getAttribute("data-check");
            if (!rule) {
                tile.disabled = false;
                tile.classList.remove("is-disabled");
                tile.removeAttribute("aria-disabled");
                tile.removeAttribute("title");
                return;
            }
            var enabled = checkEnabled(rule);
            tile.disabled = !enabled;
            tile.classList.toggle("is-disabled", !enabled);
            if (enabled) {
                tile.removeAttribute("aria-disabled");
                tile.removeAttribute("title");
            } else {
                tile.setAttribute("aria-disabled", "true");
                tile.setAttribute("title", t("This check is turned off in Settings."));
            }
        });
    }

    /* ------------------------------------------------------------------
       Missing provider key callout (v3 Item 2)

       Inferred strictly from the existing /api/admin/employee/settings
       API_KEY_MASK field (empty when no key is stored). Non-blocking and
       dismissible for the current browser session.
       ------------------------------------------------------------------ */

    function missingKeyStorageKey() {
        var m = Api.Session.getMember() || {};
        return "cybersyn_missing_key_dismissed_" +
            (m.parentId || "0") + "_" + (m.employeeId || "0");
    }

    function isMissingKeyDismissed() {
        try {
            return sessionStorage.getItem(missingKeyStorageKey()) === "1";
        } catch (err) {
            return false;
        }
    }

    function updateMissingKeyNote(data) {
        if (!nodes.missingKeyNote || !data || typeof data.API_KEY_MASK !== "string") {
            return;
        }
        var hasKey = data.API_KEY_MASK.length > 0;
        if (hasKey) {
            try { sessionStorage.removeItem(missingKeyStorageKey()); } catch (err) {}
            nodes.missingKeyNote.classList.add("hidden");
            return;
        }
        nodes.missingKeyNote.classList.toggle("hidden", isMissingKeyDismissed());
    }

    Dom.on(nodes.dismissKeyNote, "click", function () {
        try { sessionStorage.setItem(missingKeyStorageKey(), "1"); } catch (err) {}
        if (nodes.missingKeyNote) nodes.missingKeyNote.classList.add("hidden");
        nodes.input.focus();
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
                '<span class="chat-item-title" data-no-i18n>' + Dom.esc(chat.title) + "</span>" +
                '<span class="chat-item-meta">' + Dom.esc(Dom.timeAgo(chat.updated_at)) + "</span>";
            Dom.on(item, "click", function () { openChat(chat.id); });
            nodes.list.appendChild(item);
        });
    }

    function loadChats() {
        return Api.post("CHATS", {}).then(function (data) {
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

        var hasPrompt = !!(message.prompt && String(message.prompt).trim() !== "");

        /* ---- Your turn: right-aligned head, bubble, notes, then the pencil */
        var userTurn = Dom.el("div", "turn turn-user");
        userTurn.appendChild(memberAvatar());
        userTurn.appendChild(turnHead(
            t("You"),
            message.created_at,
            message.edited ? t("edited") : ""
        ));

        var mine = Dom.el("div", "bubble bubble-user");
        var mineText = Dom.el("p");
        mineText.textContent = message.prompt || "";
        mine.appendChild(mineText);
        Dom.highlightText(mineText, state.query);

        var userBody = Dom.el("div", "turn-body");
        userBody.appendChild(mine);

        if (message.redacted && message.redaction_info) {
            var info = message.redaction_info;
            var disclosure = Dom.el("details", "redaction-receipt");
            var summary = Dom.el("summary");
            summary.appendChild(Dom.el("span", "badge badge-accent", "Redacted " + Dom.plural(info.count, "item")));
            var placeholderList = Dom.el("span", "mono redaction-tokens", (info.placeholders || []).join(", "));
            placeholderList.setAttribute("data-no-i18n", "");
            summary.appendChild(placeholderList);
            disclosure.appendChild(summary);
            disclosure.appendChild(Dom.el("p", "tiny muted", "Sanitized prompt"));
            var preview = Dom.el("pre", "redaction-preview", message.prompt || "");
            preview.setAttribute("data-no-i18n", "");
            disclosure.appendChild(preview);
            if (info.restored) disclosure.appendChild(Dom.el("p", "tiny muted", "Values restored in this reply only."));
            userBody.appendChild(disclosure);
        }

        if (message.id && state.overriddenMessages[message.id]) {
            userBody.appendChild(Dom.el(
                "p",
                "msg-receipt msg-receipt-override",
                t("Sent once with administrator approval — this was logged.")
            ));
        } else if (message.id && state.gracedMessages[message.id]) {
            userBody.appendChild(Dom.el(
                "p",
                "msg-receipt msg-receipt-grace",
                t("Rewritten — sent.")
            ));
        }

        userTurn.appendChild(userBody);

        if (hasPrompt) {
            var userActions = Dom.el("div", "msg-actions msg-actions-user");
            var editBtn = iconButton("edit", "Edit this message", function () {
                beginEdit(wrap, message, editBtn);
            });
            userActions.appendChild(editBtn);
            userTurn.appendChild(userActions);
        }
        wrap.appendChild(userTurn);

        /* ---- The assistant's turn: shield avatar, left-aligned head, reply */
        var hasAnswer = message.answer && String(message.answer).trim() !== "" &&
            String(message.answer) !== "NULL";
        var reply = null;
        var copyTintTimer = null;

        var aiTurn = Dom.el("div", "turn turn-ai");
        aiTurn.appendChild(aiAvatar());
        aiTurn.appendChild(turnHead("CyberSyn", message.created_at));

        var aiBody = Dom.el("div", "turn-body");
        if (hasAnswer) {
            reply = Dom.el("div", "bubble bubble-ai");
            reply.innerHTML = window.Markdown.render(message.answer);
            Dom.highlightText(reply, state.query);
            aiBody.appendChild(reply);
        }

        var actionsAi = Dom.el("div", "msg-actions msg-actions-ai");
        actionsAi.appendChild(iconButton("copy", "Copy the answer", function () {
            Dom.copyText(message.answer || "")
                .then(function () {
                    if (reply) {
                        if (copyTintTimer) clearTimeout(copyTintTimer);
                        reply.classList.add("is-copied");
                        copyTintTimer = setTimeout(function () {
                            reply.classList.remove("is-copied");
                            copyTintTimer = null;
                        }, 700);
                    }
                    Loading.toast("Answer copied.", "success");
                })
                .catch(function () {
                    Loading.toast("Clipboard access was blocked — select the text to copy it.", "error");
                });
        }));
        if (hasAnswer) {
            var regenBtn = iconButton("regenerate", "Generate a different answer", function () {
                regenerate(message, regenBtn);
            });
            actionsAi.appendChild(regenBtn);
        }
        actionsAi.appendChild(iconButton("delete", "Delete this message", function () {
            removeMessage(message, actionsAi);
        }, true));

        aiTurn.appendChild(aiBody);
        aiTurn.appendChild(actionsAi);
        wrap.appendChild(aiTurn);

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
        Dom.$$("[data-starter]", fragment).forEach(function (tile) {
            Dom.on(tile, "click", function () {
                if (tile.disabled) return;
                var prompt = tile.querySelector(".demo-tile-prompt");
                fillComposer((prompt ? prompt.textContent : tile.textContent).trim());
            });
        });
        nodes.stream.appendChild(fragment);
        if (nodes.viewport) nodes.viewport.classList.add("is-first-run");
        applyStarterStates();
        if (window.I18n && typeof window.I18n.apply === "function") {
            window.I18n.apply();
        }
        return true;
    }

    /* Leaving the first-run view: drop the tiles (or the empty notice) and
       give the stream its normal top-aligned rhythm back. */
    function clearEmptyState() {
        var emptyNode = nodes.stream.querySelector(".demo, .empty");
        if (emptyNode) emptyNode.remove();
        if (nodes.viewport) nodes.viewport.classList.remove("is-first-run");
    }

    function emptyStream(title, body, icon) {
        if (nodes.viewport) nodes.viewport.classList.remove("is-first-run");
        nodes.stream.innerHTML =
            '<div class="empty">' + Icons.html(icon, "icon") +
            "<h2>" + Dom.esc(title) + "</h2><p>" + Dom.esc(body) + "</p></div>";
    }

    function renderMessages() {
        var query = state.query;
        var visible = query ? state.messages.filter(matchesQuery) : state.messages;
        nodes.stream.innerHTML = "";
        if (nodes.viewport) nodes.viewport.classList.remove("is-first-run");

        if (!visible.length) {
            if (query) {
                var missBody = (window.I18n && window.I18n.current() === "el")
                    ? "Κανένα μήνυμα σε αυτή τη συνομιλία δεν περιέχει «" + query +
                      "». Δοκιμάστε άλλη λέξη ή πατήστε Esc."
                    : 'No message in this chat mentions "' + query +
                      '". Try another word or press Esc to show all messages.';
                emptyStream(t("No messages match"), missBody, "search");
            } else if (!renderFirstRun()) {
                emptyStream(t("Start the conversation"), t("Write a message below."), "chat");
            }
        } else {
            var lastDay = "";
            visible.forEach(function (message) {
                var day = Dom.dayKey(message.created_at);
                if (day && day !== lastDay) {
                    nodes.stream.appendChild(dateDivider(message.created_at));
                    lastDay = day;
                }
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

    function beginEdit(wrap, message, trigger) {
        var chatId = state.chatId;
        var viewVersion = state.viewVersion;
        if (wrap.classList.contains("is-editing")) return;
        var bubble = wrap.querySelector(".bubble-user");
        if (!bubble) return;

        wrap.classList.add("is-editing");
        bubble.classList.add("is-editing");
        bubble.innerHTML =
            '<textarea class="bubble-textarea" rows="1" aria-label="' +
            Dom.esc(t("Edit this message")) + '"></textarea>' +
            '<div class="bubble-edit-actions">' +
            '  <kbd class="kbd bubble-edit-hint" aria-hidden="true">⌘↵</kbd>' +
            '  <button type="button" class="btn btn-sm btn-ghost bubble-edit-cancel">' +
            Dom.esc(t("Cancel")) + "</button>" +
            '  <button type="button" class="btn btn-sm btn-primary bubble-edit-save">' +
            Dom.esc(t("Save")) + "</button>" +
            "</div>";

        var textarea = bubble.querySelector(".bubble-textarea");
        textarea.value = message.prompt || "";

        var cancel = bubble.querySelector(".bubble-edit-cancel");
        var save = bubble.querySelector(".bubble-edit-save");

        function sizeEditor() {
            textarea.style.height = "auto";
            if (textarea.scrollHeight > 0) {
                var cap = Math.max(120, Math.round((window.innerHeight || 800) * 0.5));
                textarea.style.height = Math.min(textarea.scrollHeight, cap) + "px";
            }
        }

        function onBubbleKeydown(event) {
            if (event.isComposing || event.keyCode === 229) return;
            if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                closeEditor();
            } else if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                event.preventDefault();
                event.stopPropagation();
                submitEdit();
            }
        }

        function closeEditor() {
            bubble.removeEventListener("keydown", onBubbleKeydown);
            wrap.classList.remove("is-editing");
            bubble.classList.remove("is-editing");
            bubble.innerHTML = "";
            var p = Dom.el("p");
            p.textContent = message.prompt || "";
            bubble.appendChild(p);
            Dom.highlightText(p, state.query);
            if (trigger && trigger.isConnected) trigger.focus();
        }

        function submitEdit() {
            if (save.disabled) return;
            var next = textarea.value.trim();
            if (!next) {
                Loading.toast("Type a message first.", "warn");
                textarea.focus();
                return;
            }
            if (next === message.prompt) {
                closeEditor();
                return;
            }
            Loading.withButton(save, function () {
                return Api.post("MESSAGE_EDIT", {
                    chat_id: chatId,
                    message_id: message.id,
                    text: next
                });
            }).then(function (data) {
                bubble.removeEventListener("keydown", onBubbleKeydown);
                if (viewVersion !== state.viewVersion) return loadChats();
                state.messages = data.messages || [];
                renderMessages();
                if (message.id !== undefined && message.id !== null) {
                    var targetId = String(message.id);
                    var rows = nodes.stream.querySelectorAll(".msg");
                    for (var i = 0; i < rows.length; i++) {
                        if (rows[i].dataset.id === targetId) {
                            var nextTrigger = rows[i].querySelector(".msg-actions-user .icon-btn");
                            if (nextTrigger) nextTrigger.focus();
                            break;
                        }
                    }
                }
                loadChats();
                Loading.toast("Message updated.", "success");
            }).catch(function (err) {
                Loading.toast(err.message, "error");
            });
        }

        Dom.on(textarea, "input", sizeEditor);
        Dom.on(cancel, "click", closeEditor);
        Dom.on(save, "click", submitEdit);
        bubble.addEventListener("keydown", onBubbleKeydown);

        sizeEditor();
        textarea.focus();
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    }

    function removeMessage(message, button) {
        var chatId = state.chatId;
        var viewVersion = state.viewVersion;
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
                return Api.post("MESSAGE_DELETE", {
                    chat_id: chatId,
                    message_id: message.id
                });
            }).then(function (data) {
                if (viewVersion === state.viewVersion) {
                    state.messages = data.messages || [];
                    renderMessages();
                }
                loadChats();
                Loading.toast("Message deleted.", "success");
            }).catch(function (err) {
                Loading.toast(err.message, "error");
            });
        });
    }

    function regenerate(message, button, options) {
        if (state.busy) return;
        var opts = options || {};
        var chatId = state.chatId;
        var viewVersion = state.viewVersion;
        state.busy = true;
        setSendBusy(true);
        clearChatError();
        var payload = { chat_id: chatId, message_id: message.id };
        if (opts.confirmWarn) payload.confirm_warn = true;
        if (opts.bypass) {
            payload.bypass = true;
            payload.admin_token = opts.token;
        }
        return Loading.withButton(button, function () {
            return Api.post("CHAT_REGENERATE", payload, { timeout: requestBudget(), onUnauthorised: !opts.bypass });
        }).then(function (data) {
            if (viewVersion !== state.viewVersion) return;
            if (data.blocked) {
                renderBlocked(data.block_info || {}, message.prompt || "", function (token) {
                    return regenerate(message, null, { bypass: true, token: token });
                });
                return;
            }
            if (data.warned) {
                renderWarning(data.warn_info || {}, message.prompt || "", function (confirm) {
                    return regenerate(message, confirm, { confirmWarn: true });
                });
                return;
            }
            if (!Array.isArray(data.messages)) return;
            state.messages = data.messages;
            if (data.redacted) {
                var updated = state.messages.find(function (item) { return item.id === message.id; });
                if (updated) {
                    updated.answer = data.reply_message; // ephemeral; the history array from the server was unrestored
                    updated.redaction_info = data.redaction_info;
                }
                loadChats().then(function () {
                    var chat = state.chats.find(function (item) { return item.id === chatId; });
                    if (chat && viewVersion === state.viewVersion) setTitle(chat.title);
                });
            }
            if (opts.bypass) state.overriddenMessages[message.id] = true;
            renderMessages();
            Loading.toast("Answer regenerated.", "success");
        }).catch(function (err) {
            if (viewVersion === state.viewVersion) showChatError(err);
        }).finally(function () {
            state.busy = false;
            setSendBusy(false);
        });
    }

    function findings(info) {
        return Array.isArray(info.matches) && info.matches.length ? info.matches : [info];
    }

    function matchList(found, warning) {
        var list = Dom.el("div", "blocked-matches");
        found.forEach(function (match) {
            var cause = match.cause || match.main_cause;
            var row = Dom.el("div", "blocked-match");
            var badge = Dom.el("span", "badge " + (warning ? "badge-warn" : "badge-danger"), cause || "match");
            if (cause) badge.setAttribute("data-no-i18n", "");
            row.appendChild(badge);
            if (warning && match.stage) row.appendChild(Dom.el("span", "", Stages.title(match.stage)));
            if (match.line) row.appendChild(Dom.el("span", "", "line " + match.line));
            if (match.snippet) {
                var code = Dom.el("code");
                code.setAttribute("data-no-i18n", "");
                code.appendChild(Dom.el("mark", "policy-match", match.snippet));
                row.appendChild(code);
            }
            list.appendChild(row);
        });
        return list;
    }

    function renderWarning(info, text, sendAnyway) {
        var wrap = Dom.el("div", "msg policy-warning");
        var card = Dom.el("div", "bubble bubble-warned");
        card.setAttribute("role", "group");
        card.setAttribute("aria-label", "Message paused for review");
        var header = Dom.el("div", "blocked-head");
        header.innerHTML = Icons.svg("warning", "icon") + '<h3 class="blocked-verdict">Message paused for review</h3>';
        card.appendChild(header);
        card.appendChild(Dom.el("p", "blocked-what", "No message was sent. Check what matched before you decide to proceed."));
        card.appendChild(Dom.el("p", "blocked-why", Stages.title(info.stage)));
        card.appendChild(matchList(findings(info), true));
        if (info.will_redact) card.appendChild(Dom.el("p", "blocked-next", "Other flagged details will be redacted before sending."));
        var actions = Dom.el("div", "blocked-cta-row");
        var edit = Dom.el("button", "btn btn-sm btn-ghost warn-edit", "Edit message");
        var confirm = Dom.el("button", "btn btn-sm btn-outline warn-send", "Send anyway");
        edit.type = confirm.type = "button";
        Dom.on(edit, "click", function () {
            wrap.remove();
            if (!nodes.stream.children.length) renderMessages();
            fillComposer(text);
        });
        Dom.on(confirm, "click", function () {
            if (state.busy) return;
            wrap.remove();
            sendAnyway(confirm);
        });
        actions.append(edit, confirm);
        card.appendChild(actions);

        var aiTurn = Dom.el("div", "turn turn-ai");
        aiTurn.appendChild(aiAvatar());
        aiTurn.appendChild(turnHead("CyberSyn"));
        var aiBody = Dom.el("div", "turn-body turn-body-wide");
        aiBody.appendChild(card);
        aiTurn.appendChild(aiBody);
        wrap.appendChild(aiTurn);
        nodes.stream.appendChild(wrap);
        if (window.I18n) window.I18n.apply();
        edit.focus();
        scrollToEnd(true);
    }

    /* ------------------------------------------------------------------
       Blocked message card + "Why?" trace expander + one-off override (D3)
       ------------------------------------------------------------------ */

    function renderBlocked(blockInfo, promptText, approveOverride) {
        // Clear any empty-state notice if this was the chat's first attempt.
        clearEmptyState();

        var wrap = Dom.el("div", "msg");

        var userTurn = Dom.el("div", "turn turn-user");
        userTurn.appendChild(memberAvatar());
        userTurn.appendChild(turnHead(t("You")));
        var userBody = Dom.el("div", "turn-body");
        userBody.appendChild(Dom.el("div", "bubble bubble-user", promptText));
        userTurn.appendChild(userBody);
        wrap.appendChild(userTurn);

        var card = Dom.el("div", "bubble bubble-blocked");

        var header = Dom.el("div", "blocked-head");
        header.innerHTML = Icons.svg("warning", "icon") +
            '<h3 class="blocked-verdict">' +
            Dom.esc(blockInfo.stage === "policy" ? "Destination blocked by workspace policy" : Stages.verdict(blockInfo.stage)) + "</h3>";
        card.appendChild(header);

        card.appendChild(Dom.el(
            "p",
            "blocked-what",
            t("Nothing left this computer. Your message stayed here and was not sent to the AI.")
        ));
        if (blockInfo.stage === "policy") {
            var reason = Dom.el("p", "blocked-why", "This AI tool is unapproved.");
            var name = Dom.el("strong", "", blockInfo.tool_name || "");
            name.setAttribute("data-no-i18n", "");
            reason.append(" ", name);
            card.appendChild(reason);
        } else {
            card.appendChild(Dom.el("p", "blocked-why", Stages.reason(blockInfo)));
        }

        var found = findings(blockInfo);
        card.appendChild(matchList(found, false));

        // "Why?" expander with labelled mono trace rows (cause, line, offsets).
        var expander = Dom.el("details", "blocked-expander");
        var expSummary = Dom.el("summary", "blocked-summary", t("Why was this stopped?"));
        var details = Dom.el("div", "blocked-details");
        found.forEach(function (match) {
            details.appendChild(Dom.el(
                "div",
                "blocked-detail-row",
                Stages.detailLine(blockInfo.stage, {
                    main_cause: match.cause || match.main_cause || blockInfo.main_cause,
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

        // Constructive next step: restore the message to edit, or approve once.
        var hasPrompt = typeof promptText === "string" && promptText.length > 0;
        var panel = Dom.el("div", "override-panel");
        panel.innerHTML =
            '<p class="blocked-next">' +
            Dom.esc(t("Ask an administrator to approve this once, or rephrase without the flagged details.")) +
            "</p>" +
            '<div class="blocked-cta-row">' +
            (hasPrompt
                ? '  <button type="button" class="btn btn-sm btn-ghost rephrase-btn">' +
                  Dom.esc(t("Put my text back in the message box")) + "</button>"
                : "") +
            '  <button type="button" class="btn btn-sm btn-outline override-ask">' +
            Dom.esc(t("Approve once")) + "</button>" +
            "</div>" +
            '<p class="override-note">' +
            Dom.esc(t("One-off approvals need the administrator password and are recorded in the audit log.")) +
            "</p>";

        var ctaRow = panel.querySelector(".blocked-cta-row");
        var rephrase = panel.querySelector(".rephrase-btn");
        var ask = panel.querySelector(".override-ask");

        if (rephrase) {
            Dom.on(rephrase, "click", function () {
                fillComposer(promptText);
            });
        }

        Dom.on(ask, "click", function () {
            var blockedChat = currentChatKey();
            var form = Dom.el("div", "override-form");
            form.innerHTML =
                '<label class="override-label"><span>' +
                Dom.esc(t("Administrator username")) + "</span>" +
                '<input type="text" class="input override-name" autocomplete="username"></label>' +
                '<label class="override-label"><span>' +
                Dom.esc(t("Administrator password")) + "</span>" +
                '<input type="password" class="input override-pass" ' +
                'placeholder="' + Dom.esc(t("Administrator password")) + '" autocomplete="off"></label>' +
                '<div class="override-actions">' +
                '<button type="button" class="btn btn-sm btn-primary override-send">' +
                Dom.esc(t("Approve & send")) + "</button>" +
                '<button type="button" class="btn btn-sm btn-ghost override-cancel">' +
                Dom.esc(t("Cancel")) + "</button>" +
                "</div>";
            panel.replaceChild(form, ctaRow);

            var username = form.querySelector(".override-name");
            username.value = (Api.Session.getAdmin() || {}).username || "";
            var input = form.querySelector(".override-pass");
            var approve = form.querySelector(".override-send");
            (username.value ? input : username).focus();

            Dom.on(form.querySelector(".override-cancel"), "click", function () {
                panel.replaceChild(ctaRow, form);
                ask.focus();
            });

            function submit() {
                var password = input.value;
                if (!username.value.trim()) {
                    Loading.toast("Enter the administrator username.", "warn");
                    username.focus();
                    return;
                }
                if (!password) {
                    Loading.toast("Enter the administrator password to continue.", "warn");
                    input.focus();
                    return;
                }
                Loading.withButton(approve, function () {
                    return Api.post("ADMIN_APPROVE", {
                        username: username.value.trim(),
                        password: password,
                        scope: "once"
                    }, { onUnauthorised: false });
                }).then(function (data) {
                    if (blockedChat !== currentChatKey() || !wrap.isConnected) return;
                    var token = data.admin_token;
                    wrap.remove();
                    if (approveOverride) approveOverride(token);
                    else send(promptText.trim(), true, token, promptText);
                }).catch(function (err) {
                    Loading.toast(
                        err.message || "That password did not match. Check it and try again.",
                        "error"
                    );
                    input.select();
                });
            }

            Dom.on(approve, "click", submit);
            Dom.on(form, "keydown", function (e) {
                if (e.key === "Escape") {
                    e.preventDefault();
                    e.stopPropagation();
                    panel.replaceChild(ctaRow, form);
                    ask.focus();
                }
            });
            Dom.on(username, "keydown", function (e) {
                if (e.key === "Enter") { e.preventDefault(); input.focus(); }
            });
            Dom.on(input, "keydown", function (e) {
                if (e.key === "Enter") { e.preventDefault(); submit(); }
            });
        });

        card.appendChild(panel);

        var aiTurn = Dom.el("div", "turn turn-ai");
        aiTurn.appendChild(aiAvatar());
        aiTurn.appendChild(turnHead("CyberSyn"));
        var aiBody = Dom.el("div", "turn-body turn-body-wide");
        aiBody.appendChild(card);
        aiTurn.appendChild(aiBody);
        wrap.appendChild(aiTurn);

        nodes.stream.appendChild(wrap);
        scrollToEnd(true);
    }

    /* ------------------------------------------------------------------
       Sending
       ------------------------------------------------------------------ */

    function requestBudget() {
        var body = document.body || {};
        var seconds = parseInt(body.getAttribute("data-request-timeout"), 10);
        if (!seconds || seconds < 30) seconds = 270;
        return seconds * 1000;
    }

    function send(text, bypass, adminToken, rawPrompt, confirmWarn) {
        if (state.busy) return;
        state.busy = true;
        setSendBusy(true);

        var originalPrompt = typeof rawPrompt === "string" ? rawPrompt : text;
        var viewVersion = state.viewVersion;
        var composerVersion = state.composerVersion;
        var canRefill = !nodes.input.value;
        var preSendKey = currentChatKey();
        var creating = !state.chatId;
        if (creating && nodes.rename) nodes.rename.disabled = true;
        clearChatError();
        var paused = false;
        clearEmptyState();

        var waiting = showPending(text, bypass);

        var payload = {
            prompt: text,
            chat_id: state.chatId,
            bypass: !!bypass
        };
        if (creating && state.draftTitle) payload.title = state.draftTitle;
        if (adminToken) payload.admin_token = adminToken;
        if (confirmWarn) payload.confirm_warn = true;

        return Api.post("CHAT", payload, { timeout: requestBudget(), onUnauthorised: !bypass })
            .then(function (data) {
                if (viewVersion !== state.viewVersion) {
                    hidePending();
                    if (data.chat_id && !data.blocked && !data.warned) return loadChats();
                    return;
                }
                if (data.warned) {
                    hidePending();
                    paused = true;
                    renderWarning(data.warn_info || {}, originalPrompt, function () {
                        return send(text, false, null, originalPrompt, true);
                    });
                    return null;
                }
                if (data.blocked) {
                    waiting.resolve((data.block_info || {}).stage || "check1");
                    hidePending();
                    state.blockedChats[preSendKey] = true;
                    renderBlocked(data.block_info || {}, originalPrompt);
                    return null;
                }

                waiting.resolve(data.redacted || confirmWarn ? "policy" : null);

                var nextChatId = data.chat_id || state.chatId;
                var nextKey = nextChatId ? String(nextChatId) : preSendKey;
                // Carry a draft chat's prior block forward once the chat gets its id.
                if (preSendKey === DRAFT_CHAT_KEY && state.blockedChats[DRAFT_CHAT_KEY]) {
                    state.blockedChats[nextKey] = true;
                    delete state.blockedChats[DRAFT_CHAT_KEY];
                }
                state.chatId = nextChatId;
                if (creating) state.draftTitle = null;

                if (data.message_id) {
                    if (bypass) {
                        state.overriddenMessages[data.message_id] = true;
                    } else if (!data.redacted && !confirmWarn && state.blockedChats[nextKey] && !state.gracedChats[nextKey]) {
                        // D4: fires once per chat, only after a prior block in it.
                        state.gracedChats[nextKey] = true;
                        state.gracedMessages[data.message_id] = true;
                    }
                    state.messages.push({
                        id: data.message_id,
                        prompt: data.redacted ? data.redacted_prompt : text,
                        answer: data.reply_message,
                        redacted: !!data.redacted,
                        redaction_info: data.redaction_info,
                        created_at: new Date().toISOString(),
                        edited: false
                    });
                    return loadChats().then(function () {
                        hidePending();
                        if (viewVersion !== state.viewVersion) return;
                        var current = state.chats.filter(function (c) {
                            return c.id === state.chatId;
                        })[0];
                        if (current && current.title) setTitle(current.title);
                        renderMessages();
                    });
                }

                return openChat(state.chatId).then(function () {
                    hidePending();
                    return loadChats();
                });
            })
            .catch(function (err) {
                hidePending();
                if (viewVersion !== state.viewVersion) return;
                if (!nodes.stream.children.length) renderMessages();
                var code = err.body && err.body.error_code;
                // Only a definite refusal can refill the composer, and only
                // if nothing has been entered since this send started.
                if ((code === "missing_api_key" || code === "screening_failed") &&
                    canRefill && composerVersion === state.composerVersion && !nodes.input.value) {
                    nodes.input.value = originalPrompt;
                    autoGrow();
                }
                showChatError(err);
            })
            .finally(function () {
                state.busy = false;
                setSendBusy(false);
                if (creating && nodes.rename) nodes.rename.disabled = false;
                var focused = document.activeElement;
                if (!paused && viewVersion === state.viewVersion &&
                    (focused === document.body || focused === nodes.send)) nodes.input.focus();
            });
    }

    function onSend(event) {
        event.preventDefault();
        if (state.busy) return;
        var raw = nodes.input.value;
        var text = raw.trim();
        if (!text) {
            Loading.toast("Type a message first.", "info");
            nodes.input.focus();
            return;
        }
        nodes.input.value = "";
        autoGrow();
        clearSearch();
        send(text, false, null, raw);
    }

    /* ------------------------------------------------------------------
       Chat management
       ------------------------------------------------------------------ */

    function setTitle(title) {
        if (!nodes.title) return;
        nodes.title.toggleAttribute("data-no-i18n", !!title);
        nodes.title.textContent = title || t("New chat");
    }

    function openChat(chatId) {
        var viewVersion = ++state.viewVersion;
        hidePending();
        clearChatError();
        return Api.post("CHATS_OPEN", { chat_id: chatId })
            .then(function (data) {
                if (viewVersion !== state.viewVersion) return false;
                // Invalidate work that started in the old view while loading.
                state.viewVersion++;
                state.chatId = chatId;
                state.draftTitle = null;
                state.messages = (data.chat && data.chat.messages) || [];
                var chat = data.chat || {};
                setTitle(chat.title);
                state.chats.forEach(function (c) {
                    if (c.id === chatId) c.title = chat.title || c.title;
                });
                renderChatList();
                renderMessages();
                return true;
            })
            .catch(function (err) {
                if (viewVersion === state.viewVersion) Loading.toast(err.message, "error");
                return false;
            });
    }

    function newChat() {
        state.viewVersion++;
        hidePending();
        clearChatError();
        state.chatId = null;
        state.draftTitle = null;
        state.messages = [];
        delete state.blockedChats[DRAFT_CHAT_KEY];
        setTitle(null);
        renderChatList();
        renderMessages();
        nodes.input.focus();
    }

    function deleteChat(button) {
        var chatId = state.chatId;
        var viewVersion = state.viewVersion;
        if (!chatId) {
            Loading.toast("This chat has no saved messages.", "info");
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
                return Api.post("CHATS_DELETE", { chat_id: chatId });
            }).then(function () {
                Loading.toast("Chat deleted.", "success");
                return loadChats();
            }).then(function () {
                if (viewVersion === state.viewVersion) newChat();
            }).catch(function (err) { Loading.toast(err.message, "error"); });
        });
    }

    function renameChat() {
        var viewVersion = state.viewVersion;
        var chatId = state.chatId;
        var current = nodes.title.hasAttribute("data-no-i18n")
            ? nodes.title.textContent.trim()
            : "";
        Shell.prompt({
            eyebrow: "Conversation",
            title: "Rename this chat",
            label: "Chat title",
            value: current,
            placeholder: "Short title for this conversation",
            maxLength: 80,
            confirmLabel: "Save title",
            cancelLabel: "Cancel"
        }).then(function (raw) {
            if (raw === null || viewVersion !== state.viewVersion || (!chatId && state.busy)) return null;
            var next = raw.trim().replace(/\s+/g, " ").slice(0, 80).trimEnd();
            if (!next || next === current) return null;
            if (!chatId) {
                state.draftTitle = next;
                setTitle(next);
                return null;
            }
            return Api.post("CHATS_RENAME", {
                chat_id: chatId,
                title: next
            }).then(function (data) {
                if (viewVersion === state.viewVersion) setTitle(data.title);
                return loadChats();
            }).then(function () {
                Loading.toast("Chat renamed.", "success");
            }).catch(function (err) { Loading.toast(err.message, "error"); });
        });
    }

    /* ------------------------------------------------------------------
       Search within the open chat and across other conversations
       ------------------------------------------------------------------ */

    var searchVersion = 0;

    function applySearch() {
        var version = ++searchVersion;
        var query = nodes.search.value.trim();
        state.query = query;
        renderMessages();
        if (nodes.otherResults) {
            nodes.otherResults.replaceChildren();
            nodes.otherResults.hidden = true;
        }
        if (!query || !nodes.otherResults) return;
        Api.post("CHATS_SEARCH", { query: query }).then(function (data) {
            if (version !== searchVersion || query !== nodes.search.value.trim()) return;
            var hits = (data.results || []).filter(function (hit) {
                return hit.chat_id !== state.chatId;
            });
            if (!hits.length) return;
            nodes.otherResults.appendChild(Dom.el("strong", "eyebrow", t("Other conversations")));
            hits.forEach(function (hit) {
                var button = Dom.el("button", "search-hit", hit.chat_title + " — " + hit.excerpt);
                button.type = "button";
                button.setAttribute("data-no-i18n", "");
                Dom.highlightText(button, query);
                Dom.on(button, "click", function () {
                    nodes.otherResults.hidden = true;
                    openChat(hit.chat_id).then(function (opened) {
                        if (!opened) return;
                        var match = Dom.$$(".msg", nodes.stream).find(function (node) {
                            return node.dataset.id === String(hit.message_id);
                        });
                        if (match) {
                            match.tabIndex = -1;
                            match.focus({ preventScroll: true });
                            match.scrollIntoView({ block: "center" });
                        }
                    });
                });
                nodes.otherResults.appendChild(button);
            });
            nodes.otherResults.hidden = false;
        }).catch(function (err) { Loading.toast(err.message, "error"); });
    }

    function clearSearch() {
        searchVersion++;
        if (nodes.otherResults) {
            nodes.otherResults.replaceChildren();
            nodes.otherResults.hidden = true;
        }
        if (!nodes.search.value && !state.query) return;
        nodes.search.value = "";
        state.query = "";
        renderMessages();
    }

    /* ------------------------------------------------------------------
       Wiring
       ------------------------------------------------------------------ */

    Dom.on(nodes.form, "submit", onSend);
    Dom.on(nodes.input, "input", function () {
        state.composerVersion++;
        autoGrow();
    });
    Dom.on(nodes.input, "keydown", function (e) {
        // Some browsers report 229 on the Enter that commits an IME choice.
        if (e.isComposing || e.keyCode === 229) return;
        if (e.key === "Enter" && !e.shiftKey) onSend(e);
    });

    Dom.on(nodes.newChat, "click", newChat);
    Dom.on(nodes.deleteChat, "click", function () { deleteChat(nodes.deleteChat); });
    Dom.on(nodes.rename, "click", renameChat);

    /* Overflow menu — the same two actions, nothing invented. Escape closes
       and returns focus to the trigger; a click or focus anywhere else closes
       it, so no focus trap is needed for a two-item menu. */
    function setChatMenu(open) {
        if (!nodes.menu || !nodes.menuButton) return;
        nodes.menu.hidden = !open;
        nodes.menuButton.setAttribute("aria-expanded", open ? "true" : "false");
        if (open) {
            var first = nodes.menu.querySelector(".menu-item");
            if (first && typeof first.focus === "function") first.focus();
        }
    }

    function chatMenuOpen() {
        return !!(nodes.menu && !nodes.menu.hidden);
    }

    Dom.on(nodes.menuButton, "click", function (event) {
        event.stopPropagation();
        setChatMenu(!chatMenuOpen());
    });

    if (nodes.menu) {
        Dom.on(nodes.menu, "keydown", function (event) {
            var items = Dom.$$(".menu-item", nodes.menu);
            var index = items.indexOf(document.activeElement);
            if (event.key === "ArrowDown" && items.length) {
                event.preventDefault();
                items[(index + 1) % items.length].focus();
            } else if (event.key === "ArrowUp" && items.length) {
                event.preventDefault();
                items[(index - 1 + items.length) % items.length].focus();
            } else if (event.key === "Escape") {
                event.preventDefault();
                setChatMenu(false);
                nodes.menuButton.focus();
            }
        });
    }

    Dom.on(nodes.menuRename, "click", function () {
        setChatMenu(false);
        renameChat();
    });

    Dom.on(nodes.menuDelete, "click", function () {
        setChatMenu(false);
        deleteChat(nodes.deleteChat);
    });

    Dom.on(document, "click", function (event) {
        if (!chatMenuOpen()) return;
        if (nodes.menuWrap && nodes.menuWrap.contains(event.target)) return;
        setChatMenu(false);
    });

    Dom.on(document, "focusin", function (event) {
        if (!chatMenuOpen()) return;
        if (nodes.menuWrap && nodes.menuWrap.contains(event.target)) return;
        setChatMenu(false);
    });

    Dom.on(document, "keydown", function (event) {
        if (event.key === "Escape" && chatMenuOpen()) {
            setChatMenu(false);
            if (nodes.menuButton) nodes.menuButton.focus();
        }
    });

    Dom.on(nodes.search, "input", Dom.debounce(applySearch, 180));
    Dom.on(nodes.search, "keydown", function (e) {
        if (e.key === "Escape") clearSearch();
    });
    Dom.on(nodes.searchClear, "click", function () {
        clearSearch();
        nodes.search.focus();
    });

    /* ---- single-key navigation --------------------------------------
       "/" jumps to search and 1-4 drop a starter prompt into the message
       box. Both hints are painted only while their control is hovered, and
       neither fires while someone is typing in a field.
       ---------------------------------------------------------------- */

    function typingInField(target) {
        if (!target || !target.tagName) return false;
        var tag = target.tagName;
        return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" ||
            target.isContentEditable === true;
    }

    Dom.on(document, "keydown", function (event) {
        if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
        if (typingInField(event.target)) return;

        if (event.key === "/" && nodes.search) {
            event.preventDefault();
            nodes.search.focus();
            nodes.search.select();
            return;
        }

        var index = parseInt(event.key, 10);
        if (isNaN(index) || index < 1) return;
        var tile = Dom.$$(".demo-tile[data-starter]", nodes.stream)[index - 1];
        if (!tile || tile.disabled) return;
        event.preventDefault();
        tile.click();
    });

    Dom.on(document, "cybersyn:lang", function () {
        updateChecksBadge();
        renderChatList();
        applyStarterStates();
        if (pending && pending.relocalise) pending.relocalise();
        if (!state.busy &&
            !nodes.stream.querySelector(".bubble-blocked, .bubble-warned") &&
            !nodes.stream.querySelector(".is-editing")) {
            renderMessages();
        }
    });

    /* ------------------------------------------------------------------
       Start
       ------------------------------------------------------------------ */

    (function start() {
        Api.post("SETTINGS", {}).then(function (data) {
            state.settings = data;
            updateChecksBadge();
            updateMissingKeyNote(data);
            applyStarterStates();
        }).catch(function () { updateChecksBadge(); applyStarterStates(); });

        loadChats()
            .then(function () {
                if (state.viewVersion || state.busy || state.chatId) return null;
                if (state.chats.length) return openChat(state.chats[0].id);
                renderMessages();
                return null;
            })
            .catch(function (err) { Loading.toast(err.message, "error"); });

        autoGrow();
        nodes.input.focus();
    })();
})();
