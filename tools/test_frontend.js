#!/usr/bin/env node
/* Front-end behaviour that only exists in the browser: the administrator
   step-up prompt and the wording on a blocked message.

   Everything here loads the real file out of src/static/js, so it checks the
   code that ships rather than a copy of it. Only the network is stubbed.

       node tools/test_frontend.js

   Needs jsdom. If it is not installed the run is skipped rather than failed,
   because a missing dev dependency is not a regression in the app:

       npm install jsdom
*/
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const candidates = [
    process.env.CYBERSYN_JSDOM,
    path.join(ROOT, "node_modules", "jsdom"),
    "/tmp/jsdomtest/node_modules/jsdom",
].filter(Boolean);

let JSDOM = null;
for (const candidate of candidates) {
    try {
        const mod = require(candidate);
        JSDOM = mod.JSDOM || mod.default || mod;
        if (typeof JSDOM === "function") break;
        JSDOM = null;
    } catch (err) { /* try the next */ }
}
if (!JSDOM) {
    console.log("SKIP  jsdom is not installed (npm install jsdom)");
    process.exit(0);
}

let pass = 0, fail = 0;
const check = (name, ok, extra) => {
    if (ok) { pass++; console.log("  PASS  " + name); }
    else { fail++; console.log("  FAIL  " + name + (extra ? " -> " + extra : "")); }
};

const read = (rel) => fs.readFileSync(path.join(ROOT, "src", "static", "js", rel), "utf8");

/** A page with the elements shell.js expects, and a stubbed Api. */
/* Where the app listens, from includes/constants.json. The server binds to
   whatever that file says, so a hardcoded 127.0.0.1:5000 here would break
   the moment someone changes the port there. */
function baseUrl() {
    if (process.env.CYBERSYN_BASE) return process.env.CYBERSYN_BASE.replace(/\/$/, "");
    let host = "127.0.0.1";
    let port = 5000;
    try {
        const constants = JSON.parse(fs.readFileSync(
            path.join(ROOT, "includes", "constants.json"), "utf8"));
        if (constants.HOST) host = constants.HOST;
        if (constants.PORT) port = constants.PORT;
    } catch (err) {
        /* A missing or malformed constants file is not this test's problem;
           the defaults match config.py's own fallbacks. */
    }
    if (host === "0.0.0.0" || host === "::") host = "127.0.0.1";
    return `http://${host}:${port}`;
}

const BASE = baseUrl();

function makePage(options) {
    const opts = options || {};
    const dom = new JSDOM(
        `<!doctype html><html><body>
           <div id="toast-container"></div>
           <div class="sidebar-unlock hidden" data-admin-lock></div>
         </body></html>`,
        { url: BASE + (opts.url || "/workspace"),
          runScripts: "outside-only", pretendToBeVisual: true }
    );
    const win = dom.window;

    win.requestAnimationFrame = (fn) => setTimeout(fn, 0);
    for (const file of ["core/dom.js", "core/stages.js", "core/icons.js"]) {
        win.eval(read(file));
    }

    const posted = [];
    win.Api = {
        Session: {
            getAdmin: () => opts.admin || { username: "boss", parentId: 2 },
            getAdminToken: () => opts.adminToken || null,
            setAdmin: (token, meta) => { win.__setAdmin = { token, meta }; },
            getMember: () => opts.member || { parentId: 2, employeeId: 5, username: "mia" },
            getMemberToken: () => "member-token",
            clearAll: () => { win.__cleared = true; },
            ready: () => true,
        },
        post: (p, body) => {
            posted.push({ path: p, body });
            if (p === "/api/admin/login") {
                if ((body.password || "") === "correct") {
                    return Promise.resolve({
                        success: true, session_token: "admin-token-1",
                        Parent_id: "2", username: body.username || "boss",
                    });
                }
                const err = new Error("Invalid password.");
                err.status = 401;
                return Promise.reject(err);
            }
            return Promise.resolve({});
        },
    };
    win.Loading = {
        toast: () => {},
        withButton: (btn, task) => Promise.resolve().then(task),
    };
    win.Icons = win.Icons || { html: () => "", svg: () => "" };

    win.eval(read("core/shell.js"));
    return { win, doc: win.document, posted };
}

/* --------------------------------------------------------------------------
   The step-up prompt
   -------------------------------------------------------------------------- */

console.log("\nAdministrator step-up");

