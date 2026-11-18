#!/usr/bin/env node
/* ==========================================================================
   Frontend checks — admin approval gate, navigation drawer, stage wording,
   in-place bubble editing, browser boundaries, and signed-in screens.

   Mocks only fetch/session; everything else runs inside jsdom against the
   real browser scripts and HTML templates.
   ========================================================================== */

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const ROUTES = require("../includes/constants.json").ROUTES;
const candidates = [
    process.env.CYBERSYN_JSDOM, "jsdom",
    path.join(ROOT, "node_modules", "jsdom"),
    "/tmp/jsdomtest/node_modules/jsdom",
].filter(Boolean);

let JSDOM;
for (const c of candidates) {
    try { ({ JSDOM } = require(c)); break; } catch (_) {}
}
if (!JSDOM) {
    console.error("jsdom not found. Set CYBERSYN_JSDOM or npm install jsdom.");
    process.exit(2);
}

const BASE = "https://cybersyn.test";
const JS = path.join(ROOT, "src", "static", "js");
const read = (rel) => fs.readFileSync(path.join(JS, rel), "utf8");

let pass = 0, fail = 0;
function check(label, cond, detail) {
    if (cond) { pass++; console.log(`  ok   ${label}`); }
    else { fail++; console.error(`  FAIL ${label}${detail ? " — " + detail : ""}`); }
}

/* --------------------------------------------------------------------------
   A fake page with Shell + Dom + Icons + a stubbed Api
   -------------------------------------------------------------------------- */

function makePage(opts = {}) {
    const dom = new JSDOM(
        `<!doctype html><html><body>
           <div id="toast-container"></div>
           <div class="sidebar-user">
             <span data-member-avatar></span>
             <span data-member-name></span>
             <span data-admin-lock class="hidden"></span>
           </div>
           <a href="/stats">Statistics</a>
           <a href="/team">Team</a>
         </body></html>`,
        { url: BASE + "/workspace", runScripts: "outside-only", pretendToBeVisual: true }
    );
    const win = dom.window;
    const doc = win.document;

    /* jsdom doesn't animate frames cleanly; let focus run synchronously-ish. */
    win.requestAnimationFrame = (fn) => setTimeout(fn, 0);

    for (const file of ["core/dom.js", "core/stages.js", "core/icons.js"]) {
        win.eval(read(file));
    }

    const posted = [];
    const routes = ROUTES;
    win.Api = {
        Session: {
            getAdmin: () => opts.admin || { username: "boss", parentId: 2 },
            setAdmin: (token, meta) => { win.__setAdmin = { token, meta }; },
            getMember: () => opts.member || { parentId: 2, employeeId: 5, username: "mia" },
            clearAll: () => { win.__cleared = true; },
            ready: () => true,
        },
        post: (key, body) => {
            const p = routes[key];
            posted.push({ path: p, body });
            if (p === ROUTES.OVERRIDE_CHECK) return Promise.resolve({ allowed: !opts.revoked });
            if (p === ROUTES.ADMIN_APPROVE) {
                if ((body.password || "") === "correct") {
                    return Promise.resolve({
                        success: true, admin_token: body.scope === "once" ? "one-use-test" : undefined,
                        Parent_id: "2", username: body.username || "boss",
                    });
                }
                return Promise.reject(Object.assign(new Error("Invalid password."), { status: 401 }));
            }
            return Promise.resolve({});
        },
    };
    win.Loading = { toast: () => {}, withButton: (b, task) => Promise.resolve().then(task) };
    win.Icons = win.Icons || { html: () => "", svg: () => "" };

    win.eval(read("core/shell.js"));
    return { win, doc, posted };
}

/* --------------------------------------------------------------------------
   The step-up prompt
   -------------------------------------------------------------------------- */

console.log("\nAdministrator step-up");

