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
            finish();
        }, 10);
    }
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
    check("the present-participle form reads naturally",
        /Checking for confidential/.test(Stages.checking("check2")), Stages.checking("check2"));

    const reason = Stages.reason({ stage: "check1", main_cause: "AFM", line: 3 });
    check("a block explains why and where",
        /Greek ID numbers/.test(reason) && /AFM/.test(reason) && /line 3/.test(reason),
        reason);
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

    console.log(`\n${pass} passed, ${fail} failed`);
    process.exit(fail ? 1 : 0);
}
