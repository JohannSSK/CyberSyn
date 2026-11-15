(function () {
    const LANG_KEY = "cybersyn_lang";
    const ATTRS = ["placeholder", "title", "aria-label"];
    const SKIP = { SCRIPT: true, STYLE: true, TEXTAREA: true };
    const textOrig = new Map();
    const attrOrig = new Map();
    const toggleButtons = [];

    const EXACT = {
        "Create administrator account": "Δημιουργία λογαριασμού διαχειριστή",
        "Add team member": "Προσθήκη μέλους ομάδας",
        "Remove team member": "Αφαίρεση μέλους ομάδας",
        "Delete account": "Διαγραφή λογαριασμού",
        "Switch administrator": "Αλλαγή διαχειριστή",
        "View team and stats": "Προβολή ομάδας και στατιστικών",
        "Signed in as administrator": "Συνδεδεμένος ως διαχειριστής",
        "Step 2 of 2": "Βήμα 2 από 2",
        "Team member sign in": "Σύνδεση μέλους ομάδας",
        "Choose the team member account you want to work in.": "Επιλέξτε τον λογαριασμό μέλους ομάδας με τον οποίο θέλετε να εργαστείτε.",
        "Username": "Όνομα χρήστη",
        "Password": "Κωδικός πρόσβασης",
        "Enter team member username": "Εισάγετε το όνομα χρήστη του μέλους",
        "Sign in": "Σύνδεση",
        "Log out": "Αποσύνδεση",
        "Logout": "Αποσύνδεση",
        "Settings": "Ρυθμίσεις",
        "Profile": "Προφίλ",
        "Team": "Ομάδα",
        "Help & info": "Βοήθεια και πληροφορίες",
        "Apply": "Εφαρμογή",
        "Save": "Αποθήκευση",
        "Cancel": "Ακύρωση",
        "Close": "Κλείσιμο",
        "Confirm": "Επιβεβαίωση",
        "Delete": "Διαγραφή",
        "Send": "Αποστολή",
        "Send anyway with admin approval": "Αποστολή με έγκριση διαχειριστή",
        "Wrong admin password": "Λάθος κωδικός διαχειριστή",
        "Admin password": "Κωδικός διαχειριστή",
        "Settings applied.": "Οι ρυθμίσεις εφαρμόστηκαν.",
        "Could not reach the server.": "Δεν ήταν δυνατή η επικοινωνία με τον διακομιστή.",
        "Clear chat": "Εκκαθάριση συνομιλίας",
        "Change password": "Αλλαγή κωδικού",
        "Change username": "Αλλαγή ονόματος χρήστη",
        "Current password": "Τρέχων κωδικός",
        "New password": "Νέος κωδικός",
        "New username": "Νέο όνομα χρήστη",
        "API key": "Κλειδί API",
        "Model": "Μοντέλο",
        "Back to sign in": "Πίσω στη σύνδεση",
        "Refresh": "Ανανέωση",
        "Team and stats": "Ομάδα και στατιστικά",
        "Administrator": "Διαχειριστής",
        "Team members": "Μέλη ομάδας",
        "Prompts sent": "Αποσταλμένα prompts",
        "Blocked": "Αποκλείστηκαν",
        "Block rate": "Ποσοστό αποκλεισμού",
        "Members": "Μέλη",
        "No team members yet. Add one from the sign-in page.": "Δεν υπάρχουν ακόμη μέλη ομάδας. Προσθέστε ένα από τη σελίδα σύνδεσης.",
        "Loading...": "Φόρτωση...",
        "Not signed in": "Δεν έχετε συνδεθεί",
        "Sign in as an administrator first.": "Συνδεθείτε πρώτα ως διαχειριστής.",
        "Could not load the team.": "Δεν ήταν δυνατή η φόρτωση της ομάδας.",
        "Your administrator session has ended.": "Η συνεδρία διαχειριστή έληξε.",
        "Sent": "Εστάλησαν",
        "Answered": "Απαντήθηκαν",
        "Block reasons": "Αιτίες αποκλεισμού",
        "Blocks by check": "Αποκλεισμοί ανά έλεγχο",
        "No blocked prompts yet.": "Δεν υπάρχουν ακόμη αποκλεισμένα prompts.",
        "No checks triggered yet.": "Δεν έχει ενεργοποιηθεί ακόμη κανένας έλεγχος.",
        "Admin password must be at least 8 characters.": "Ο κωδικός διαχειριστή πρέπει να έχει τουλάχιστον 8 χαρακτήρες.",
        "Admin password must include at least one number.": "Ο κωδικός διαχειριστή πρέπει να περιέχει τουλάχιστον έναν αριθμό.",
        "Admin password must include at least one letter.": "Ο κωδικός διαχειριστή πρέπει να περιέχει τουλάχιστον ένα γράμμα."
    };

    const PATTERNS = [
        [/^([0-9]+) of 3 checks on$/, (m, n) => n + " από 3 έλεγχους ενεργούς"],
        [/^Signed in as (.+)$/, (m, name) => "Συνδεδεμένος ως " + name],
        [/^([0-9]+) members?$/, (m, n) => (n === "1" ? "1 μέλος" : n + " μέλη")],
        [/^(Answered|Blocked) ([0-9]+)%$/, (m, word, n) => (word === "Answered" ? "Απαντήθηκαν" : "Αποκλείστηκαν") + " " + n + "%"],
        [/^Check ([0-9])$/, (m, n) => "Έλεγχος " + n],
        [/^Are you sure you want to delete team member (.+)\? This cannot be undone\.$/, (m, name) => "Είστε βέβαιοι ότι θέλετε να διαγράψετε το μέλος ομάδας " + name + "; Η ενέργεια αυτή δεν μπορεί να ακυρωθεί."],
        [/^Yes, delete (.+)$/, (m, name) => "Ναι, διαγραφή του " + name]
    ];

    function current() {
        return localStorage.getItem(LANG_KEY) === "el" ? "el" : "en";
    }

    function translate(text) {
        const core = text.replace(/\s+/g, " ").trim();
        if (!core) return null;
        let out = null;
        if (Object.prototype.hasOwnProperty.call(EXACT, core)) {
            out = EXACT[core];
        } else {
            for (const [re, rep] of PATTERNS) {
                if (re.test(core)) {
                    out = core.replace(re, rep);
                    break;
                }
            }
        }
        if (out === null || out === core) return null;
        const lead = text.match(/^\s*/)[0];
        const trail = text.match(/\s*$/)[0];
        return lead + out + trail;
    }

    function setText(node, out) {
        const prev = textOrig.get(node);
        const orig = prev && prev.out === node.data ? prev.orig : node.data;
        textOrig.set(node, { orig: orig, out: out });
        node.data = out;
    }

    function setAttr(el, name, out) {
        let map = attrOrig.get(el);
        if (!map) {
            map = {};
            attrOrig.set(el, map);
        }
        const current = el.getAttribute(name);
        const prev = map[name];
        const orig = prev && prev.out === current ? prev.orig : current;
        map[name] = { orig: orig, out: out };
        el.setAttribute(name, out);
    }

    function translateAttr(el, name) {
        if (!el.hasAttribute || !el.hasAttribute(name)) return;
        const out = translate(el.getAttribute(name));
        if (out !== null) setAttr(el, name, out);
    }

    function translateNode(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            if (!node.parentNode || SKIP[node.parentNode.nodeName]) return;
            const out = translate(node.data);
            if (out !== null) setText(node, out);
            return;
        }
        if (node.nodeType !== Node.ELEMENT_NODE || SKIP[node.nodeName]) return;
        ATTRS.forEach(name => translateAttr(node, name));
        Array.from(node.childNodes).forEach(translateNode);
    }

    function restoreAll() {
        textOrig.forEach((entry, node) => {
            if (node.isConnected && node.data === entry.out) node.data = entry.orig;
        });
        textOrig.clear();
        attrOrig.forEach((map, el) => {
            Object.keys(map).forEach(name => {
                if (el.isConnected && el.getAttribute(name) === map[name].out) {
                    el.setAttribute(name, map[name].orig);
                }
            });
        });
        attrOrig.clear();
    }

    function applyToggle() {
        toggleButtons.forEach(b => b.classList.toggle("is-active", b.dataset.lang === current()));
    }

    function setLang(code) {
        localStorage.setItem(LANG_KEY, code);
        document.documentElement.lang = code;
        document.documentElement.dataset.lang = code;
        if (code === "el") {
            translateNode(document.body);
        } else {
            restoreAll();
        }
        applyToggle();
    }

    function run() {
        if (current() === "el") translateNode(document.body);
    }

    const observer = new MutationObserver(records => {
        if (current() !== "el") return;
        records.forEach(r => {
            if (r.type === "characterData") translateNode(r.target);
            else if (r.type === "attributes") translateAttr(r.target, r.attributeName);
            else r.addedNodes.forEach(translateNode);
        });
    });

    function buildToggle() {
        const wrap = document.createElement("div");
        wrap.className = "lang-switch";
        [["en", "EN"], ["el", "ΕΛ"]].forEach(([code, label]) => {
            const b = document.createElement("button");
            b.type = "button";
            b.className = "lang-btn";
            b.dataset.lang = code;
            b.textContent = label;
            b.addEventListener("click", () => setLang(code));
            toggleButtons.push(b);
            wrap.appendChild(b);
        });
        document.body.appendChild(wrap);
        applyToggle();
    }

    document.documentElement.lang = current();
    document.documentElement.dataset.lang = current();
    run();
    document.addEventListener("DOMContentLoaded", run);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    buildToggle();
})();