{
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
            check("the dialog requests a page-only approval",
                posted.some((p) => p.path === ROUTES.ADMIN_APPROVE && p.body.scope === "page"),
                JSON.stringify(posted.map((p) => p.path)));
            check("approval never sets a primary admin session", !win.__setAdmin);
            runRemember();
        }, 10);
    }

    function runRemember() {
        /* After one approval the same tab does not ask again for a while,
           but it does ask for an action marked fresh. */
        const remembered = makePage();
        remembered.win.sessionStorage.setItem("cybersyn_page_hint", JSON.stringify({
            username: "boss", parentId: 2,
            until: Date.now() + 600000,
        }));

        let quiet = true;
        remembered.win.Shell.withAdmin({ title: "Team", what: "roster." })
            .catch(() => { quiet = false; });
        setTimeout(() => {
            check("a recent approval is not asked for again",
                quiet && !remembered.doc.querySelector(".overlay"));
            check("remembered access is verified by server",
                remembered.posted.some((p) => p.path.endsWith("override/check")));

            let asked = false;
            remembered.win.Shell.withAdmin({
                title: "Settings", what: "changing a key.", fresh: true,
            }).catch(() => {});
            asked = !!remembered.doc.querySelector(".overlay");
            check("changing a key still asks afresh", asked);
            remembered.doc.querySelector("[data-gate-cancel]").click();

            runExpiry();
        }, 10);
    }

    function runExpiry() {
        const expired = makePage();
        expired.win.sessionStorage.setItem("cybersyn_page_hint", JSON.stringify({
            username: "boss", parentId: 2,
            until: Date.now() - 1000,
        }));
        expired.win.Shell.withAdmin({ title: "Statistics", what: "activity." })
            .catch(() => {});
        check("an expired approval asks again",
            !!expired.doc.querySelector(".overlay"));

        const otherWorkspace = makePage({ member: { parentId: 9, employeeId: 1 } });
        otherWorkspace.win.sessionStorage.setItem("cybersyn_page_hint",
            JSON.stringify({ username: "boss", parentId: 2,
                             until: Date.now() + 600000 }));
        otherWorkspace.win.Shell.withAdmin({ title: "Team", what: "roster." })
            .catch(() => {});
        check("an approval for another workspace asks again",
            !!otherWorkspace.doc.querySelector(".overlay"));

        runBadge();
    }

    function runBadge() {
        const p = makePage();
        p.win.sessionStorage.setItem("cybersyn_page_hint", JSON.stringify({
            username: "boss", parentId: 2,
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
            p.win.sessionStorage.getItem("cybersyn_page_hint") === null);

        check("Lock now revokes the server page grant",
            p.posted.some((r) => r.path === ROUTES.ADMIN_LOGOUT && r.body.scope === "page"));
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
            setAdmin: () => {},
            getMember: () => ({ parentId: 2, employeeId: 5, username: "mia" }),
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

        click(btn);
        doc.dispatchEvent(new win.KeyboardEvent("keydown",
            { key: "Escape", bubbles: true }));
        check("Escape does not put away a column",
            layout.classList.contains("is-sidebar-collapsed"));

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
   Blocked wording, in-place editing, browser boundaries & signed-in screens
   -------------------------------------------------------------------------- */

async function finish() {
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

    const evil = '<img src=x onerror="alert(1)">';
    const card = dom.window.document.createElement("div");
    card.innerHTML = "<code>" + Dom.esc(evil) + "</code>";
    check("a hostile snippet cannot inject an element",
        card.querySelector("img") === null);
    check("a hostile snippet is shown as text",
        card.querySelector("code").textContent === evil);

    await runEditInPlace();
    testBrowserBoundaries();
    await testSignedInScreens();

    console.log(`\n${pass} passed, ${fail} failed`);
    process.exit(fail ? 1 : 0);
}

function runEditInPlace() {
    console.log("\nEdit in-place");
    return new Promise((resolve) => {
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
                 <section id="other-chat-results" hidden></section>
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
                setAdmin: () => {},
                getMember: () => ({ parentId: 2, employeeId: 5, username: "mia" }),
                clearAll: () => {},
                ready: () => true,
            },
            post: (key, body) => {
                const p = ROUTES[key] || key;
                posted.push({ key, path: p, body });
                if (key === "SETTINGS") {
                    return Promise.resolve({ check1: true, check2: true, check3: true, API_KEY_MASK: "sk-***" });
                }
                if (key === "CHATS") {
                    return Promise.resolve({ chats: [{ id: 1, title: "Thread 1", updated_at: "2026-11-18T10:00:00Z" }] });
                }
                if (key === "CHATS_OPEN") {
                    return Promise.resolve({ chat: { id: 1, title: "Thread 1", messages } });
                }
                if (key === "MESSAGE_EDIT") {
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

            textarea.value = "Draft while blurred";
            textarea.dispatchEvent(new win.Event("blur", { bubbles: true }));
            check("blur does not save or exit edit mode",
                !!bubble.querySelector(".bubble-textarea") &&
                !posted.some((p) => p.key === "MESSAGE_EDIT"));

            textarea.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
            check("Escape restores the bubble paragraph",
                bubble.querySelector("p") && bubble.querySelector("p").textContent === "Original question" &&
                !bubble.classList.contains("is-editing"));
            check("Escape returns focus to the pencil button",
                doc.activeElement === pencil);

            pencil.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
            const ta2 = bubble.querySelector(".bubble-textarea");
            ta2.value = "   ";
            bubble.querySelector(".bubble-edit-save").dispatchEvent(
                new win.MouseEvent("click", { bubbles: true }));
            check("empty trimmed save keeps editor open and warns",
                !!bubble.querySelector(".bubble-textarea") &&
                toasts.some((item) => item.kind === "warn"));

            ta2.value = "Updated in place";
            ta2.dispatchEvent(new win.KeyboardEvent("keydown", {
                key: "Enter", ctrlKey: true, bubbles: true
            }));
            setTimeout(() => {
                const editPost = posted.find((p) => p.key === "MESSAGE_EDIT");
                check("Ctrl/Cmd+Enter submits to the edit endpoint",
                    !!(editPost && editPost.body.text === "Updated in place" && editPost.body.message_id === 101));
                const updatedP = doc.querySelector(".bubble-user p");
                check("the saved text renders inside .bubble-user without a separate box",
                    updatedP && updatedP.textContent === "Updated in place" &&
                    doc.querySelector(".bubble-textarea") === null);
                check("focus returns to the pencil button after save",
                    doc.activeElement === doc.querySelector(".msg-actions-user .icon-btn"));
                win.close();
                resolve();
            }, 25);
        }, 25);
    });
}

function testBrowserBoundaries() {
    console.log("\nBrowser boundaries");
    const dom = new JSDOM(`<body><h1>Settings</h1><div class="bubble-ai"><p>Settings</p></div>
      <span data-member-name>Admin</span><code>Open</code><input value="Send"></body>`,
      { url: BASE, runScripts: "outside-only" });
    const win = dom.window;
    win.document.body.dataset.routes = JSON.stringify(ROUTES);
    win.localStorage.setItem("cybersyn_admin_token", "old-admin");
    win.localStorage.setItem("cybersyn_member_token", "old-member");
    ["core/dom.js", "core/i18n.js", "core/markdown.js", "core/api.js"].forEach((f) => win.eval(read(f)));
    win.Api.Session.setAdmin({ parentId: 1, username: "owner", token: "not-to-store" });
    win.Api.Session.setMember({ parentId: 1, employeeId: 2, username: "member", session_token: "not-to-store" });
    check("only non-secret UI metadata is stored", win.Api.Session.ready() &&
        !/old-admin|old-member|not-to-store|_token/.test(JSON.stringify(win.localStorage)));
    let req;
    win.fetch = (url, opts) => { req = { url, opts }; return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) }); };
    win.Api.post("SETTINGS", {});
    check("requests use the route registry and CSRF-protected cookies", req.url === ROUTES.SETTINGS &&
        req.opts.credentials === "same-origin" && req.opts.headers["X-CyberSyn-Request"] === "1" && !req.opts.body.includes("token"));
    const rich = win.Markdown.render("**bold** `a * b * c` `**kwargs` `<tag>`");
    check("code spans preserve operators and HTML escaping", rich.includes("<strong>bold</strong>") &&
        rich.includes("<code>a * b * c</code>") && rich.includes("<code>**kwargs</code>") && rich.includes("<code>&lt;tag&gt;</code>"));
    win.I18n.set("el");
    check("translate chrome, not chats, names, code or input values", win.document.querySelector("h1").textContent === "Ρυθμίσεις" &&
        win.document.querySelector(".bubble-ai p").textContent === "Settings" && win.document.querySelector("[data-member-name]").textContent === "Admin" &&
        win.document.querySelector("code").textContent === "Open" && win.document.querySelector("input").value === "Send");
    check("dollar in translated dynamic text is literal", win.I18n.t("Signed in as $&").endsWith("$&"));
    win.I18n.set("en");
    check("English is restored", win.document.querySelector("h1").textContent === "Settings");
    win.close();
}