{
    // The reported bug: an administrator token in localStorage satisfied the
    // old check, so the prompt never appeared at all.
    const { win, doc, posted } = makePage({ adminToken: "stale-token-from-login" });
    let resolved = null;
    win.Shell.withAdmin({ title: "Statistics", what: "team activity." })
        .then((t) => { resolved = t; })
        .catch(() => {});

    const overlay = doc.querySelector(".overlay");
    check("a remembered token does not skip the prompt", !!overlay,
        "no overlay was shown");
    check("the prompt names what is being unlocked",
        overlay && /Statistics/.test(overlay.textContent));
    check("the prompt explains what it protects",
        overlay && /team activity/.test(overlay.textContent));
    check("the password field is a password field",
        overlay && overlay.querySelector("#admin-gate-password").type === "password");
    check("the username is prefilled from the remembered administrator",
        overlay && /boss/.test(overlay.querySelector("#admin-gate-password").placeholder),
        overlay && overlay.querySelector("#admin-gate-password").placeholder);
    check("no request is made before the password is typed", posted.length === 0);
    check("nothing is resolved yet", resolved === null);
}

{
    const { win, doc, posted } = makePage();
    win.Shell.withAdmin({ title: "Statistics", what: "team activity." }).catch(() => {});
    const overlay = doc.querySelector(".overlay");

    // Empty password: refuse locally rather than asking the server.
    overlay.querySelector("[data-gate-unlock]").dispatchEvent(
        new win.MouseEvent("click", { bubbles: true }));
    check("an empty password is refused without a request", posted.length === 0, posted.length);
    check("an empty password says so",
        /Enter the administrator password/.test(
            overlay.querySelector("[data-gate-msg]").textContent));

    // Wrong password: the provider's answer is shown, and the prompt stays.
    overlay.querySelector("#admin-gate-password").value = "wrong";
    overlay.querySelector("[data-gate-unlock]").dispatchEvent(
        new win.MouseEvent("click", { bubbles: true }));
    setTimeout(() => {
        check("a wrong password is reported",
            /Invalid password/.test(overlay.querySelector("[data-gate-msg]").textContent),
            overlay.querySelector("[data-gate-msg]").textContent);
        check("the prompt stays open after a wrong password",
            !!doc.querySelector(".overlay"));
        nextWrong();
    }, 10);

    function nextWrong() {
        // Right password: the prompt closes and the token comes back.
        overlay.querySelector("#admin-gate-password").value = "correct";
        overlay.querySelector("[data-gate-unlock]").dispatchEvent(
            new win.MouseEvent("click", { bubbles: true }));
        setTimeout(() => {
            check("the prompt closes once the password is right",
                !doc.querySelector(".overlay"));
            check("the login was sent to the right route",
                posted.some((p) => p.path === "/api/admin/login"),
                JSON.stringify(posted.map((p) => p.path)));
            runRemember();
        }, 10);
    }

    function runRemember() {
        /* After one approval the same tab does not ask again for a while,
           but it does ask for an action marked fresh. */
        const remembered = makePage();
        remembered.win.sessionStorage.setItem("cybersyn_admin_unlock", JSON.stringify({
            token: "admin-token-1", username: "boss", parentId: 2,
            until: Date.now() + 600000,
        }));

        let quiet = true;
        remembered.win.Shell.withAdmin({ title: "Team", what: "the roster." })
            .catch(() => { quiet = false; });
        setTimeout(() => {
            check("a recent approval is not asked for again",
                quiet && !remembered.doc.querySelector(".overlay"));

            let asked = false;
            remembered.win.Shell.withAdmin({
                title: "Change", what: "policy.", fresh: true,
            }).catch(() => { asked = true; });
            setTimeout(() => {
                check("a fresh action asks even when already unlocked",
                    !!remembered.doc.querySelector(".overlay"));
                runExpiry();
            }, 10);
        }, 10);
    }

    function runExpiry() {
        const expired = makePage();
        expired.win.sessionStorage.setItem("cybersyn_admin_unlock", JSON.stringify({
            token: "admin-token-1", username: "boss", parentId: 2,
            until: Date.now() - 1000,
        }));
        expired.win.Shell.withAdmin({ title: "Statistics", what: "activity." })
            .catch(() => {});
        check("an expired unlock asks again",
            !!expired.doc.querySelector(".overlay"));

        const otherWorkspace = makePage({ member: { parentId: 9, employeeId: 1 } });
        otherWorkspace.win.sessionStorage.setItem("cybersyn_admin_unlock",
            JSON.stringify({ token: "t", username: "boss", parentId: 2,
                             until: Date.now() + 600000 }));
        otherWorkspace.win.Shell.withAdmin({ title: "Team", what: "roster." })
            .catch(() => {});
        check("an unlock from another workspace does not carry over",
            !!otherWorkspace.doc.querySelector(".overlay"));

        runBadge();
    }

    function runBadge() {
        const p = makePage();
        p.win.sessionStorage.setItem("cybersyn_admin_unlock", JSON.stringify({
            token: "admin-token-1", username: "boss", parentId: 2,
            until: Date.now() + 600000,
        }));
        p.win.Shell.paintUnlock();
        const slot = p.doc.querySelector("[data-admin-lock]");
        check("the unlocked state is visible", !slot.classList.contains("hidden"));
        check("it says how long is left", /min/.test(slot.textContent), slot.textContent);
        check("it can be closed", !!slot.querySelector("[data-action='lock-admin']"));

        slot.querySelector("[data-action='lock-admin']").dispatchEvent(
            new p.win.MouseEvent("click", { bubbles: true }));
        check("locking hides the badge again",
            p.doc.querySelector("[data-admin-lock]").classList.contains("hidden"));
        check("locking forgets the unlock",
            p.win.sessionStorage.getItem("cybersyn_admin_unlock") === null);

        runCancel();
    }

    function runCancel() {
        const p = makePage();
        let cancelled = false;
        p.win.Shell.withAdmin({ title: "Team", what: "roster." })
            .catch((err) => { cancelled = !!err.cancelled; });
        p.doc.querySelector("[data-gate-cancel]").dispatchEvent(
            new p.win.MouseEvent("click", { bubbles: true }));
        setTimeout(() => {
            check("cancelling closes the prompt", !p.doc.querySelector(".overlay"));
            check("cancelling rejects with a cancellable error", cancelled);
            runSidebar();
        }, 10);
    }
}

