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

    /* ------------------------------------------------------------------
       Waiting indicator

       The server runs every check and then the model call inside one request,
       so there is no real progress to report. What is honest is to say which
       stage is being worked through and cycle through the ones that are
       actually switched on, rather than freezing on one word or claiming
       completion it cannot know about.
       ------------------------------------------------------------------ */

    var Stages = window.Stages;

    var pending = null;


    function showPending(promptText, bypass) {
        hidePending();

        var order = ["check1", "check2", "check3"].filter(function (id) {
            return state.settings[id] !== false;
        });
        var script = order.map(function (id) { return Stages.checking(id); });
        script.unshift("Thinking");
        script.push(bypass ? "Sending with approval" : "Waiting for the model");

        var wrap = Dom.el("div", "msg");
        var head = Dom.el("div", "msg-head");
        head.innerHTML = Icons.html("profile") + '<span class="who">You</span>';
        wrap.appendChild(head);
        wrap.appendChild(Dom.el("div", "bubble bubble-user", promptText));

        var note = Dom.el("div", "msg-pending");
        note.innerHTML =
            '<span class="pending-dots" aria-hidden="true">' +
            "<i></i><i></i><i></i></span>" +
            '<span class="pending-text"></span>';
        wrap.appendChild(note);

        nodes.stream.appendChild(wrap);
        scrollToEnd(true);

        var label = note.querySelector(".pending-text");
        var index = 0;
        var tick = setInterval(function () {
            label.textContent = script[index % script.length] + "…";
            index += 1;
        }, 900);
        label.textContent = script[0] + "…";

        pending = {
            wrap: wrap,
            stop: function () {
                clearInterval(tick);
                if (wrap.parentNode) wrap.remove();
            }
        };
        return pending;
    }

    function hidePending() {
        if (pending) pending.stop();
        pending = null;
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
            "<span>Not sent — stopped by " + Dom.esc(Stages.name(blockInfo.stage)) + "</span></div>" +
            '<p class="blocked-what">Nothing left this machine. The message was screened ' +
            "on this computer, matched a rule, and was refused before it reached any " +
            "AI provider.</p>" +
            '<p class="blocked-why">' + Dom.esc(Stages.reason(blockInfo)) + "</p>";

        // Everything the scanner flagged, not just the first thing.
        var summary = Dom.el("div", "blocked-matches");
        var found = Array.isArray(blockInfo.matches) ? blockInfo.matches : [];
        if (!found.length) {
            found = [{
                main_cause: blockInfo.main_cause,
                line: blockInfo.line,
                snippet: blockInfo.snippet
            }];
        }
        summary.innerHTML = found.map(function (match) {
            return '<div class="blocked-match">' +
                '<span class="badge badge-danger">' +
                Dom.esc(match.main_cause || "match") + "</span>" +
                "<span>line " + Dom.esc(match.line) + "</span>" +
                "<code>" + Dom.esc(match.snippet || "") + "</code>" +
                "</div>";
        }).join("");
        card.appendChild(summary);

        /* Bypass: a button, not a password box sitting in every blocked card.
           Pressing it asks who is approving, and the server is what enforces
           it — the browser only collects the approval. */
        var panel = Dom.el("div", "override-panel");
        panel.innerHTML =
            '<button type="button" class="btn btn-sm override-ask">Send anyway</button>' +
            '<p class="override-note">Needs an administrator password, and is ' +
            "recorded in the audit trail.</p>";

        var ask = panel.querySelector(".override-ask");

        Dom.on(ask, "click", function () {
            var form = Dom.el("div", "override-form");
            form.innerHTML =
                '<label class="override-label" for="override-password">' +
                "Administrator password</label>" +
                '<input type="password" id="override-password" class="input" ' +
                'placeholder="Administrator password" autocomplete="off">' +
                '<div class="override-actions">' +
                '<button type="button" class="btn btn-sm btn-primary override-send">' +
                "Approve &amp; send</button>" +
                '<button type="button" class="btn btn-sm btn-ghost override-cancel">' +
                "Cancel</button>" +
                "</div>";
            panel.replaceChild(form, ask);

            var input = form.querySelector("input");
            var approve = form.querySelector(".override-send");
            input.focus();

            Dom.on(form.querySelector(".override-cancel"), "click", function () {
                panel.replaceChild(ask, form);
            });

            function submit() {
                var password = input.value;
                if (!password) {
                    Loading.toast("Enter the administrator password.", "warn");
                    input.focus();
                    return;
                }
                Loading.withButton(approve, function () {
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
                    wrap.remove();
                    send(promptText, true, token);
                }).catch(function (err) {
                    Loading.toast(err.message || "That password was not accepted.", "error");
                    input.select();
                });
            }

            Dom.on(approve, "click", submit);
            Dom.on(input, "keydown", function (e) {
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

    function send(text, bypass, adminToken) {
        if (state.busy) return;
        state.busy = true;
        nodes.send.disabled = true;

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

        Api.post("/api/admin/employee/chat", payload, { timeout: 120000 })
            .then(function (data) {
                hidePending();
                if (data.blocked) {
                    // The card says everything; nothing should pop up.
                    renderBlocked(data.block_info || {}, text);
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
                waiting.stop();
                pending = null;
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