function screenFixture(page, answer, employeeId = 5) {
    const html = template(page + ".html").match(/\{% block body %\}([\s\S]*?)\{% endblock %\}/)[1]
        .replace(/\{% include "([^"]+\.html)" %\}/g, (_, name) => template(name))
        .replace("{% include sidebar_extra %}", page === "workspace" ? partial("chat_list.html") : "")
        .replace(/\{#[\s\S]*?#\}|\{%[\s\S]*?%\}/g, "");
    const win = new JSDOM(html, { url: BASE + "/" + page, runScripts: "outside-only", pretendToBeVisual: true }).window;
    const routes = ROUTES;
    win.document.body.dataset.routes = JSON.stringify(routes);
    const posted = [], approvals = [], messages = [];
    win.HTMLElement.prototype.scrollTo = function () {};
    win.HTMLElement.prototype.scrollIntoView = function () { this.dataset.scrolled = "1"; };
    win.fetch = (url, opts) => {
        const key = Object.keys(routes).find((k) => routes[k] === url);
        const body = JSON.parse(opts.body);
        posted.push({ key, body });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(answer(key, body)) });
    };
    for (const f of ["dom", "stages", "icons", "i18n", "markdown", "api"]) win.eval(read("core/" + f + ".js"));
    win.Api.Session.setMember({ parentId: 2, employeeId, username: "Settings" });
    win.Shell = { guard: () => true, withAdmin: (opts) => {
        approvals.push(opts); return Promise.resolve("test-grant-" + approvals.length);
    } };
    win.Loading = { toast: (text) => messages.push(text), withButton: (_, task) => Promise.resolve().then(task) };
    win.eval(read(page + ".js"));
    return { win, posted, approvals, messages, $: (s) => win.document.querySelector(s) };
}