/* --------------------------------------------------------------------------
   The navigation

   Two things went wrong here. The button only existed on the chat screen, so
   on every other page the drawer could not be opened at all; and above the
   breakpoint it toggled a class nothing listened to, so it looked broken
   even where it did exist.

   The markup is read out of the real partials, so a page that drops the bar
   fails here rather than in someone's browser.
   -------------------------------------------------------------------------- */

const template = (name) =>
    fs.readFileSync(path.join(ROOT, "src", "templates", name), "utf8");
const partial = (name) => template("partials/" + name);

/** A signed-in page, at the width given by `isNarrow`. */
function drawerPage(isNarrow) {
    const dom = new JSDOM(
        `<!doctype html><html><body>
           <div id="toast-container"></div>
           <div class="layout">
             ${partial("sidebar.html")}
             <main class="layout-main">
               ${partial("page_bar.html")}
               <header class="page-head"><h1>Settings</h1></header>
             </main>
           </div>
         </body></html>`,
        { url: BASE + "/settings", runScripts: "outside-only", pretendToBeVisual: true }
    );
    const win = dom.window;
    win.requestAnimationFrame = (fn) => setTimeout(fn, 0);

    // jsdom does not evaluate media queries, so the breakpoint is decided
    // here. It is the same (max-width: 900px) that shell.js asks about.
    let matches = isNarrow;
    win.matchMedia = (query) => ({
        media: query,
        get matches() { return matches && /max-width/.test(query); },
        addListener() {}, removeListener() {},
        addEventListener() {}, removeEventListener() {},
    });
    win.__setNarrow = (value) => { matches = value; };

    for (const file of ["core/dom.js", "core/stages.js", "core/icons.js"]) {
        win.eval(read(file));
    }
    win.Api = {
        Session: {
            getAdmin: () => ({ username: "boss", parentId: 2 }),
            getAdminToken: () => null,
            setAdmin: () => {},
            getMember: () => ({ parentId: 2, employeeId: 5, username: "mia" }),
            getMemberToken: () => "member-token",
            clearAll: () => {},
            ready: () => true,
        },
        post: () => Promise.resolve({}),
    };
    win.Loading = { toast: () => {}, withButton: (b, task) => Promise.resolve().then(task) };
    win.Icons = win.Icons || { html: () => "", svg: () => "" };

    win.eval(read("core/shell.js"));
    win.document.dispatchEvent(new win.Event("DOMContentLoaded"));
    return { win, doc: win.document };
}

