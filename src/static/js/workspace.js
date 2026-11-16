/* ==========================================================================
   workspace.js — the chat screen.

   Owns: the conversation list, the message stream, sending a prompt through
   the three checks, admin override, and per-message edit / delete /
   regenerate / copy, plus in-chat search.
   ========================================================================== */

(function () {
    "use strict";

    if (!window.Shell.guard()) return;

    var Api = window.Api;
    var Dom = window.Dom;
    var Icons = window.Icons;
    var Loading = window.Loading;
    var $ = Dom.$;

    var state = {
        chats: [],
        chatId: null,
        messages: [],
        settings: { check1: true, check2: true, check3: true },
        query: "",
        busy: false
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
        searchClear: $("#search-clear"),
        searchCount: $("#search-count"),
        checksSummary: $("#checks-summary"),
        checksStatus: $("#checks-status")
    };

    /* ------------------------------------------------------------------
       Helpers
       ------------------------------------------------------------------ */

    function iconButton(name, title, action, danger) {
        var btn = Dom.el("button", "icon-btn" + (danger ? " danger" : ""));
        btn.type = "button";
        btn.title = title;
        btn.setAttribute("aria-label", title);
        btn.innerHTML = Icons.html(name);
        Dom.on(btn, "click", action);
        return btn;
    }

    function autoGrow() {
        nodes.input.style.height = "auto";
        nodes.input.style.height = Math.min(nodes.input.scrollHeight, 180) + "px";
    }

    function scrollToEnd(smooth) {
        requestAnimationFrame(function () {
            nodes.viewport.scrollTo({
                top: nodes.viewport.scrollHeight,
                behavior: smooth ? "smooth" : "auto"
            });
        });
    }

    function updateChecksBadge() {
        var on = ["check1", "check2", "check3"].filter(function (k) {
            return state.settings[k];
        }).length;
        nodes.checksSummary.textContent = on + " of 3 checks active";
        nodes.checksStatus.classList.toggle("off", on === 0);
        if (on === 0) {
            nodes.checksStatus.querySelector(".dot").style.color = "var(--warn)";
        } else {
            nodes.checksStatus.querySelector(".dot").style.color = "var(--success)";
        }
    }

    /* ------------------------------------------------------------------
       Conversation list
       ------------------------------------------------------------------ */

    function renderChatList() {
        nodes.list.innerHTML = "";
        if (!state.chats.length) {
            nodes.list.appendChild(Dom.el("p", "tiny muted", "No conversations yet."));
            return;
        }
        state.chats.forEach(function (chat) {
            var item = Dom.el("button", "chat-item");
            item.type = "button";
            if (chat.id === state.chatId) item.classList.add("is-active");
            item.innerHTML = Icons.html("chat") +
                '<span class="chat-item-title">' + Dom.esc(chat.title) + "</span>" +
                '<span class="chat-item-meta">' + Dom.timeAgo(chat.updated_at) + "</span>";
            Dom.on(item, "click", function () { openChat(chat.id); });
            nodes.list.appendChild(item);
        });
    }

    function loadChats() {
        return Api.post("/api/admin/employee/chats", {}).then(function (data) {
            state.chats = data.chats || [];
            renderChatList();
        });
    }

    /* ------------------------------------------------------------------
       Message rendering
       ------------------------------------------------------------------ */

    function renderMessage(message) {
        var wrap = Dom.el("div", "msg");
        wrap.dataset.id = message.id || "";

        var head = Dom.el("div", "msg-head");
        head.innerHTML = Icons.html("profile") +
            '<span class="who">You</span>' +
            '<span>·</span><span>' + Dom.stamp(message.created_at) + "</span>" +
            (message.edited ? "<span>· edited</span>" : "");
        wrap.appendChild(head);

        // Your message. The prompt is set as text, never as HTML, so search
        // highlighting has no markup to break.
        var mine = Dom.el("div", "bubble bubble-user");
        var mineText = Dom.el("p");
        mineText.textContent = message.prompt || "";
        mine.appendChild(mineText);
        Dom.highlightText(mineText, state.query);
        wrap.appendChild(mine);

        // The model's answer (absent when the prompt was blocked)
        var hasAnswer = message.answer && String(message.answer).trim() !== "" &&
            String(message.answer) !== "NULL";
        if (hasAnswer) {
            var reply = Dom.el("div", "bubble bubble-ai");
            reply.innerHTML = window.Markdown.render(message.answer);
            Dom.highlightText(reply, state.query);
            wrap.appendChild(reply);
        }

        // Actions: edit and delete apply to your prompt, regenerate to the answer
        var actions = Dom.el("div", "msg-actions");
        actions.appendChild(iconButton("copy", "Copy the answer", function () {
            Dom.copyText(message.answer || "")
                .then(function () { Loading.toast("Copied to clipboard.", "success"); })
                .catch(function () { Loading.toast("Could not copy.", "error"); });
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

    /* A message matches when either side of the exchange contains the query.
       Rendering decides visibility, rather than hiding nodes afterwards, so a
       re-render can never drop the filter. */
    function matchesQuery(message) {
        if (!state.query) return true;
        var needle = state.query.toLowerCase();
        return String(message.prompt || "").toLowerCase().indexOf(needle) !== -1 ||
            String(message.answer || "").toLowerCase().indexOf(needle) !== -1;
    }

    function emptyStream(title, body, icon) {
        nodes.stream.innerHTML =
            '<div class="empty">' + Icons.html(icon, "icon") +
            "<h3>" + Dom.esc(title) + "</h3><p>" + Dom.esc(body) + "</p></div>";
    }

    function renderMessages() {
        var query = state.query;
        var visible = query ? state.messages.filter(matchesQuery) : state.messages;
        nodes.stream.innerHTML = "";

        if (!visible.length) {
            if (query) {
                emptyStream(
                    "No messages match",
                    'Nothing in this chat contains "' + query + '".',
                    "search"
                );
            } else {
                emptyStream(
                    "Start the conversation",
                    "Write a message below. It is screened on this machine by three " +
                    "checks before anything is sent to an AI provider.",
                    "chat"
                );
            }
        } else {
            visible.forEach(function (message) {
                nodes.stream.appendChild(renderMessage(message));
            });
            // Only jump to the newest message when everything is on screen.
            if (!query) scrollToEnd(false);
        }

        nodes.searchCount.classList.toggle("hidden", !query);
        nodes.searchClear.classList.toggle("hidden", !query);
        if (query) {
            nodes.searchCount.textContent = Dom.plural(visible.length, "message");
        }
    }

    /* ------------------------------------------------------------------
       Per-message actions
       ------------------------------------------------------------------ */

    function beginEdit(wrap, message) {
        wrap.classList.add("is-editing");
        var editor = Dom.el("div", "msg-edit");
        editor.innerHTML =
            '<textarea class="msg-edit-input"></textarea>' +
            '<div class="msg-edit-actions">' +
            '  <button type="button" class="btn btn-sm btn-ghost msg-edit-cancel">Cancel</button>' +
            '  <button type="button" class="btn btn-sm btn-primary msg-edit-save">Save</button>' +
            "</div>";

        var textarea = editor.querySelector("textarea");
        textarea.value = message.prompt;
        editor.querySelector("textarea").focus();

        var cancel = editor.querySelector(".msg-edit-cancel");
        var save = editor.querySelector(".msg-edit-save");

        Dom.on(cancel, "click", function () {
            wrap.classList.remove("is-editing");
            editor.remove();
        });

        Dom.on(save, "click", function () {
            var next = textarea.value.trim();
            if (!next) { Loading.toast("The message cannot be empty.", "warn"); return; }
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
        if (!confirm("Delete this message? It is removed from the chat history.")) return;
        Loading.withButton(button, function () {
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
    }

    function regenerate(message, button) {
        Loading.withButton(button, function () {
            return Api.post("/api/admin/employee/chat/regenerate", {
                chat_id: state.chatId,
                message_id: message.id
            }, { timeout: 120000 });
        }).then(function (data) {
            state.messages = data.messages || [];
            renderMessages();
            Loading.toast("Answer regenerated.", "success");
        }).catch(function (err) {
            Loading.toast(err.message, "error");
        });
    }

    /* ------------------------------------------------------------------
       Blocked message card + admin override
       ------------------------------------------------------------------ */

    function renderBlocked(blockInfo, promptText) {
        var wrap = Dom.el("div", "msg");

        var head = Dom.el("div", "msg-head");
        head.innerHTML = Icons.html("profile") + '<span class="who">You</span>';
        wrap.appendChild(head);
        wrap.appendChild(Dom.el("div", "bubble bubble-user", promptText));

        var card = Dom.el("div", "bubble bubble-blocked");
        card.innerHTML =
            '<div class="blocked-head">' + Icons.html("warning") +
            "<span>Not sent — blocked by " + Dom.esc(blockInfo.stage) + "</span></div>" +
            '<div class="blocked-reason">Sensitive content was found locally, so nothing ' +
            "left this machine.</div>";

        var summary = Dom.el("div", "blocked-matches");
        summary.innerHTML =
            '<div class="blocked-match"><span class="badge badge-danger">' +
            Dom.esc(blockInfo.main_cause) + "</span>" +
            "<span>line " + Dom.esc(blockInfo.line) + "</span>" +
            "<code>" + Dom.esc(blockInfo.snippet) + "</code></div>";
        card.appendChild(summary);

        // Override: the browser collects the approval, the server enforces it.
        var panel = Dom.el("div", "override-panel");
        panel.innerHTML =
            '<input type="password" placeholder="Administrator password" ' +
            'autocomplete="off" aria-label="Administrator password">' +
            '<button type="button" class="btn btn-sm btn-warning">Approve &amp; send</button>' +
            '<p class="override-note">An administrator must approve this. The approval ' +
            "is recorded in the audit trail.</p>";

        var input = panel.querySelector("input");
        var button = panel.querySelector("button");

        Dom.on(button, "click", function () {
            var password = input.value;
            if (!password) { Loading.toast("Enter the administrator password.", "warn"); input.focus(); return; }
            Loading.withButton(button, function () {
                // Exchange the password for an admin session token, then send.
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
                send(promptText, true, token);
                wrap.remove();
            }).catch(function (err) {
                Loading.toast(err.message || "That password was not accepted.", "error");
            });
        });

        Dom.on(input, "keydown", function (e) {
            if (e.key === "Enter") { e.preventDefault(); button.click(); }
        });

        card.appendChild(panel);
        wrap.appendChild(card);
        nodes.stream.appendChild(wrap);
        scrollToEnd(true);
    }

    /* ------------------------------------------------------------------
       Sending
       ------------------------------------------------------------------ */

    function send(text, bypass, adminToken) {
        if (state.busy) return;
        state.busy = true;
        nodes.send.disabled = true;

        var scan = Loading.showScan(state.settings, bypass);

        var payload = {
            prompt: text,
            chat_id: state.chatId,
            bypass: !!bypass,
            check1: state.settings.check1,
            check2: state.settings.check2,
            check3: state.settings.check3
        };
        if (adminToken) payload.admin_token = adminToken;

        Api.post("/api/admin/employee/chat", payload, { timeout: 120000 })
            .then(function (data) {
                scan.hide();
                if (data.blocked) {
                    renderBlocked(data.block_info || {}, text);
                    Loading.toast("Blocked by " + (data.block_info || {}).stage + ".", "warn");
                    return;
                }
                state.chatId = data.chat_id || state.chatId;
                if (data.message_id) {
                    state.messages.push({
                        id: data.message_id,
                        prompt: text,
                        answer: data.reply_message,
                        created_at: new Date().toISOString(),
                        edited: false
                    });
                    renderMessages();
                } else {
                    return openChat(state.chatId);
                }
                loadChats();
            })
            .catch(function (err) {
                scan.hide();
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
        var text = nodes.input.value.trim();
        if (!text || state.busy) return;
        nodes.input.value = "";
        autoGrow();
        // A filter would hide the very message being sent.
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
                var chat = (data.chat || {});
                nodes.title.textContent = chat.title || "New chat";
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
        nodes.title.textContent = "New chat";
        renderChatList();
        renderMessages();
        nodes.input.focus();
    }

    function deleteChat(button) {
        if (!state.chatId) { Loading.toast("This chat has not been saved yet.", "info"); return; }
        if (!confirm("Delete this chat? Its messages are removed. Team statistics are kept.")) return;
        Loading.withButton(button, function () {
            return Api.post("/api/admin/employee/chats/delete", { chat_id: state.chatId });
        }).then(function () {
            Loading.toast("Chat deleted.", "success");
            return loadChats();
        }).then(function () {
            newChat();
        }).catch(function (err) { Loading.toast(err.message, "error"); });
    }

    function renameChat() {
        var current = nodes.title.textContent;
        var next = prompt("Rename this chat", current === "New chat" ? "" : current);
        if (next === null) return;
        next = next.trim().slice(0, 80);
        if (!next || next === current) return;
        if (!state.chatId) { nodes.title.textContent = next; return; }
        Api.post("/api/admin/employee/chats/rename", { chat_id: state.chatId, title: next })
            .then(function () {
                nodes.title.textContent = next;
                return loadChats();
            })
            .then(function () { Loading.toast("Chat renamed.", "success"); })
            .catch(function (err) { Loading.toast(err.message, "error"); });
    }

    /* ------------------------------------------------------------------
       Search within the current chat
       ------------------------------------------------------------------ */

    /* Read the box, store the query, re-render. Nothing else: the filtering
       lives in renderMessages so the two can never disagree. */
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

    /* ------------------------------------------------------------------
       Start
       ------------------------------------------------------------------ */

    (function start() {
        // Settings drive the checks badge; they are owned by the settings page.
        Api.post("/api/admin/employee/settings", {}).then(function (data) {
            state.settings.check1 = data.check1 !== false;
            state.settings.check2 = data.check2 !== false;
            state.settings.check3 = data.check3 !== false;
            updateChecksBadge();
        }).catch(function () { /* badge keeps its default */ });

        loadChats()
            .then(function () {
                if (state.chats.length) return openChat(state.chats[0].id);
                renderMessages();
            })
            .catch(function (err) { Loading.toast(err.message, "error"); });

        autoGrow();
        nodes.input.focus();
    })();
})();