async function testSignedInScreens() {
    console.log("\nSigned-in screens");
    const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
    const revoked = makePage({ revoked: true });
    revoked.win.sessionStorage.setItem("cybersyn_page_hint", JSON.stringify({ username: "boss", parentId: 2, until: Date.now() + 60000 }));
    const pending = revoked.win.Shell.withAdmin({ title: "Team", what: "the roster" }).catch(() => {});
    await tick();
    check("a revoked server grant cannot be restored from a local hint", !!revoked.doc.querySelector(".overlay") && !revoked.win.sessionStorage.getItem("cybersyn_page_hint"));
    revoked.doc.querySelector("[data-gate-cancel]").click(); await pending; revoked.win.close();

    const fresh = makePage();
    const grant = fresh.win.Shell.withAdmin({ fresh: true, title: "Settings", what: "a change" });
    fresh.doc.querySelector("#admin-gate-password").value = "correct";
    fresh.doc.querySelector("[data-gate-unlock]").click();
    check("fresh step-up returns only a one-use credential to its caller", await grant === "one-use-test" &&
        fresh.posted[0].body.scope === "once" && !fresh.win.sessionStorage.length && !fresh.win.localStorage.length);
    fresh.win.close();

    const base = "https://models.example/prefix/v1";
    const records = { 5: true, 6: false };
    const answer = (key, body) => {
        if (key === "SETTINGS") {
            if (typeof body.block_code === "boolean") records[body.Employee_id] = body.block_code;
            return {
                check1: true, check2: false, check3: true, block_code: records[body.Employee_id], MODEL_NAME: "Settings",
                API_KEY_MASK: body.CLEAR_API_KEY ? "" : "****1234", PROVIDER: "openai", API_BASE: base
            };
        }
        if (key === "PROVIDERS") return { providers: ["auto", "openai", "custom"].map((k) => ({ key: k, label: k })) };
        if (key === "MODELS") return { models: ["Settings"], provider: body.provider };
        return {};
    };
    const first = screenFixture("settings", answer), other = screenFixture("settings", answer, 6);
    await tick();
    check("Settings renders each member's own code toggle", first.$("#setting-block-code").checked && !other.$("#setting-block-code").checked);
    check("saved named-provider base path survives load and automatic discovery", first.$("#setting-base").value === base &&
        first.posted.find((r) => r.key === "MODELS").body.API_BASE === base);
    first.win.I18n.set("el");
    check("model names are data, not interface copy", first.$("#setting-model option:checked").textContent === "Settings");
    first.$("#setting-block-code").checked = false;
    first.$("#btn-save-checks").click();
    await tick();
    const policy = first.posted.find((r) => r.key === "SETTINGS" && "block_code" in r.body).body;
    check("saving targets this member, not the default or another member", policy.Employee_id === 5 && policy.block_code === false &&
        !policy.also_default && policy.admin_token === "test-grant-1" && first.approvals[0].fresh);
    first.$("#setting-base").value = "";
    first.$("#btn-refresh-models").click();
    await tick();
    const refresh = first.posted.filter((r) => r.key === "MODELS").pop().body;
    check("probing a new destination with the stored key asks afresh", refresh.API_BASE === "" && refresh.admin_token === "test-grant-2" &&
        first.approvals[1].fresh && !("API_KEY" in refresh));
    first.$("#connection-also-default").checked = true;
    first.$("#btn-save-connection").click();
    await tick();
    const connection = first.posted.find((r) => r.key === "SETTINGS" && "API_BASE" in r.body).body;
    check("a cleared base is sent explicitly; copying to default is opt-in", connection.API_BASE === "" && connection.also_default === true);
    first.$("#btn-clear-key").click();
    await tick();
    check("removing the saved key sends an approved clear operation", first.posted.some((r) => r.body.CLEAR_API_KEY && r.body.admin_token === "test-grant-4"));
    first.win.close(); other.win.close();

    const workspace = screenFixture("workspace", (key, body) => {
        if (key === "SETTINGS") return { check1: false, check2: false, check3: false, block_code: true };
        if (key === "CHATS") return { chats: [{ id: 1, title: "Here" }, { id: 2, title: "Settings" }] };
        if (key === "CHATS_OPEN") return { chat: { id: body.chat_id, title: body.chat_id === 1 ? "Here" : "Settings", messages: [{
            id: "message-" + body.chat_id, prompt: "needle", answer: "**needle**", created_at: "2026-11-18T09:00:00Z" }] } };
        if (key === "CHATS_SEARCH") return { results: [1, 2].map((id) => ({ chat_id: id, message_id: "message-" + id, chat_title: "Settings", excerpt: "<em>needle</em>" })) };
        if (key === "CHAT") return body.bypass ? { chat_id: 2, message_id: "granted", reply_message: "ok" } :
            { blocked: true, block_info: { stage: "check2", main_cause: "computer source code", line: 1, snippet: "Settings" } };
        if (key === "ADMIN_APPROVE") return { admin_token: "inline-once" };
        return {};
    });
    await tick();
    const search = workspace.$("#chat-search");
    search.value = "needle"; search.dispatchEvent(new workspace.win.Event("input"));
    await new Promise((resolve) => setTimeout(resolve, 220));
    check("cross-chat hits are separate, highlighted and never interpreted as HTML", workspace.$("#other-chat-results .search-hit mark").textContent === "needle" &&
        !workspace.$("#other-chat-results .search-hit em") && workspace.win.document.querySelectorAll(".search-hit").length === 1);
    workspace.$(".search-hit").click(); await tick();
    check("a search result opens the other chat and focuses the matching message", workspace.$("#active-chat-title").textContent === "Settings" &&
        workspace.win.document.activeElement.dataset.id === "message-2" && workspace.$(".msg[data-scrolled] .bubble-ai mark").textContent === "needle");
    workspace.win.I18n.set("el");
    check("a chat named Settings keeps its original title", workspace.$("#active-chat-title").textContent === "Settings");
    for (let i = 0; i < 2; i++) {
        workspace.$("#prompt-input").value = "example paste";
        workspace.$("#form-send").dispatchEvent(new workspace.win.Event("submit", { cancelable: true }));
        await tick();
    }
    const sent = workspace.posted.find((r) => r.key === "CHAT").body;
    check("chat never sends policy toggles or model overrides", !["check1", "check2", "check3", "block_code", "MODEL_NAME", "API_KEY"].some((k) => k in sent));
    workspace.win.document.querySelectorAll(".override-ask").forEach((b) => b.click());
    const ids = Array.from(workspace.win.document.querySelectorAll("[id]"), (el) => el.id);
    check("multiple override forms do not introduce duplicate DOM ids", new Set(ids).size === ids.length);
    workspace.$(".override-name").value = "another-owner"; workspace.$(".override-pass").value = "  example password 1  ";
    workspace.$(".override-send").click(); await tick();
    check("inline override uses the edited username, exact password and one-use approval", workspace.posted.some((r) =>
        r.key === "ADMIN_APPROVE" && r.body.username === "another-owner" && r.body.password === "  example password 1  " && r.body.scope === "once") &&
        workspace.posted.some((r) => r.key === "CHAT" && r.body.bypass && r.body.admin_token === "inline-once"));
    check("no override token survives in either browser storage", !/inline-once/.test(JSON.stringify(workspace.win.localStorage) + JSON.stringify(workspace.win.sessionStorage)));
    workspace.win.close();

    const profile = screenFixture("profile", (key) => key === "ADMIN_APPROVE" ? { admin_token: "profile-once" } : {});
    await tick();
    const form = profile.$("#form-admin-password");
    form.elements.username.value = "owner";
    form.elements.current_password.value = "  old 123  "; form.elements.new_password.value = "  new 456  ";
    form.dispatchEvent(new profile.win.Event("submit", { cancelable: true })); await tick();
    check("Profile uses a fresh approval to change the administrator password", profile.posted.some((r) => r.key === "ADMIN_PASSWORD" &&
        r.body.token === "profile-once" && r.body.new_password === "  new 456  " && r.body.current_password === "  old 123  "));
    profile.win.close();
}