function runSidebar() {
    console.log("\nNavigation");

    // Every page with the navigation has to be able to reach it.
    fs.readdirSync(path.join(ROOT, "src", "templates"))
        .filter((f) => f.endsWith(".html"))
        .forEach((file) => {
            const text = template(file);
            if (!/partials\/sidebar\.html/.test(text)) return;
            const own = /data-action="toggle-sidebar"/.test(text);
            const shared = /partials\/page_bar\.html/.test(text);
            check(`${file} can open the navigation`, own || shared);
        });

    check("the toggle points at something that exists",
        /id="site-sidebar"/.test(partial("sidebar.html")));
    check("the shared bar carries a toggle",
        /data-action="toggle-sidebar"/.test(partial("page_bar.html")));

    /* ---- narrow: a drawer that opens and closes ---- */

    {
        const { win, doc } = drawerPage(true);
        const aside = doc.querySelector("[data-sidebar]");
        const btn = doc.querySelector("[data-action='toggle-sidebar']");
        const scrim = doc.querySelector(".sidebar-scrim");
        const click = (node) =>
            node.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));

        check("the drawer starts shut", !aside.classList.contains("is-open"));
        check("the button says so", btn.getAttribute("aria-expanded") === "false");
        check("nothing is dimmed while it is shut",
            scrim && !scrim.classList.contains("is-open"));

        click(btn);
        check("the button opens the drawer", aside.classList.contains("is-open"));
        check("the button says so", btn.getAttribute("aria-expanded") === "true");
        check("opening dims the page behind it", scrim.classList.contains("is-open"));

        click(scrim);
        check("clicking away from the drawer closes it",
            !aside.classList.contains("is-open"));
        check("and puts the button back", btn.getAttribute("aria-expanded") === "false");

        click(btn);
        doc.dispatchEvent(new win.KeyboardEvent("keydown",
            { key: "Escape", bubbles: true }));
        check("Escape closes the drawer", !aside.classList.contains("is-open"));

        click(btn);
        click(btn);
        check("a second press closes it again", !aside.classList.contains("is-open"));

        // Widening the window past the breakpoint turns the drawer back into
        // a column, which is open by default.
        click(btn);
        win.__setNarrow(false);
        win.dispatchEvent(new win.Event("resize"));
        check("crossing the breakpoint leaves the drawer state behind",
            !aside.classList.contains("is-open"));
        check("and the column is showing instead",
            !doc.querySelector(".layout").classList.contains("is-sidebar-collapsed"));
    }

    /* ---- wide: a column that can be put away ---- */

    {
        const { win, doc } = drawerPage(false);
        const layout = doc.querySelector(".layout");
        const btn = doc.querySelector("[data-action='toggle-sidebar']");
        const click = (node) =>
            node.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));

        check("the column starts out", !layout.classList.contains("is-sidebar-collapsed"));
        check("the button says it is open", btn.getAttribute("aria-expanded") === "true");

        click(btn);
        check("the button puts the column away",
            layout.classList.contains("is-sidebar-collapsed"));
        check("the button says so", btn.getAttribute("aria-expanded") === "false");
        check("the drawer class is not left on the sidebar",
            !doc.querySelector("[data-sidebar]").classList.contains("is-open"));

        click(btn);
        check("and brings it back", !layout.classList.contains("is-sidebar-collapsed"));

        // Escape is for dismissing a drawer, not for hiding a column.
        click(btn);
        doc.dispatchEvent(new win.KeyboardEvent("keydown",
            { key: "Escape", bubbles: true }));
        check("Escape does not put away a column",
            layout.classList.contains("is-sidebar-collapsed"));

        // Narrowing the window hands over to the drawer, shut.
        win.__setNarrow(true);
        win.dispatchEvent(new win.Event("resize"));
        check("narrowing hands over to a shut drawer",
            !doc.querySelector("[data-sidebar]").classList.contains("is-open") &&
            !layout.classList.contains("is-sidebar-collapsed"));
        check("the dimming layer exists once it is needed",
            !!doc.querySelector(".sidebar-scrim"));
    }

    finish();
}

/* --------------------------------------------------------------------------
   The wording on a blocked message
   -------------------------------------------------------------------------- */

