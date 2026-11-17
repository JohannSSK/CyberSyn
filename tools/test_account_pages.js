#!/usr/bin/env node
/* Creating and deleting an account, on their own pages.

   These actions used to reuse the sign-in boxes, so the same two fields
   meant "sign in", "create" or "delete" depending on which link you had
   clicked last. This loads the real templates and the real account_pages.js
   and drives them, so it checks what a browser actually gets.

       node tools/test_account_pages.js

   Needs jsdom (npm install jsdom). Skipped, not failed, when it is absent:
   a missing dev dependency is not a regression in the app.
*/
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");

let JSDOM = null;
for (const candidate of [
    process.env.CYBERSYN_JSDOM,
    path.join(ROOT, "node_modules", "jsdom"),
    "/tmp/jsdomtest/node_modules/jsdom",
].filter(Boolean)) {
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
const read = (rel) => fs.readFileSync(path.join(ROOT, "src/static/js", rel), "utf8");

/** Render a child template into auth_page.html the way Jinja would. */
function renderTemplate(file) {
    const child = fs.readFileSync(path.join(ROOT, "src/templates", file), "utf8");
    const parent = fs.readFileSync(path.join(ROOT, "src/templates", "auth_page.html"), "utf8");

    // {% set name = "value" %} -- enough of Jinja to fill the variables in.
    const vars = {};
    for (const [, name, value] of
         child.matchAll(/\{%\s*set\s+(\w+)\s*=\s*"([^"]*)"\s*%\}/g)) {
        vars[name] = value;
    }
    const block = child.match(/\{% block form %\}([\s\S]*?)\{% endblock %\}/);
    const merged = parent.replace("{% block form %}{% endblock %}", block ? block[1] : "");

    return merged
        .replace(/\{\{\s*(\w+)\s*\}\}/g, (m, name) => (name in vars ? vars[name] : ""))
        .replace(/\{%[^%]*%\}/g, "");
}

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

function makePage(file, options) {
    const opts = options || {};
    const dom = new JSDOM(
        `<!doctype html><html><body><div id="toast-container"></div>${
            renderTemplate(file)}</body></html>`,
        { url: BASE + (opts.url || "/" + file.replace(".html", "")),
          runScripts: "outside-only" }
    );
    const win = dom.window;
    for (const f of ["core/dom.js", "core/icons.js"]) win.eval(read(f));

    const posted = [];
    win.Api = {
        Session: {
            getAdmin: () => opts.admin || null,
            getAdminToken: () => (opts.admin ? "admin-token" : null),
            setAdmin: () => {},
            clearAll: () => { win.__cleared = true; },
            getMember: () => null, getMemberToken: () => null, ready: () => false,
        },
        post: (p, body) => { posted.push({ path: p, body }); return Promise.resolve({}); },
    };
    win.Loading = {
        toast: () => {},
        withButton: (btn, task) => Promise.resolve().then(task),
    };
    win.Icons = win.Icons || { html: () => "", svg: () => "" };
    win.eval(read("account_pages.js"));

    const doc = win.document;
    return {
        win, doc, posted,
        fill: (id, value) => { doc.querySelector(id).value = value; },
        text: (id) => (doc.querySelector(id) || {}).textContent || "",
        // Let the promise chain settle before asserting.
        click: (id) => new Promise((resolve) => {
            doc.querySelector(id).dispatchEvent(
                new win.MouseEvent("click", { bubbles: true }));
            setTimeout(resolve, 5);
        }),
    };
}

const LOGIN_FIELDS = ["#admin-username", "#admin-password",
                      "#employee-username", "#employee-password"];

/* --------------------------------------------------------------------------
   Creating an administrator
   -------------------------------------------------------------------------- */

async function createAdmin() {
    console.log("\nCreate administrator");
    const page = makePage("create_admin.html");

    check("it has its own username field", !!page.doc.querySelector("#new-admin-username"));
    check("it shares no field with the sign-in page",
        LOGIN_FIELDS.every((id) => !page.doc.querySelector(id)));
    check("it asks for the password twice",
        !!page.doc.querySelector("#new-admin-password") &&
        !!page.doc.querySelector("#new-admin-confirm"));
    check("it states the password rule up front",
        /8 characters/.test(page.text("#admin-password-rule")));
    check("its button is not a sign-in button",
        page.doc.querySelector("#btn-create-admin").textContent.trim() === "Create account");
    check("it offers a way back", page.doc.querySelector('.auth-link[href="/"]') !== null);

    await page.click("#btn-create-admin");
    check("an empty username sends nothing", page.posted.length === 0, page.posted.length);
    check("an empty username is explained", /Choose a username/.test(page.text("#create-admin-msg")),
        page.text("#create-admin-msg"));

    page.fill("#new-admin-username", "boss");
    page.fill("#new-admin-password", "Admin-Pw-123");
    page.fill("#new-admin-confirm", "Admin-Pw-999");
    await page.click("#btn-create-admin");
    check("a mismatch sends nothing", page.posted.length === 0, page.posted.length);
    check("a mismatch is explained", /do not match/.test(page.text("#create-admin-msg")),
        page.text("#create-admin-msg"));

    page.fill("#new-admin-confirm", "Admin-Pw-123");
    await page.click("#btn-create-admin");
    check("a valid form posts once", page.posted.length === 1, page.posted.length);
    check("it posts to /api/admin", page.posted[0] && page.posted[0].path === "/api/admin");
    check("it asks to add", page.posted[0] && page.posted[0].body.method === "add");
    check("it sends the chosen credentials",
        page.posted[0] && page.posted[0].body.username === "boss" &&
        page.posted[0].body.password === "Admin-Pw-123",
        JSON.stringify(page.posted[0] && page.posted[0].body));
}

/* --------------------------------------------------------------------------
   Deleting an administrator
   -------------------------------------------------------------------------- */

async function deleteAdmin() {
    console.log("\nDelete administrator");
    const page = makePage("delete_admin.html", { url: "/delete-admin" });

    check("it has its own fields",
        !!page.doc.querySelector("#del-admin-username") &&
        !!page.doc.querySelector("#del-admin-password"));
    check("it shares no field with the sign-in page",
        LOGIN_FIELDS.every((id) => !page.doc.querySelector(id)));
    check("the consequences are on the page, not only in a dialog",
        /deleted|cannot be undone/i.test(
            (page.doc.querySelector(".auth-warning") || {}).textContent || ""));
    check("its button reads as destructive",
        /Delete/.test(page.doc.querySelector("#btn-delete-admin").textContent));

    page.fill("#del-admin-username", "boss");
    page.fill("#del-admin-password", "Admin-Pw-123");

    page.win.confirm = () => false;
    await page.click("#btn-delete-admin");
    check("declining the confirmation sends nothing", page.posted.length === 0, page.posted.length);

    page.win.confirm = () => true;
    await page.click("#btn-delete-admin");
    check("confirming posts once", page.posted.length === 1, page.posted.length);
    check("it asks to remove", page.posted[0] && page.posted[0].body.method === "remove");
    check("the remembered session is cleared",
        page.win.__cleared === true, "a deleted account's token should not survive");
}

/* --------------------------------------------------------------------------
   Team members -- these act on an administrator's workspace
   -------------------------------------------------------------------------- */

async function memberPages() {
    console.log("\nTeam members");

    const bare = makePage("create_member.html", { url: "/create-member" });
    bare.fill("#new-member-username", "mia");
    bare.fill("#new-member-password", "Member-Pw-123");
    bare.fill("#new-member-confirm", "Member-Pw-123");
    await bare.click("#btn-create-member");
    check("without an administrator session nothing is sent",
        bare.posted.length === 0, bare.posted.length);

    const page = makePage("create_member.html", {
        url: "/create-member", admin: { username: "boss", parentId: 7 },
    });
    check("the page names the administrator acting",
        /boss/.test(page.text("#active-admin-label")), page.text("#active-admin-label"));
    check("it shares no field with the sign-in page",
        LOGIN_FIELDS.every((id) => !page.doc.querySelector(id)));

    page.fill("#new-member-username", "mia");
    page.fill("#new-member-password", "Member-Pw-123");
    page.fill("#new-member-confirm", "Member-Pw-123");
    await page.click("#btn-create-member");
    check("adding posts once", page.posted.length === 1, page.posted.length);
    check("it posts to /api/admin/employee",
        page.posted[0] && page.posted[0].path === "/api/admin/employee");
    check("it acts on the administrator's workspace",
        page.posted[0] && page.posted[0].body.Parent_id === 7,
        page.posted[0] && page.posted[0].body.Parent_id);
    check("it asks to add", page.posted[0] && page.posted[0].body.method === "add");
    check("it carries the administrator's token",
        page.posted[0] && page.posted[0].body.token === "admin-token",
        page.posted[0] && page.posted[0].body.token);

    const del = makePage("delete_member.html", {
        url: "/delete-member", admin: { username: "boss", parentId: 7 },
    });
    check("the remove page says what is lost",
        /deleted|chats/i.test((del.doc.querySelector(".auth-warning") || {}).textContent || ""));
    del.win.confirm = () => true;
    del.fill("#del-member-username", "mia");
    del.fill("#del-member-password", "Member-Pw-123");
    await del.click("#btn-delete-member");
    check("removing posts once", del.posted.length === 1, del.posted.length);
    check("it asks to remove", del.posted[0] && del.posted[0].body.method === "remove");
    check("it carries the administrator's token",
        del.posted[0] && del.posted[0].body.token === "admin-token",
        del.posted[0] && del.posted[0].body.token);
    check("it names the member",
        del.posted[0] && del.posted[0].body.username === "mia");
    check("it acts on the administrator's workspace",
        del.posted[0] && del.posted[0].body.Parent_id === 7);
}

createAdmin()
    .then(deleteAdmin)
    .then(memberPages)
    .then(() => {
        console.log(`\n${pass} passed, ${fail} failed`);
        process.exit(fail ? 1 : 0);
    })
    .catch((err) => {
        console.error(err);
        process.exit(1);
    });
