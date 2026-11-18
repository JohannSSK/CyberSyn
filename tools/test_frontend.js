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

let JSDOM, VirtualConsole;
for (const c of candidates) {
    try { ({ JSDOM, VirtualConsole } = require(c)); break; } catch (_) {}
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

/* --------------------------------------------------------------------------
   The night-slate chat skin: cool ground, two labelled voices, one date line,
   one instrument below the words.
   -------------------------------------------------------------------------- */

const luminance = (hex) => {
    const n = hex.replace("#", "");
    const parts = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255)
        .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];
};
const contrast = (a, b) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
};
const tokenOf = (css, name) => (css.match(new RegExp("--" + name + ":\\s*(#[0-9a-f]{6})")) || [])[1];

function testChatReskin() {
    console.log("\nNight-slate ground");
    const base = sheet("base.css");
    const palette = {
        bg: "#101318", surface: "#161a21", "surface-2": "#1c212a",
        "surface-3": "#232936", "surface-4": "#2b3242",
    };
    for (const [name, hex] of Object.entries(palette)) {
        check(`--${name} is the cool slate value ${hex}`, tokenOf(base, name) === hex, tokenOf(base, name));
    }
    check("the cream accent is the one warm survivor", tokenOf(base, "accent") === "#ecebe7");
    check("status hues are unchanged from v5",
        tokenOf(base, "success") === "#97ab91" && tokenOf(base, "warn") === "#bfa273" &&
        tokenOf(base, "danger") === "#bd8a80");
    check("the sidebar narrows from 268px to 240px", /--sidebar-w:\s*240px/.test(base));
    check("body copy clears 4.5:1 on the ground, panel and raised fills",
        contrast("#e8eaee", "#101318") >= 4.5 && contrast("#e8eaee", "#161a21") >= 4.5 &&
        contrast("#e8eaee", "#1c212a") >= 4.5 && contrast("#e8eaee", "#232936") >= 4.5);
    check("secondary copy clears 4.5:1 on every text surface",
        contrast("#b9bec9", "#101318") >= 4.5 && contrast("#b9bec9", "#232936") >= 4.5);
    check("muted copy clears 4.5:1 on --surface-3, where hover copy lives",
        contrast("#8d93a1", "#232936") >= 4.5, contrast("#8d93a1", "#232936").toFixed(2));
    check("the focus ring clears 3:1 against --surface-2",
        contrast("#ecebe7", "#1c212a") >= 3);
    check("every avatar pair still clears 4.5:1 internally",
        [...base.matchAll(/--avatar-\w+-bg:\s*(#[0-9a-f]{6});\s*\n\s*--avatar-\w+-fg:\s*(#[0-9a-f]{6})/g)]
            .every((m) => contrast(m[1], m[2]) >= 4.5));

    console.log("\nSidebar without the rail");
    const side = sheet("sidebar.css");
    check("no rail terminology or 3px bar survives in the chrome",
        !/rail|3px solid|sidebar-rail/.test(side) && !/is-active::before/.test(side));
    check("the active row is a rounded fill with a bright glyph",
        /\.nav-item\.is-active \{[^}]*background: var\(--surface-2\)[^}]*\}/.test(side) &&
        /\.nav-item\.is-active \.icon \{ color: var\(--text-strong\)/.test(side));
    check("resting nav glyphs sit at --text-dim", /\.nav-item \.icon \{[^}]*color: var\(--text-dim\)/.test(side));

    console.log("\nTwo-line heading and overflow menu");
    const wsHtml = template("workspace.html");
    check("the title block carries a second line",
        /class="topbar-subtitle">A conversation with CyberSyn</.test(wsHtml) &&
        /class="topbar-title-row"/.test(wsHtml));
    check("the overflow menu exposes exactly the two existing actions",
        /id="btn-chat-menu"/.test(wsHtml) &&
        (wsHtml.match(/class="menu-item[\s"]/g) || []).length === 2 &&
        /id="menu-rename-chat"/.test(wsHtml) && /id="menu-delete-chat"/.test(wsHtml));
    check("the menu is labelled and starts closed",
        /aria-haspopup="menu"/.test(wsHtml) && /aria-expanded="false"/.test(wsHtml) &&
        /id="chat-menu"[^>]*hidden/.test(wsHtml));

    console.log("\nTurns, date dividers and bubbles");
    const wsCss = sheet("workspace.css");
    check("turns sit 30px apart", /\.stream-inner \{[^}]*gap: 30px/.test(wsCss));
    check("the date divider is the app's second pill",
        /\.stream-date > span \{[^}]*border-radius: var\(--r-pill\)/.test(wsCss) &&
        /\.stream-date > span \{[^}]*background: var\(--surface\)/.test(wsCss) &&
        !/\.stream-date[^{]*\{[^}]*border:/.test(wsCss));
    check("avatars are 36px circles that centre on the bubble row",
        /\.turn-avatar \{\s*width: 36px;\s*height: 36px;/.test(wsCss) &&
        /\.turn-ai \.turn-avatar\s*\{ grid-column: 1; grid-row: 2; align-self: center/.test(wsCss));
    check("the assistant avatar is the app's own shield on --surface-2",
        /\.turn-avatar-ai \{[^}]*background: var\(--surface-2\)[^}]*color: var\(--accent\)/.test(wsCss));
    check("ground < assistant bubble < your bubble",
        /\.bubble-ai \{\s*background: var\(--surface-2\)/.test(wsCss) &&
        /\.bubble-user \{\s*background: var\(--surface-3\)/.test(wsCss));
    check("bubbles cap at a 62% measure and keep the 10px radius",
        /\.turn-body \{[^}]*max-width: 62%/.test(wsCss) &&
        /\.bubble \{[^}]*border-radius: var\(--r-lg\)/.test(wsCss));
    check("the action rows brighten from muted to text with no fill",
        /\.msg-actions \{[^}]*gap: 14px/.test(wsCss) &&
        /\.msg-actions \.icon-btn \{[^}]*background: transparent;[^}]*color: var\(--text-muted\)/.test(wsCss) &&
        /\.msg-actions \.icon-btn:hover:not\(:disabled\)[\s\S]{0,80}color: var\(--text\)/.test(wsCss));

    console.log("\nComposer");
    check("the send control is a ghost circle outside the box",
        /\.composer-send \{[\s\S]*?background: transparent;[\s\S]*?border: 1px solid var\(--border\);/.test(wsCss) &&
        !/\.composer-send \{[^}]*--accent/.test(wsCss));
    check("the send control keeps a 44px target and a dimmed disabled state",
        /\.composer-send \{[^}]*width: 44px;[\s\S]*?height: 44px;/.test(wsCss) &&
        /\.composer-send:disabled \{[^}]*opacity: 0\.45[\s\S]*?cursor: not-allowed/.test(wsCss));
    check("the shortcut chip sits inside the box and hides on narrow screens",
        /\.composer-chip \{[^}]*align-self: flex-end/.test(wsCss) &&
        /@media \(max-width: 640px\) \{\s*\.composer-chip \{ display: none; \}/.test(wsCss));
    check("the composer box keeps the 1px --border and the focus recipe",
        /\.composer-box \{[^}]*background: var\(--surface-2\);[^}]*border: 1px solid var\(--border\);/.test(wsCss) &&
        /\.composer-box:focus-within \{[^}]*outline: 2px solid var\(--accent\)/.test(wsCss));
    check("no attachment affordance ships anywhere",
        !/paperclip/i.test(wsHtml + wsCss) && !/data-icon="clip|data-icon="attach|type="file"/.test(wsHtml));
    check("the old mono key strap is gone", !/Enter · Shift\+Enter/.test(wsHtml));
}

async function testChatInBrowser() {
    console.log("\nChat skin in the browser");
    const answer = (key) => {
        if (key === "SETTINGS") return { check1: true, check2: true, check3: true, API_KEY_MASK: "sk-***" };
        if (key === "CHATS") return { chats: [{ id: 7, title: "Kept chat" }] };
        if (key === "CHATS_OPEN") return { chat: { id: 7, title: "Kept chat", messages: [
            { id: 21, prompt: "First question", answer: "First answer", created_at: "2026-11-17T22:05:00Z" },
            { id: 22, prompt: "Second question", answer: "Second answer", created_at: "2026-11-17T23:30:00Z" },
            { id: 23, prompt: "Third question", answer: "Third answer", created_at: "2026-11-18T09:00:00Z" }
        ] } };
        return {};
    };
    const p = screenFixture("workspace", answer);
    await tick();
    const { $, win } = p;
    const doc = win.document;

    const dividers = [...doc.querySelectorAll(".stream-date")];
    check("one date divider per calendar day, in order",
        dividers.length === 2 &&
        dividers[0].textContent.trim() === "17 Nov 2026" &&
        dividers[1].textContent.trim() === "18 Nov 2026",
        dividers.map((d) => d.textContent.trim()).join(" | "));

    const firstMsg = doc.querySelector('.msg[data-id="21"]');
    check("each message opens with a speaker head and time only",
        firstMsg.querySelector(".msg-head .who").textContent === "You" &&
        firstMsg.querySelector(".msg-head .msg-time").textContent === "22:05 UTC" &&
        !/Nov|2026/.test(firstMsg.querySelector(".msg-head").textContent));

    const userTurn = firstMsg.querySelector(".turn-user");
    const aiTurn = firstMsg.querySelector(".turn-ai");
    check("your avatar carries your initials and sits on the right",
        userTurn.querySelector(".turn-avatar-user").textContent === "SE" &&
        !!userTurn.querySelector(".bubble-user"));
    check("the assistant's face is an inline shield, not a vendor mark",
        !!aiTurn.querySelector(".turn-avatar-ai .icon path") &&
        !/openai|knot|assistant-logo/i.test(aiTurn.innerHTML));
    check("the assistant head names CyberSyn and the reply keeps its bubble",
        aiTurn.querySelector(".msg-head .who").textContent === "CyberSyn" &&
        !!aiTurn.querySelector(".bubble-ai"));

    /* The overflow menu opens, closes on Escape and never invents an action. */
    const menu = $("#chat-menu");
    const trigger = $("#btn-chat-menu");
    trigger.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    check("the overflow menu opens from its trigger",
        menu.hidden === false && trigger.getAttribute("aria-expanded") === "true");
    check("the menu holds exactly two items",
        menu.querySelectorAll(".menu-item").length === 2);
    menu.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    check("Escape closes the menu and returns focus",
        menu.hidden === true && doc.activeElement === trigger);

    let prompted = null, confirmed = null;
    win.Shell.prompt = (options) => { prompted = options; return Promise.resolve(null); };
    win.Shell.confirm = (options) => { confirmed = options; return Promise.resolve(false); };
    trigger.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    $("#menu-rename-chat").dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    await tick();
    check("the menu's rename runs the same rename flow",
        prompted && prompted.title === "Rename this chat");
    check("picking an item closes the menu", menu.hidden === true);

    trigger.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    $("#menu-delete-chat").dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    await tick();
    check("the menu's delete runs the same confirm flow",
        confirmed && confirmed.title === "Delete this chat?");

    /* A click elsewhere closes it. */
    trigger.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    doc.body.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    check("a click outside closes the menu", menu.hidden === true);

    win.close();

    /* The send control swaps to a spinner while the request is open. */
    let release = null;
    const slow = screenFixture("workspace", (key) => {
        if (key === "SETTINGS") return { check1: true, check2: true, check3: true, API_KEY_MASK: "sk-***" };
        if (key === "CHATS") return { chats: [] };
        if (key === "CHAT") {
            return new Promise((resolve) => {
                release = () => resolve({ chat_id: 1, message_id: 5, reply_message: "hi" });
            });
        }
        return {};
    });
    await tick();
    slow.$("#prompt-input").value = "A question";
    slow.$("#form-send").dispatchEvent(new slow.win.Event("submit", { cancelable: true, bubbles: true }));
    await tick();
    check("the send button is disabled and spinning while a reply is pending",
        slow.$("#btn-send").disabled && slow.$("#btn-send").classList.contains("is-loading") &&
        !!slow.$("#btn-send .btn-spinner"));
    if (release) release();
    await tick();
    await tick();
    check("the send button returns to idle afterwards",
        !slow.$("#btn-send").disabled && !slow.$("#btn-send").classList.contains("is-loading"));
    slow.win.close();

    /* Greek: the new strings and the runtime's genitive month. */
    const el = screenFixture("workspace", answer);
    await tick();
    el.win.I18n.set("el");
    await tick();
    const elDoc = el.win.document;
    check("the descriptor line is translated",
        elDoc.querySelector(".topbar-subtitle").textContent === "Μια συζήτηση με το CyberSyn");
    check("the composer placeholder is translated",
        elDoc.querySelector("#prompt-input").placeholder === "Γράψτε ένα μήνυμα…");
    check("the shortcut chip is translated",
        elDoc.querySelector(".composer-chip").textContent === "Shift + Enter για νέα γραμμή");
    check("the Greek divider takes the genitive month",
        elDoc.querySelector(".stream-date").textContent.trim() === "17 Νοεμβρίου 2026",
        elDoc.querySelector(".stream-date").textContent.trim());
    check("chat titles stay untranslated",
        elDoc.querySelector("#active-chat-title").textContent === "Kept chat");
    el.win.close();
}

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
    testDesignOverhaul();
    await testDemoTiles();
    testChatReskin();
    await testChatInBrowser();
    testBrowserBoundaries();
    await testSignedInScreens();
    await testPortal();
    await testScreeningActions();
    await testDiscovery();

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

function screenFixture(page, answer, opts = {}) {
    const html = template(page + ".html").match(/\{% block body %\}([\s\S]*?)\{% endblock %\}/)[1]
        .replace(/\{% include "([^"]+\.html)" %\}/g, (_, name) => template(name))
        .replace("{% include sidebar_extra %}", page === "workspace" ? partial("chat_list.html") : "")
        .replace(/\{#[\s\S]*?#\}|\{%[\s\S]*?%\}/g, "");
    const virtualConsole = new VirtualConsole();
    const navigations = [];
    virtualConsole.on("jsdomError", (error) => {
        if (/^Not implemented: navigation/.test(error.message)) navigations.push(error.message);
        else check(`${page} runs without browser errors`, false, error.message);
    });
    const win = new JSDOM(html, { url: BASE + "/" + (page === "index" ? "" : page.replaceAll("_", "-")) + (opts.query || ""),
        runScripts: "outside-only", pretendToBeVisual: true, virtualConsole }).window;
    const routes = ROUTES;
    win.document.body.dataset.routes = JSON.stringify(routes);
    const posted = [], approvals = [], messages = [];
    if (opts.narrow) win.matchMedia = (query) => ({ matches: query.includes("max-width") });
    /* A real frame is still queued when these one-off windows close, and jsdom
       throws inside its own frame runner once the document is gone. */
    win.requestAnimationFrame = (fn) => setTimeout(fn, 0);
    win.HTMLElement.prototype.scrollTo = function () {};
    win.HTMLElement.prototype.scrollIntoView = function () { this.dataset.scrolled = "1"; };
    win.fetch = (url, opts) => {
        const key = Object.keys(routes).find((k) => routes[k] === url);
        const body = JSON.parse(opts.body);
        posted.push({ key, body });
        return Promise.resolve(answer(key, body)).then((data) => {
            const status = (data && data.httpStatus) || 200;
            return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(data) };
        });
    };
    for (const f of ["dom", "stages", "icons", "i18n", "markdown", "api"]) win.eval(read("core/" + f + ".js"));
    if (opts.member !== false) win.Api.Session.setMember({ parentId: 2, employeeId: opts.employeeId || 5, username: "Settings" });
    win.Loading = { toast: (text) => messages.push(text), withButton: (_, task) => Promise.resolve().then(task) };
    if (opts.realShell) win.eval(read("core/shell.js"));
    else win.Shell = { guard: () => true, withAdmin: (options) => {
        approvals.push(options); return Promise.resolve("test-grant-" + approvals.length);
    } };
    win.eval(read((page === "index" ? "auth" : page) + ".js"));
    const $ = (selector) => win.document.querySelector(selector);
    return { win, posted, approvals, messages, navigations, $,
        submit: (selector) => $(selector).dispatchEvent(new win.Event("submit", { cancelable: true, bubbles: true })),
        change: (selector, value) => {
            $(selector).value = value;
            $(selector).dispatchEvent(new win.Event("change", { bubbles: true }));
        } };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const DENIED = { httpStatus: 401, success: false };
const VERIFIED = { success: true, Parent_id: "72", username: "Settings" };

async function testPortal() {
    console.log("\nIndependent sign-in");
    const p = screenFixture("index", (key, body) => {
        if (key === "ADMIN_SESSION") return DENIED;
        if (key === "ADMIN_LOGIN") return VERIFIED;
        if (key === "EMPLOYEE_LOGIN") return body.workspace ? { Parent_id: "72", Employee_id: "4", username: "member_fixture" } : {
            httpStatus: 400, error: true, error_message: "Enter your workspace name to sign in."
        };
        return {};
    }, { member: false, realShell: true });
    await tick();
    const { $, win, posted } = p;
    const active = (type) => $("#tab-" + type).getAttribute("aria-selected") === "true" &&
        $("#tab-" + type).tabIndex === 0 && !$("#" + $("#tab-" + type).getAttribute("aria-controls")).hidden;
    const press = (type, key) => $("#tab-" + type).dispatchEvent(new win.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
    check("the portal starts with an independent member form", active("member") && $("#admin-step").hidden &&
        $("#employee-workspace").getAttribute("aria-describedby") === "workspace-hint");
    press("member", "ArrowRight");
    check("Right moves focus and selection to Administrator", active("admin") && win.document.activeElement === $("#tab-admin") && $("#employee-card").hidden);
    press("admin", "ArrowLeft");
    check("Left switches back to Team member", active("member") && win.document.activeElement === $("#tab-member"));
    press("member", "End");
    check("End and Home move across the tab group", active("admin") && (press("admin", "Home"), active("member")));
    $("#employee-username").value = "member_fixture";
    $("#employee-password").value = "  fixture member pass  ";
    p.submit("#employee-login-form");
    await tick();
    const independent = posted.find((r) => r.key === "EMPLOYEE_LOGIN").body;
    check("member form submits without admin authorization or an empty workspace field",
        JSON.stringify(independent) === JSON.stringify({ username: "member_fixture", password: "  fixture member pass  " }));
    check("an ambiguous workspace explains what to enter", $("#employee-msg").textContent === "Enter your workspace name to sign in.");
    win.I18n.set("el");
    check("translated member tab, hint, placeholder and sign-in error", $("#tab-member").textContent === "Μέλος ομάδας" &&
        /χώρο/.test($("#workspace-hint").textContent) && $("#employee-workspace").placeholder !== "Administrator username" &&
        /Πληκτρολογήστε/.test($("#employee-msg").textContent));
    win.I18n.set("en");
    check("member sign-in copy and input survive a language round-trip", $("#employee-msg").textContent === "Enter your workspace name to sign in." &&
        $("#employee-username").value === "member_fixture" && $("#employee-password").value === "  fixture member pass  ");
    $("#tab-admin").click();
    $("#admin-username").value = " Settings ";
    $("#admin-password").value = "  fixture owner pass  ";
    p.submit("#admin-login-form");
    await tick();
    const login = posted.find((r) => r.key === "ADMIN_LOGIN").body;
    check("separate admin form submits exact password and opens the hub", login.username === "Settings" && login.password === "  fixture owner pass  " &&
        $("#admin-sign-in").hidden && !$("#admin-session-badge").hidden && !$("#admin-password").value);
    check("the hub links to the admin tasks directly", ["/shadow-ai", "/stats", "/team", "/create-member", "/delete-member"].every(
        (href) => $("#admin-session-badge a[href='" + href + "']")));
    $("#btn-switch-member").click();
    check("switching prefills workspace and explains session revocation", active("member") && $("#employee-workspace").value === "Settings" &&
        !$("#member-ends-admin").hidden && win.document.activeElement === $("#employee-username"));
    p.submit("#employee-login-form");
    await tick();
    check("member login sends the workspace name, accepts the returned workspace ID and drops admin hints",
        posted.filter((r) => r.key === "EMPLOYEE_LOGIN").at(-1).body.workspace === "Settings" &&
        win.Api.Session.getMember().parentId === "72" && !win.Api.Session.getAdmin() && $("#member-ends-admin").hidden && p.navigations.length === 1);
    check("no sign-in secrets are retained in browser storage", !/fixture.*pass|_token|session_token/.test(JSON.stringify(win.localStorage) + JSON.stringify(win.sessionStorage)));
    win.close();

    const restored = screenFixture("index", (key) => key === "ADMIN_SESSION" ? VERIFIED : {}, { member: false, realShell: true, query: "?tab=admin" });
    await tick();
    restored.win.I18n.set("el");
    check("a server-verified cookie restores the hub without local hints and preserves the administrator name",
        !restored.$("#admin-step").hidden && !restored.$("#admin-session-badge").hidden && restored.$("#active-admin-label").textContent === "Settings");
    restored.$("#btn-admin-logout").click();
    await tick();
    check("hub sign-out revokes the cookie and restores the admin form", restored.posted.some((r) => r.key === "ADMIN_LOGOUT") &&
        !restored.win.Api.Session.getAdmin() && !restored.$("#admin-sign-in").hidden && restored.$("#admin-session-badge").hidden);
    restored.win.close();

    const explicit = screenFixture("index", (key) => key === "ADMIN_SESSION" ? VERIFIED : {}, { member: false, realShell: true, query: "?tab=member" });
    await tick();
    check("an explicit member tab is not overridden by a restored admin session", !explicit.$("#employee-card").hidden &&
        !explicit.$("#member-ends-admin").hidden);
    explicit.win.close();
}

async function testScreeningActions() {
    console.log("\nWorkspace policy actions");
    const old = { id: "fixture-message", prompt: "Synthetic stored prompt", answer: "Original reply", created_at: "2026-11-18T10:00:00Z" };
    const evidence = "<fixture@example.example>";
    const warn = { warned: true, action: "warn", warn_info: { stage: "check1", will_redact: true, matches: [
        { stage: "check1", cause: "EMAIL", main_cause: "legacy cause", line: 2, snippet: evidence },
        { stage: "check2", main_cause: "Synthetic match", line: 3 }, { line: 4 }
    ] } };
    const receipt = { count: 1, categories: ["EMAIL"], placeholders: ["[EMAIL_1]"], restored: true };
    const masked = "Settings [EMAIL_1]";
    const redacted = { redacted: true, action: "redact", redacted_prompt: masked, redaction_info: receipt,
        reply_message: "Local reply " + evidence, chat_id: 1, message_id: "fixture-new" };
    const history = (id) => ({ id, prompt: masked, answer: "Unrestored [EMAIL_1]", redacted: true,
        redaction_info: { ...receipt, restored: false }, created_at: old.created_at });
    let thread = [old];
    let regenBlocked = false;
    const p = screenFixture("workspace", (key, body) => {
        if (key === "SETTINGS") return { action_check1: "warn", action_check2: "redact", action_check3: "block", action_code: "warn" };
        if (key === "CHATS") return { chats: [{ id: 1, title: "Settings" }] };
        if (key === "CHATS_OPEN") return { chat: { id: 1, title: "Settings", messages: structuredClone(thread) } };
        if (key === "CHAT") {
            if (!body.confirm_warn) return warn;
            thread = [old, history(redacted.message_id)];
            return redacted;
        }
        if (key === "CHAT_REGENERATE") {
            if (regenBlocked) return { blocked: true, block_info: { stage: "policy", main_cause: "UNAPPROVED_AI_TOOL", tool_name: "<Fixture AI>" } };
            if (!body.confirm_warn) return warn;
            thread = [history(body.message_id), history(redacted.message_id)];
            return { ...redacted, messages: structuredClone(thread) };
        }
        return {};
    });
    const { $, win, posted } = p;
    const submitDraft = () => {
        $("#prompt-input").value = "Review " + evidence;
        p.submit("#form-send");
        return tick();
    };
    const regen = () => $(".msg-actions-ai button[title='Generate a different answer']").click();
    await tick();
    check("workspace counts all four non-Allow actions", $("#checks-summary").textContent === "All checks on");
    await submitDraft();
    check("warning lists causes in order, including the fallback, and escapes evidence",
        [...win.document.querySelectorAll(".bubble-warned .blocked-match .badge")].map((b) => b.textContent).join("|") === "EMAIL|Synthetic match|match" &&
        $(".bubble-warned code").textContent === evidence && !$(".bubble-warned code fixture") && /will be redacted/.test($(".bubble-warned").textContent));
    win.I18n.set("el");
    check("warning buttons and aria label translate without changing evidence", $(".warn-send").textContent !== "Send anyway" &&
        $(".bubble-warned").getAttribute("aria-label") !== "Message paused for review" && $(".bubble-warned code").textContent === evidence);
    win.I18n.set("en");
    $(".warn-edit").click();
    check("warning edit returns the original draft to the focused composer without sending again", $("#prompt-input").value === "Review " + evidence &&
        win.document.activeElement === $("#prompt-input") && posted.filter((r) => r.key === "CHAT").length === 1);
    await submitDraft();
    $(".warn-send").click();
    await tick();
    const confirmed = posted.filter((r) => r.key === "CHAT").at(-1).body;
    check("warning confirmation repeats the same draft with a boolean confirmation and no administrator grant", confirmed.confirm_warn === true &&
        confirmed.prompt === "Review " + evidence && !confirmed.bypass && !posted.some((r) => r.key === "ADMIN_APPROVE"));
    const details = $(".redaction-receipt");
    details.open = true;
    check("the live exchange shows sanitized text and an expandable redaction receipt", details.querySelector(".redaction-preview").textContent === masked &&
        details.querySelector("summary").textContent.includes("Redacted 1") && $(".msg[data-id='fixture-new'] .bubble-ai").textContent.includes(evidence));
    win.I18n.set("el");
    check("receipt copy translates but its token and sanitized prompt do not", !details.querySelector("summary").textContent.includes("Redacted") &&
        details.querySelector(".redaction-tokens").textContent === "[EMAIL_1]" && details.querySelector(".redaction-preview").textContent === masked);
    win.I18n.set("en");
    regen();
    await tick();
    check("a warned regeneration preserves the original answer and other messages", !!$(".bubble-warned") &&
        $(".msg[data-id='fixture-message'] .bubble-ai").textContent === "Original reply" && !!$(".msg[data-id='fixture-new'] .bubble-ai"));
    $(".warn-send").click();
    await tick();
    check("confirmation uses regeneration, updates only its live answer and retains unrestored history for the others", posted.some((r) =>
        r.key === "CHAT_REGENERATE" && r.body.confirm_warn === true && r.body.message_id === old.id) &&
        $(".msg[data-id='fixture-message'] .bubble-ai").textContent.includes(evidence) &&
        $(".msg[data-id='fixture-new'] .bubble-ai").textContent.includes("Unrestored [EMAIL_1]"));
    regenBlocked = true;
    regen();
    await tick();
    check("a blocked regeneration keeps the thread and names the destination safely", $(".bubble-blocked .blocked-why strong").textContent === "<Fixture AI>" &&
        win.document.querySelectorAll(".msg[data-id]").length === 2);
    win.close();
}

async function testDiscovery() {
    console.log("\nShadow AI and administrator entry");
    const base = { tool_key: "fixture_tool", name: "Settings", vendor: "Fixture Vendor", category: "gateway", domains: ["assistant.example"],
        provider_key: "fixture", status: "unapproved", default_status: "unapproved", custom: false, risk_score: 80, risk_level: "high",
        hosting: "On-premise", gdpr_summary: "This entry covers loopback inference only; verify that cloud features are disabled.",
        training_policy: "opt_out_only", note: "Settings" };
    let inventory = [base];
    let events = [];
    const sample = { host: "assistant.example", observed_at: "2026-11-18T09:00:00Z", actor: "192.0.2.55", team: "Settings",
        tool_key: base.tool_key, tool_name: base.name, status: base.status, risk_level: "high", risk_score: 80, method: "POST", bytes_sent: 8000,
        data_signal: "client_data" };
    const response = () => ({ inventory, events, teams: events.length ? ["Settings"] : [], summary: { total_events: events.length },
        by_team: events.length ? [{ team: "Settings", total_events: 1, unapproved_events: 1, sensitive_data_to_unapproved: 1,
            client_data_to_unapproved: 1, unapproved_tools: [base.name] }] : [] });
    const admin = screenFixture("shadow_ai", (key, body) => {
        if (key === "ADMIN_SESSION") return VERIFIED;
        if (key === "SHADOW_AI") return response();
        if (key === "SHADOW_AI_IMPORT") {
            events = body.clear ? [] : [sample];
            return { lines_scanned: 2, ai_events_added: events.length, non_ai_ignored: 1 };
        }
        if (key === "SHADOW_AI_POLICY") {
            if (body.method === "add") inventory = [...inventory, { ...base, tool_key: "custom:" + body.domain, name: body.name,
                domains: [body.domain], custom: true }];
            else if (body.method === "remove") inventory = inventory.filter((t) => t.tool_key !== body.tool_key);
            else inventory = inventory.map((t) => t.tool_key === body.tool_key ? { ...t, note: body.note, status: body.status } : t);
            return { inventory };
        }
        return {};
    }, { realShell: true, narrow: true });
    await tick();
    const { $, win, posted } = admin;
    check("primary admin page verifies the cookie, scopes reads to it and skips step-up even with stale member metadata",
        posted[0].key === "ADMIN_SESSION" && Object.keys(posted[0].body).length === 0 && posted[1].key === "SHADOW_AI" &&
        posted[1].body.Parent_id === "72" && !("Employee_id" in posted[1].body) && !$(".overlay"));
    check("primary navigation hides member-only items and names the administrator", $("[data-sidebar-role]").textContent === "Administrator" &&
        [...win.document.querySelectorAll("[data-member-only]")].every((link) => link.hidden) && !$("[data-admin-hub]").hidden);
    $("[data-action='toggle-sidebar']").click();
    check("Shadow AI has a working mobile navigation drawer", $("[data-sidebar]").classList.contains("is-open") &&
        $("[data-nav='/shadow-ai']").getAttribute("aria-current") === "page");
    $("#shadow-sample").click();
    await tick();
    check("sample import uses the primary cookie and refreshes counts and the event list", posted.some((r) => r.key === "SHADOW_AI_IMPORT" &&
        r.body.sample === true && r.body.Parent_id === "72" && !("admin_token" in r.body)) &&
        $("[data-summary='total_events']").textContent === "1" && $("#shadow-events").textContent.includes("192.0.2.55"));
    admin.change("#shadow-days", "30");
    admin.change("#shadow-status", "unapproved");
    admin.change("#shadow-team", "Settings");
    admin.change("#shadow-signal", "client_data");
    await tick();
    const filter = posted.filter((r) => r.key === "SHADOW_AI").at(-1).body;
    check("all four filters travel with the verified workspace", JSON.stringify(filter) === JSON.stringify({
        Parent_id: "72", days: 30, status: "unapproved", team: "Settings", data_signal: "client_data"
    }));
    const toolName = "<fixture-ai>";
    $("#shadow-tool-name").value = toolName;
    $("#shadow-domain").value = "second-assistant.example";
    admin.submit("#shadow-add-tool");
    await tick();
    const custom = () => $("[data-tool='custom:second-assistant.example']");
    check("custom tools can be added and their names are literal text", custom().querySelector("summary strong").textContent === toolName &&
        !custom().querySelector("fixture-ai") && !$("#shadow-domain").value);
    const tool = () => $("[data-tool='fixture_tool']");
    tool().open = true;
    tool().querySelector(".shadow-tool-note").value = "Settings";
    tool().querySelector(".shadow-tool-status").value = "restricted";
    tool().querySelector("button").click();
    await tick();
    check("policy save refreshes the status, keeps the note and leaves the facts expanded", tool().open &&
        tool().querySelector("summary .badge-warn").textContent === "Restricted" && tool().querySelector(".shadow-tool-note").value === "Settings");
    const statusName = $("#shadow-status option:checked").textContent;
    win.I18n.set("el");
    check("Shadow AI translates filter and result chrome but preserves team, actor, host, tool and note data", $("#shadow-status option:checked").textContent !== statusName &&
        /Γραμμές που ελέγχθηκαν/.test($("#shadow-import-result").textContent) && $("#shadow-team option:checked").textContent === "Settings" &&
        $("#shadow-events .mono").textContent === "assistant.example" && $("#shadow-events").textContent.includes("192.0.2.55") &&
        tool().querySelector("summary strong").textContent === "Settings" && tool().querySelector(".shadow-tool-note").value === "Settings");
    win.I18n.set("en");
    check("Shadow AI English copy and filter values round-trip", $("#shadow-status option:checked").textContent === statusName &&
        $("#shadow-signal").value === "client_data" && $("#shadow-import-result").textContent === "Scanned 2 lines · 1 AI event · 1 non-AI ignored");
    const log = "192.0.2.56 POST assistant.example 5000";
    Object.defineProperty($("#shadow-file"), "files", { value: [new win.File([log], "synthetic.log", { type: "text/plain" })] });
    $("#shadow-file").dispatchEvent(new win.Event("change", { bubbles: true }));
    for (let i = 0; i < 20 && !$("#shadow-content").value; i++) await tick();
    check("local file picker populates the paste field without uploading", $("#shadow-content").value === log &&
        posted.filter((r) => r.key === "SHADOW_AI_IMPORT").length === 1);
    $("#shadow-import").click();
    await tick();
    check("import posts the selected text once and clears the field on success", posted.some((r) => r.key === "SHADOW_AI_IMPORT" &&
        r.body.content === log) && $("#shadow-content").value === "");
    custom().querySelector(".btn-danger").click();
    $("[data-confirm-accept]").click();
    await tick();
    check("removing a custom service asks for confirmation then refreshes inventory", !custom() && posted.some((r) =>
        r.key === "SHADOW_AI_POLICY" && r.body.method === "remove"));
    $("#shadow-clear").click();
    $("[data-confirm-cancel]").click();
    await tick();
    check("declining clear sends nothing", !posted.some((r) => r.body.clear));
    $("#shadow-clear").click();
    $("[data-confirm-accept]").click();
    await tick();
    check("confirmed clear resets discovery but not policy", $("#shadow-import-result").textContent === "Discovery logs cleared." &&
        $("[data-summary='total_events']").textContent === "0" && !!tool() && $("#shadow-team").value === "");
    win.close();

    const approve = (page) => {
        page.$("#admin-gate-username").value = "fixture_admin";
        page.$("#admin-gate-password").value = "  fixture approval pass  ";
        page.$("[data-gate-unlock]").click();
    };
    const member = screenFixture("shadow_ai", (key, body) => {
        if (key === "ADMIN_SESSION") return DENIED;
        if (key === "ADMIN_APPROVE") return { success: true, Parent_id: "2", username: body.username,
            ...(body.scope === "once" && { admin_token: "once-shadow-fixture" }) };
        if (key === "SHADOW_AI") return response();
        if (key === "SHADOW_AI_IMPORT") return { lines_scanned: 25, ai_events_added: 22, non_ai_ignored: 3 };
        return {};
    }, { realShell: true });
    await tick();
    check("member entry prompts for read-only unlock before loading any discovery data", !!member.$(".overlay") && member.posted.length === 1);
    approve(member);
    await tick();
    check("page grant loads Shadow AI for the member's own workspace and exposes Lock now", member.posted[1].body.scope === "page" &&
        member.posted[2].body.Parent_id === 2 && !member.$("[data-admin-lock]").classList.contains("hidden"));
    member.$("#shadow-sample").click();
    await tick();
    check("member imports still require a fresh password after page unlock", !!member.$(".overlay") && !member.posted.some((r) => r.key === "SHADOW_AI_IMPORT"));
    approve(member);
    await tick();
    const write = member.posted.find((r) => r.key === "SHADOW_AI_IMPORT");
    check("fresh approval is used only in the scoped import request and never stored", write.body.admin_token === "once-shadow-fixture" &&
        write.body.Parent_id === 2 && member.posted.some((r) => r.body.scope === "once") &&
        !/once-shadow-fixture/.test(JSON.stringify(member.win.localStorage) + JSON.stringify(member.win.sessionStorage)));
    member.win.close();

    for (const page of ["stats", "team"]) {
        const direct = screenFixture(page, (key) => key === "ADMIN_SESSION" ? VERIFIED : {
            admin: "Settings", stats: { members: 1 }, members: [{ id: 4, username: "Settings", checks_on: 4, model: "Settings" }]
        }, { member: false, realShell: true });
        await tick();
        check(`${page} loads directly from the primary administrator cookie, without a member gate`,
            direct.posted.some((r) => r.key === "TEAM" && r.body.Parent_id === "72") && !direct.$(".overlay") &&
            direct.$(".member-meta").textContent.includes("4 of 4 checks on"));
        direct.win.close();
    }
    const anonymous = screenFixture("shadow_ai", () => DENIED, { realShell: true, member: false });
    await tick();
    check("without either session the page redirects without a discovery request or unlock", anonymous.posted.length === 1 &&
        !anonymous.$(".overlay") && anonymous.navigations.length === 1);
    anonymous.win.close();
}

async function testSignedInScreens() {
    console.log("\nSigned-in screens");
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
    const records = { 5: "warn", 6: "allow" };
    const answer = (key, body) => {
        if (key === "SETTINGS") {
            if (body.action_code) records[body.Employee_id] = body.action_code;
            return {
                action_check1: body.action_check1 || "block", action_check2: body.action_check2 || "allow", action_check3: "warn",
                action_code: records[body.Employee_id], restore_redactions: !!body.restore_redactions, MODEL_NAME: "Settings",
                API_KEY_MASK: body.CLEAR_API_KEY ? "" : "****1234", PROVIDER: "openai", API_BASE: base
            };
        }
        if (key === "PROVIDERS") return { providers: ["auto", "openai", "custom"].map((k) => ({ key: k, label: k })) };
        if (key === "MODELS") return { models: ["Settings"], provider: body.provider };
        return {};
    };
    const first = screenFixture("settings", answer), other = screenFixture("settings", answer, { employeeId: 6 });
    await tick();
    check("Settings renders each member's own saved actions", first.$("#setting-block-code").value === "warn" && other.$("#setting-block-code").value === "allow");
    check("prompt injection has no redact option; restoration is off by default", !first.$("#setting-check3 option[value='redact']") &&
        !first.$("#setting-restore-redactions").checked);
    check("saved named-provider base path survives load and automatic discovery", first.$("#setting-base").value === base &&
        first.posted.find((r) => r.key === "MODELS").body.API_BASE === base);
    first.win.I18n.set("el");
    check("model names are data, not interface copy", first.$("#setting-model option:checked").textContent === "Settings");
    check("settings action labels translate without modifying action values", first.$("#setting-block-code option:checked").textContent !== "Warn" &&
        first.$("#setting-block-code").value === "warn");
    first.win.I18n.set("en");
    first.change("#setting-check1", "redact");
    first.change("#setting-block-code", "allow");
    first.$("#setting-restore-redactions").checked = true;
    first.$("#also-default").checked = true;
    first.$("#btn-save-checks").click();
    await tick();
    const policy = first.posted.find((r) => r.key === "SETTINGS" && "action_code" in r.body).body;
    check("four actions and local restoration require fresh approval, scoped to this member with an opt-in default copy", policy.Employee_id === 5 &&
        policy.action_code === "allow" && policy.action_check1 === "redact" && policy.action_check2 === "allow" && policy.action_check3 === "warn" &&
        policy.restore_redactions === true && policy.also_default === true && policy.admin_token === "test-grant-1" && first.approvals[0].fresh &&
        !first.$("#also-default").checked && !("block_code" in policy));
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

/* --------------------------------------------------------------------------
   Design overhaul — one type family, compact page headers, flat settings
   screens, and the four check-gated demo tiles on an empty conversation.
   -------------------------------------------------------------------------- */

const sheet = (name) => fs.readFileSync(path.join(ROOT, "src", "static", "css", name), "utf8");

function testDesignOverhaul() {
    console.log("\nOne type family");
    const base = sheet("base.css");
    check("no serif display family is left in the design tokens",
        !/Instrument Serif|Noto Serif Display|Georgia|Times New Roman/.test(base));
    check("--font-display resolves to Inter", /--font-display:\s*"Inter"/.test(base));
    check("headings carry the -0.02em display tracking",
        /--tracking-display:\s*-0\.02em/.test(base) &&
        /letter-spacing:\s*var\(--tracking-display\)/.test(base));
    check("headings are set in a semibold weight, not a 400 italic-style serif",
        /h1, \.display \{[\s\S]*?font-weight:\s*600/.test(base));
    check("JetBrains Mono stays reserved for code and tabular numbers",
        /--font-mono:\s*"JetBrains Mono"/.test(base) && /\.mono \{[\s\S]*?font-variant-numeric:\s*tabular-nums/.test(base));
    const fontFiles = fs.readdirSync(path.join(ROOT, "src", "static", "fonts"));
    check("unused serif font files are pruned",
        !fontFiles.some((f) => /instrument|noto-serif/i.test(f)), fontFiles.join(","));
    for (const name of ["auth.css", "workspace.css", "components.css", "page.css", "help.css"]) {
        check(`${name} asks for no serif family`,
            !/Instrument Serif|Noto Serif Display|Georgia/.test(sheet(name)));
    }
    check("the bundled licence no longer credits the serif faces",
        !/Instrument Serif|Noto Serif Display/.test(
            fs.readFileSync(path.join(ROOT, "src", "static", "fonts", "OFL.txt"), "utf8")));

    console.log("\nCompact page headers");
    const HEADER_PAGES = ["settings", "profile", "help", "stats", "team", "index", "auth_page"];
    for (const page of HEADER_PAGES) {
        const html = template(page + ".html");
        check(`${page} has no eyebrow line`, !/class="eyebrow"/.test(html));
        check(`${page} has no muted one-line lead`, !/<p class="dim">/.test(html));
        check(`${page} still names itself with an h1`, /<h1\b/.test(html));
    }
    const indexHtml = template("index.html");
    check("the sign-in screen has no marketing split pane",
        !/class="auth-brand"/.test(indexHtml) && !/auth-points/.test(indexHtml) &&
        !/auth-progress/.test(indexHtml) && !/Self-hosted AI security gateway/.test(indexHtml));
    check("the sign-in screen has no step eyebrows or privacy footnote",
        !/Step 1 of 2|Step 2 of 2/.test(indexHtml) && !/auth-footnote/.test(indexHtml));
    check("the account pages match the single-surface layout",
        !/class="auth-brand"/.test(template("auth_page.html")) &&
        !/auth-progress|auth-eyebrow|auth-footnote/.test(template("auth_page.html")));
    check("no muted lead line repeats the sign-in or account titles",
        !/auth-lead/.test(indexHtml) && !/auth-lead/.test(template("auth_page.html")) &&
        ["create_admin", "create_member", "delete_admin", "delete_member"]
            .every((page) => !/set lead|auth-lead/.test(template(page + ".html"))));

    console.log("\nFlat settings screens");
    for (const page of ["settings", "profile", "help"]) {
        const html = template(page + ".html");
        check(`${page} drops the stacked card containers`, !/class="card|card-title/.test(html));
        check(`${page} is built from flat sections`, /class="section"/.test(html));
    }
    check("help.css no longer boxes its rule list", !/\.check-card \{\s*padding/.test(sheet("help.css")));
    const pageCss = sheet("page.css");
    check("a flat section is a labelled two-column block with a hairline",
        /\.section \{[^}]*grid-template-columns:[^}]*\}/.test(pageCss) &&
        /\.section \{[^}]*border-top:\s*1px solid var\(--border-soft\)/.test(pageCss));
    check("sections stack cleanly on narrow viewports",
        /@media \(max-width: 760px\)[\s\S]*?\.section \{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/.test(pageCss));
    check("the page label sits in a left column on desktop",
        /\.section-label h2[\s\S]*?font-weight:\s*600/.test(pageCss));

    console.log("\nChat measure and demo tiles");
    const wsCss = sheet("workspace.css");
    check("the chat stream and composer widen to a 940px measure",
        /#chat-stream \.stream-inner \{ max-width: 940px/.test(wsCss) &&
        /\.composer-inner \{\s*max-width: 940px/.test(wsCss));
    check("vertical rhythm is tighter than the old 820px sheet",
        /\.stream \{[^}]*padding: 18px 0 12px/.test(wsCss) &&
        /\.bubble \{\s*padding: 10px 14px/.test(wsCss));
    check("demo tiles form a 2x2 grid", /\.demo-grid \{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/.test(wsCss));
    check("a tile for a switched-off check is faded and inert",
        /\.demo-tile:disabled[\s\S]*?opacity:\s*0\.42[\s\S]*?pointer-events:\s*none/.test(wsCss));
    const wsHtml = template("workspace.html");
    check("four demo tiles ship in the template", (wsHtml.match(/data-starter/g) || []).length === 4);
    check("tiles 2-4 each name the check they trip",
        ["check1", "check2", "check3"].every((rule) => wsHtml.includes(`data-check="${rule}"`)));
    check("the trust line is the only thing under the composer",
        /class="composer-trust">Checked on this computer before anything reaches the AI\./.test(wsHtml) &&
        !/composer-foot|Enter · Shift\+Enter/.test(wsHtml));
    check("the coaching prompt and starter caption are gone",
        !/What are we working on today|Pick a starter|first-run-title|starter-chip/.test(wsHtml));
    check("the welcome copy no longer explains the checks twice",
        !/Every message is checked on this computer through three local checks/.test(wsHtml));
}

async function testDemoTiles() {
    console.log("\nDemo tiles in the browser");
    const p = screenFixture("workspace", (key) => {
        if (key === "SETTINGS") return { check1: false, check2: true, check3: false, API_KEY_MASK: "sk-***" };
        if (key === "CHATS") return { chats: [] };
        return {};
    });
    await tick();
    const { $, win } = p;
    const tiles = () => [...win.document.querySelectorAll(".demo-tile")];

    check("an empty conversation shows four tiles", tiles().length === 4, tiles().length);
    check("the clean prompt is always available",
        !!tiles()[0] && !tiles()[0].disabled && !tiles()[0].hasAttribute("aria-disabled"));
    check("a switched-off check disables its tile completely",
        tiles()[1].disabled && tiles()[1].getAttribute("aria-disabled") === "true" && tiles()[3].disabled);
    check("a check that is still on keeps its tile clickable",
        !tiles()[2].disabled && !tiles()[2].hasAttribute("aria-disabled"));

    tiles()[0].dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    const cleanPrompt = tiles()[0].querySelector(".demo-tile-prompt").textContent.trim();
    check("picking the clean tile fills the composer without sending",
        $("#prompt-input").value === cleanPrompt &&
        win.document.activeElement === $("#prompt-input") &&
        !p.posted.some((r) => r.key === "CHAT"));
    $("#prompt-input").value = "";

    tiles()[1].dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    check("a disabled tile cannot fill the composer", $("#prompt-input").value === "");

    win.I18n.set("el");
    await tick();
    check("the four tiles carry Greek labels and prompts",
        tiles()[0].querySelector(".demo-tile-label").textContent === "Κανονικό αίτημα" &&
        tiles()[1].querySelector(".demo-tile-label").textContent.includes("Προσωπικά δεδομένα") &&
        tiles()[1].querySelector(".demo-tile-prompt").textContent.includes("ΑΦΜ"));
    check("Greek prompts still carry a check-3 trigger",
        /Αγνόησε/.test(tiles()[3].querySelector(".demo-tile-prompt").textContent));
    check("disabled tiles stay disabled through the language switch",
        tiles()[1].disabled && tiles()[3].disabled && !tiles()[2].disabled);
    tiles()[0].dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    check("the Greek prompt is what lands in the composer",
        $("#prompt-input").value === tiles()[0].querySelector(".demo-tile-prompt").textContent.trim());
    win.I18n.set("en");
    await tick();

    $("#btn-new-chat").dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    await tick();
    check("starting a new chat brings the four tiles back", tiles().length === 4);
    win.close();

    /* Tiles can render before SETTINGS answers; the disabled state must catch up. */
    const slow = screenFixture("workspace", (key) => {
        if (key === "SETTINGS") {
            return new Promise((resolve) => setTimeout(
                () => resolve({ check1: true, check2: true, check3: false }), 30));
        }
        if (key === "CHATS") return { chats: [] };
        return {};
    });
    const slowTiles = () => [...slow.win.document.querySelectorAll(".demo-tile")];
    await tick();
    check("tiles render before the settings answer arrives", slowTiles().length === 4);
    check("nothing is disabled until the checks are known", slowTiles().every((t) => !t.disabled));
    await new Promise((resolve) => setTimeout(resolve, 60));
    check("resolved settings disable exactly the tile whose check is off",
        slowTiles()[3].disabled && !slowTiles()[1].disabled && !slowTiles()[2].disabled);
    slow.win.close();

    /* A conversation with messages keeps the stream, not the tiles. */
    const history = screenFixture("workspace", (key) => {
        if (key === "SETTINGS") return { check1: true, check2: true, check3: true };
        if (key === "CHATS") return { chats: [{ id: 1, title: "Kept" }] };
        if (key === "CHATS_OPEN") return { chat: { id: 1, title: "Kept", messages: [
            { id: 1, prompt: "hello", answer: "hi", created_at: "2026-11-18T09:00:00Z" }] } };
        return {};
    });
    await tick();
    check("an existing conversation shows no demo tiles",
        history.win.document.querySelectorAll(".demo-tile").length === 0);
    history.win.close();
}