function finish() {
    console.log("\nBlocked message wording");
    const dom = new JSDOM("<!doctype html><html><body></body></html>",
        { url: BASE + "/workspace", runScripts: "outside-only" });
    dom.window.eval(read("core/dom.js"));
    dom.window.eval(read("core/stages.js"));
    const Stages = dom.window.Stages;
    const Dom = dom.window.Dom;

    check("check2 is named in words",
        Stages.name("check2") === "Confidential context", Stages.name("check2"));
    check("check2 is numbered for tables",
        Stages.label("check2") === "Check 2 · Confidential context", Stages.label("check2"));
    // Fix Batch v3.1: chat verdict, reason and detailLine stay stage-agnostic
    // (Stages.checking was removed when the in-flight tracker became anonymous).
    check("the blocked verdict is stage-agnostic",
        /local check/.test(Stages.verdict("check2")) &&
        !/confidential/i.test(Stages.verdict("check2")),
        Stages.verdict("check2"));

    const reason = Stages.reason({ stage: "check1", main_cause: "AFM", line: 3 });
    check("a block explains why and where without naming the check",
        /local check/.test(reason) && /AFM/.test(reason) && /line 3/.test(reason) &&
        !/Greek ID numbers|Check 1/.test(reason),
        reason);
    const detail = Stages.detailLine("check1", {
        main_cause: "AFM", line: 2, start_offset: 40, end_offset: 49
    });
    check("the trace row omits stage identity and labels cause, line and offsets",
        detail === "Cause: AFM · Line: 2 · Characters: 40–49", detail);
    check("'unknown' is not shown as a cause",
        !/unknown/.test(Stages.reason({ stage: "check3", main_cause: "unknown" })),
        Stages.reason({ stage: "check3", main_cause: "unknown" }));
    check("a bare stage still produces a sentence",
        /local check/.test(Stages.reason({})), Stages.reason({}));

    // The snippet is attacker-influenced text, so it must not become markup.
    const evil = '<img src=x onerror="alert(1)">';
    const card = dom.window.document.createElement("div");
    card.innerHTML = "<code>" + Dom.esc(evil) + "</code>";
    check("a hostile snippet cannot inject an element",
        card.querySelector("img") === null);
    check("a hostile snippet is shown as text",
        card.querySelector("code").textContent === evil);

    runEditInPlace();
}

/* --------------------------------------------------------------------------
   In-place message editing (Final UI Batch v6)
   -------------------------------------------------------------------------- */

function runEditInPlace() {
    console.log("\nEdit in-place");

    // Final UI Batch v6: assert in-place bubble editing with zero sibling editor box.
    const dom = new JSDOM(
        `<!doctype html><html><body>
           <div id="toast-container"></div>
           <div id="chat-list"></div>
           <div id="chat-stream"><div id="chat-messages"></div></div>
           <button id="btn-rename-chat" type="button"><span id="active-chat-title">New chat</span></button>
           <form id="form-send"><textarea id="prompt-input"></textarea><button id="btn-send" type="submit"></button></form>
           <button id="btn-new-chat" type="button"></button>
           <button id="btn-delete-chat" type="button"></button>
           <div class="search-box">
             <input id="chat-search">
             <span id="search-count" class="hidden"></span>
             <button id="search-clear" class="hidden" type="button"></button>
           </div>
           <div id="checks-status"><span id="checks-summary"></span></div>
           <div id="missing-key-note" class="hidden"></div>
           <button id="btn-dismiss-key-note" type="button"></button>
         </body></html>`,
        { url: BASE + "/workspace", runScripts: "outside-only", pretendToBeVisual: true }
    );
    const win = dom.window;
    const doc = win.document;
    win.requestAnimationFrame = (fn) => setTimeout(fn, 0);
    win.HTMLElement.prototype.scrollTo = () => {};
    win.HTMLElement.prototype.scrollIntoView = () => {};

    for (const file of ["core/dom.js", "core/stages.js", "core/icons.js", "core/markdown.js"]) {
        win.eval(read(file));
    }

    const posted = [];
    const toasts = [];
    let messages = [
        { id: 101, prompt: "Original question", answer: "Original answer", created_at: "2026-11-18T10:00:00Z", edited: false }
    ];

    win.Api = {
        Session: {
            getAdmin: () => ({ username: "boss", parentId: 2 }),
            getAdminToken: () => null,
            setAdmin: () => {},
            getMember: () => ({ parentId: 2, employeeId: 5, username: "mia" }),
            getMemberToken: () => "member-token",
            clearAll: () => {},
            ready: () => true,
        },
        post: (p, body) => {
            posted.push({ path: p, body });
            if (p === "/api/admin/employee/settings") {
                return Promise.resolve({ check1: true, check2: true, check3: true, API_KEY_MASK: "sk-***" });
            }
            if (p === "/api/admin/employee/chats") {
                return Promise.resolve({ chats: [{ id: 1, title: "Thread 1", updated_at: "2026-11-18T10:00:00Z" }] });
            }
            if (p === "/api/admin/employee/chats/open") {
                return Promise.resolve({ chat: { id: 1, title: "Thread 1", messages } });
            }
            if (p === "/api/admin/employee/chats/message/edit") {
                messages = [{ id: 101, prompt: body.text, answer: "Original answer", created_at: "2026-11-18T10:00:00Z", edited: true }];
                return Promise.resolve({ messages });
            }
            return Promise.resolve({});
        },
    };
    win.Loading = {
        toast: (msg, kind) => { toasts.push({ msg, kind }); },
        withButton: (btn, task) => {
            if (btn) btn.disabled = true;
            return Promise.resolve().then(task).finally(() => {
                if (btn) btn.disabled = false;
            });
        },
    };
    win.Shell = {
        guard: () => true,
        confirm: () => Promise.resolve(false),
        prompt: () => Promise.resolve(null),
    };

    win.eval(read("workspace.js"));

    setTimeout(() => {
        const msg = doc.querySelector(".msg");
        const pencil = msg && msg.querySelector(".msg-actions-user .icon-btn");
        check("workspace message rendered with pencil action", !!pencil);

        pencil.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));

        const bubble = msg.querySelector(".bubble-user");
        const textarea = bubble && bubble.querySelector(".bubble-textarea");
        check("no sibling editor container is created outside .bubble-user",
            msg.querySelectorAll("textarea").length === 1 && bubble && bubble.contains(textarea));
        check("clicking pencil places .bubble-textarea inside .bubble-user", !!textarea);
        check("the original paragraph is replaced while editing",
            bubble && bubble.querySelector("p") === null);
        check("the editing bubble receives .is-editing",
            bubble && bubble.classList.contains("is-editing"));
        check("textarea value starts with the message text and caret at end",
            textarea && textarea.value === "Original question" &&
            textarea.selectionStart === textarea.value.length);
        check("Cancel and Save buttons live inside the editing bubble",
            !!(bubble && bubble.querySelector(".bubble-edit-actions .bubble-edit-cancel") &&
               bubble.querySelector(".bubble-edit-actions .bubble-edit-save")));

        // Blur does not save or close.
        textarea.value = "Draft while blurred";
        textarea.dispatchEvent(new win.Event("blur", { bubbles: true }));
        check("blur does not save or exit edit mode",
            !!bubble.querySelector(".bubble-textarea") &&
            !posted.some((p) => p.path === "/api/admin/employee/chats/message/edit"));

        // Escape restores paragraph and returns focus to pencil.
        textarea.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
        check("Escape restores the bubble paragraph",
            bubble.querySelector("p") && bubble.querySelector("p").textContent === "Original question" &&
            !bubble.classList.contains("is-editing"));
        check("Escape returns focus to the pencil button",
            doc.activeElement === pencil);

        // Re-open, try empty save -> warn toast, keep editing.
        pencil.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
        const ta2 = bubble.querySelector(".bubble-textarea");
        ta2.value = "   ";
        bubble.querySelector(".bubble-edit-save").dispatchEvent(
            new win.MouseEvent("click", { bubbles: true }));
        check("empty trimmed save keeps editor open and warns",
            !!bubble.querySelector(".bubble-textarea") &&
            toasts.some((item) => item.kind === "warn"));

        // Cmd/Ctrl+Enter saves in place to the edit endpoint.
        ta2.value = "Updated in place";
        ta2.dispatchEvent(new win.KeyboardEvent("keydown", {
            key: "Enter", ctrlKey: true, bubbles: true
        }));
        setTimeout(() => {
            const editPost = posted.find((p) => p.path === "/api/admin/employee/chats/message/edit");
            check("Ctrl/Cmd+Enter submits to the edit endpoint",
                !!(editPost && editPost.body.text === "Updated in place" && editPost.body.message_id === 101));
            const updatedP = doc.querySelector(".bubble-user p");
            check("the saved text renders inside .bubble-user without a separate box",
                updatedP && updatedP.textContent === "Updated in place" &&
                doc.querySelector(".bubble-textarea") === null);
            check("focus returns to the pencil button after save",
                doc.activeElement === doc.querySelector(".msg-actions-user .icon-btn"));

            console.log(`\n${pass} passed, ${fail} failed`);
            process.exit(fail ? 1 : 0);
        }, 25);
    }, 25);
}
