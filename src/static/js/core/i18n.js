/* ==========================================================================
   i18n.js — runtime English / Greek switching.

   The interface is written in English and translated in the browser, so no
   page needs a second copy of its markup. Switching walks text nodes and a
   few attributes, remembers the original of everything it touches, and puts
   it back when you switch to English.

   Templates place the switch with <div data-lang-switch></div>. Page code
   translates strings it builds itself with I18n.t("..."), and anything added
   to the DOM later is picked up by the observer.
   ========================================================================== */

(function (global) {
    "use strict";

    var STORAGE_KEY = "cybersyn_lang";
    var CODES = ["en", "el"];

    /* Attributes whose text is user-visible. */
    var ATTRS = ["placeholder", "title", "aria-label"];

    /* Subtrees whose text is data, not interface copy. */
    var SKIP = { SCRIPT: true, STYLE: true, TEXTAREA: true, CODE: true, PRE: true, MARK: true };

    var originals = { text: new Map(), attr: new Map() };
    var buttons = [];

    /* ------------------------------------------------------------------
       The dictionary. Exact matches first, then patterns for strings that
       carry a number or a name.
       ------------------------------------------------------------------ */

    var EXACT = {
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
        "Statistics": "Στατιστικά",
        "Chat": "Συνομιλία",
        "Photo scan": "Έλεγχος φωτογραφιών",
        "Data protection": "Προστασία δεδομένων",
        "Upload a photo. CyberSyn finds the personal data in it — faces, tax numbers, phones, IBANs, document fields — and hands you back a copy with every finding covered.": "Ανεβάστε μια φωτογραφία. Το CyberSyn εντοπίζει τα προσωπικά δεδομένα σε αυτήν — πρόσωπα, ΑΦΜ, τηλέφωνα, IBAN, πεδία εγγράφων — και σας επιστρέφει ένα αντίγραφο με κάθε εύρημα καλυμμένο.",
        "Drop a photo here": "Σύρετε μια φωτογραφία εδώ",
        "or click to browse — JPEG, PNG or WebP, up to 12 MB": "ή κάντε κλικ για επιλογή — JPEG, PNG ή WebP, έως 12 MB",
        "Scanned in memory on this server. The photo is never stored.": "Σάρωση στη μνήμη αυτού του διακομιστή. Η φωτογραφία δεν αποθηκεύεται ποτέ.",
        "Cover with": "Κάλυψη με",
        "Blur": "Θόλωμα",
        "Black box": "Μαύρο πλαίσιο",
        "Download redacted copy": "Λήψη καλυμμένου αντιγράφου",
        "Scan another photo": "Νέα σάρωση",
        "Faces": "Πρόσωπα",
        "Numbers": "Αριθμοί",
        "Documents": "Έγγραφα",
        "Portraits and group photos are biometric data under GDPR — they are always covered.": "Τα πορτρέτα και οι ομαδικές φωτογραφίες είναι βιομετρικά δεδομένα κατά τον GDPR — καλύπτονται πάντα.",
        "ΑΦΜ, ΑΜΚΑ, phone numbers, IBANs, payment cards, ID numbers and plates — in Greek or English text.": "ΑΦΜ, ΑΜΚΑ, τηλέφωνα, IBAN, κάρτες πληρωμής, αριθμοί ταυτότητας και πινακίδες — σε ελληνικό ή αγγλικό κείμενο.",
        "Next to labels like «ΕΠΩΝΥΜΟ», «ΟΝΟΜΑ», «ΔΙΕΥΘΥΝΣΙΣ», the value is covered even when no pattern matches it.": "Δίπλα σε ετικέτες όπως «ΕΠΩΝΥΜΟ», «ΟΝΟΜΑ», «ΔΙΕΥΘΥΝΣΙΣ», η τιμή καλύπτεται ακόμη κι αν δεν ταιριάζει σε κάποιο μοτίβο.",
        "Nothing to cover in this photo.": "Τίποτα προς κάλυψη σε αυτή τη φωτογραφία.",
        "Clean — no personal data found.": "Καθαρή — δεν βρέθηκαν προσωπικά δεδομένα.",
        "Faces, numbers and document fields were all checked.": "Ελέγχθηκαν πρόσωπα, αριθμοί και πεδία εγγράφων.",
        "The original never left this page. Download the redacted copy below.": "Το πρωτότυπο δεν έφυγε ποτέ από αυτή τη σελίδα. Κατεβάστε το καλυμμένο αντίγραφο παρακάτω.",
        "Detecting faces…": "Εντοπισμός προσώπων…",
        "Reading text (OCR)…": "Ανάγνωση κειμένου (OCR)…",
        "Matching personal data…": "Αντιστοίχιση προσωπικών δεδομένων…",
        "Covering findings…": "Κάλυψη ευρημάτων…",
        "Redacted copy downloaded.": "Το καλυμμένο αντίγραφο λήφθηκε.",
        "The image is too large (12 MB max).": "Η εικόνα είναι πολύ μεγάλη (έως 12 MB).",
        "Help & info": "Βοήθεια και πληροφορίες",
        "Apply": "Εφαρμογή",
        "Save": "Αποθήκευση",
        "Cancel": "Άκυρο",
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
        "Admin password must include at least one letter.": "Ο κωδικός διαχειριστή πρέπει να περιέχει τουλάχιστον ένα γράμμα.",

        "Search messages": "Αναζήτηση μηνυμάτων",
        "New chat": "Νέα συνομιλία",
        "Write a message": "Γράψτε ένα μήνυμα",
        "Start the conversation": "Ξεκινήστε τη συνομιλία",
        "No messages match": "Κανένα μήνυμα δεν ταιριάζει",
        "Copy the answer": "Αντιγραφή της απάντησης",
        "Edit this message": "Επεξεργασία αυτού του μηνύματος",
        "Generate a different answer": "Δημιουργία διαφορετικής απάντησης",
        "Delete this message": "Διαγραφή αυτού του μηνύματος",
        "Recent activity": "Πρόσφατη δραστηριότητα",
        "Team activity": "Δραστηριότητα ομάδας",
        "Blocks over time": "Αποκλεισμοί στο χρόνο",
        "Per member": "Ανά μέλος",
        "Screening checks": "Έλεγχοι προστασίας",
        "Account": "Λογαριασμός",
        "Messages": "Μηνύματα",
        "message": "μήνυμα",
        "messages": "μηνύματα",
        "Overridden": "Παρακάμφθηκαν",
        "Overrides": "Παρακάμψεις",
        "Today": "Σήμερα",
        "Administrator sign in": "Σύνδεση διαχειριστή",
        "Sign in with your administrator account to manage your workspace.": "Συνδεθείτε με τον λογαριασμό διαχειριστή για να διαχειριστείτε τον χώρο εργασίας σας.",
        "Use AI at work without exposing what matters.": "Χρησιμοποιήστε την τεχνητή νοημοσύνη στη δουλειά, χωρίς να εκθέτετε ό,τι έχει σημασία.",
        "CyberSyn reviews every message on your own machine before it reaches an AI model, so sensitive information stays inside your organisation.": "Το CyberSyn ελέγχει κάθε μήνυμα στον υπολογιστή σας πριν φτάσει σε ένα μοντέλο τεχνητής νοημοσύνης, ώστε οι ευαίσθητες πληροφορίες να παραμένουν στον οργανισμό σας.",
        "Screened locally": "Έλεγχος τοπικά",
        "Every check runs on this computer. Nothing is sent out for review.": "Κάθε έλεγχος εκτελείται σε αυτόν τον υπολογιστή. Τίποτα δεν αποστέλλεται για επιθεώρηση.",
        "Built for Greek data": "Σχεδιασμένο για ελληνικά δεδομένα",
        "Recognises AFM, AMKA, phone numbers and company names.": "Αναγνωρίζει ΑΦΜ, ΑΜΚΑ, αριθμούς τηλεφώνου και επωνυμίες εταιρειών.",
        "Administrator controlled": "Έλεγχος από διαχειριστή",
        "Admins manage team access and approve any exceptions.": "Οι διαχειριστές διαχειρίζονται την πρόσβαση της ομάδας και εγκρίνουν κάθε εξαίρεση.",
        "Continue": "Συνέχεια",
        "Open workspace": "Άνοιγμα χώρου εργασίας",
        "Conversations": "Συνομιλίες",
        "New chat": "Νέα συνομιλία",
        "Search messages": "Αναζήτηση μηνυμάτων",
        "Team statistics": "Στατιστικά ομάδας",
        "Who sent what, what was stopped, and when.": "Ποιος έστειλε τι, τι σταμάτησε και πότε.",
        "Messages sent": "Μηνύματα που εστάλησαν",
        "Blocked messages": "Αποκλεισμένα μηνύματα",
        "Blocked and overridden, per day": "Αποκλεισμοί και παρακάμψεις, ανά ημέρα",
        "Why messages were stopped": "Γιατί σταμάτησαν τα μηνύματα",
        "Which check stopped them": "Ποιος έλεγχος τα σταμάτησε",
        "Per team member": "Ανά μέλος ομάδας",
        "Every step, with a timestamp": "Κάθε βήμα, με χρονική σήμανση",
        "Your prompts": "Τα prompts σας",
        "Recent activity": "Πρόσφατη δραστηριότητα",
        "Team activity": "Δραστηριότητα ομάδας",
        "Blocks over time": "Αποκλεισμοί στον χρόνο",
        "AI connection": "Σύνδεση με το AI",
        "Local safety checks": "Τοπικοί έλεγχοι ασφαλείας",
        "Save checks": "Αποθήκευση ελέγχων",
        "Save connection": "Αποθήκευση σύνδεσης",
        "Your API key": "Το κλειδί API σας",
        "The key is encrypted on the server and never sent back to the browser.": "Το κλειδί κρυπτογραφείται στον διακομιστή και δεν επιστρέφεται ποτέ στο πρόγραμμα περιήγησης.",
        "Paste a key first to load the models it can reach.": "Επικολλήστε πρώτα ένα κλειδί για να φορτωθούν τα μοντέλα που μπορεί να χρησιμοποιήσει.",
        "Turning every check off sends your prompts straight to the AI provider with no local screening.": "Με όλους τους ελέγχους απενεργοποιημένους, τα prompts αποστέλλονται κατευθείαν στον πάροχο AI χωρίς κανέναν τοπικό έλεγχο.",
        "Your account and the workspace you belong to.": "Ο λογαριασμός σας και ο χώρος εργασίας στον οποίο ανήκετε.",
        "Member ID": "Αναγνωριστικό μέλους",
        "Workspace ID": "Αναγνωριστικό χώρου εργασίας",
        "Refresh list": "Ανανέωση λίστας",
        "How the gate works, and what each check looks for.": "Πώς λειτουργεί η πύλη και τι εντοπίζει ο κάθε έλεγχος.",
        "The three checks": "Οι τρεις έλεγχοι",
        "Quick start": "Γρήγορη εκκίνηση",
        "Reference": "Αναφορά",
        "What never leaves this machine": "Τι δεν φεύγει ποτέ από αυτό το μηχάνημα",
        "When a check cannot run": "Όταν ένας έλεγχος δεν μπορεί να εκτελεστεί",
        "Source on GitHub": "Πηγαίος κώδικας στο GitHub",
        "Everyone in this workspace and how their gate is configured.": "Όλα τα μέλη αυτού του χώρου εργασίας και πώς έχει ρυθμιστεί η πύλη τους.",
        "Keys configured": "Κλειδιά που έχουν ρυθμιστεί",
        "Safety checks enabled": "Ενεργοί έλεγχοι ασφαλείας",
        "Personal & Greek IDs": "Προσωπικά και ελληνικά αναγνωριστικά",
        "Confidential context": "Εμπιστευτικό περιεχόμενο",
        "Prompt injection": "Εισαγωγή εντολών (prompt injection)",
        "Admin": "Διαχειριστής",
        "Member": "Μέλος",
        "Workspace": "Χώρος εργασίας",
        "No key saved yet.": "Δεν έχει αποθηκευτεί ακόμη κλειδί.",
        "Approved override": "Εγκεκριμένη παράκαμψη",
        "Never transmitted to any provider": "Δεν μεταδίδεται ποτέ σε κανέναν πάροχο",
        "No third-party classifier is consulted": "Δεν χρησιμοποιείται εξωτερικός ταξινομητής",
        "Screened locally before sending": "Ελέγχεται τοπικά πριν την αποστολή",
        "Stored encrypted, only ever shown masked": "Αποθηκεύεται κρυπτογραφημένο και εμφανίζεται πάντα καλυμμένο",
        "Sign out": "Αποσύνδεση",
        "Create an administrator account from the sign-in screen.": "Δημιουργήστε λογαριασμό διαχειριστή από την οθόνη σύνδεσης.",
        "Sign in as administrator, then add your team members.": "Συνδεθείτε ως διαχειριστής και στη συνέχεια προσθέστε τα μέλη της ομάδας σας.",
        "today": "σήμερα",
        "7 days": "7 ημέρες",
        "14 days": "14 ημέρες",
        "30 days": "30 ημέρες",
        "days": "ημέρες",
        "Open": "Άνοιγμα"
    };

    /* Strings that embed a number or a name cannot be exact-matched. */
    var PATTERNS = [
        [/^Photo blocked — ([0-9]+) personal data items? found\.$/, function (m, n) {
            return n === "1"
                ? "Η φωτογραφία αποκλείστηκε — βρέθηκε 1 προσωπικό δεδομένο."
                : "Η φωτογραφία αποκλείστηκε — βρέθηκαν " + n + " προσωπικά δεδομένα.";
        }],
        [/^([0-9]+) of 3 checks (?:on|active)$/, function (m, n) { return n + " από 3 έλεγχοι ενεργοί"; }],
        [/^Signed in as (.+)$/, function (m, name) { return "Συνδεδεμένος ως " + name; }],
        [/^([0-9]+) members?$/, function (m, n) { return n === "1" ? "1 μέλος" : n + " μέλη"; }],
        [/^(Answered|Blocked) ([0-9]+)%$/, function (m, word, n) {
            return (word === "Answered" ? "Απαντήθηκαν" : "Αποκλείστηκαν") + " " + n + "%";
        }],
        [/^Check ([0-9])$/, function (m, n) { return "Έλεγχος " + n; }],
        [/^([0-9]+) messages?$/, function (m, n) { return n === "1" ? "1 μήνυμα" : n + " μηνύματα"; }]
    ];

    /* ------------------------------------------------------------------
       State and lookup
       ------------------------------------------------------------------ */

    function current() {
        var stored = null;
        try {
            stored = global.localStorage.getItem(STORAGE_KEY);
        } catch (err) { /* private browsing: stay in English */ }
        return stored === "el" ? "el" : "en";
    }

    /** Translate one string. Returns null when there is no translation. */
    function t(text) {
        if (current() !== "el") return text;
        var source = String(text == null ? "" : text);
        var core = source.replace(/\s+/g, " ").trim();
        if (!core) return source;

        var out = null;
        if (Object.prototype.hasOwnProperty.call(EXACT, core)) {
            out = EXACT[core];
        } else {
            for (var i = 0; i < PATTERNS.length && out === null; i++) {
                if (PATTERNS[i][0].test(core)) out = core.replace(PATTERNS[i][0], PATTERNS[i][1]);
            }
        }
        if (out === null || out === core) return source;

        // Keep the leading and trailing whitespace the node had.
        return source.replace(core, out);
    }

    /* ------------------------------------------------------------------
       Walking the DOM
       ------------------------------------------------------------------ */

    function setText(node, out) {
        var seen = originals.text.get(node);
        var orig = seen && seen.out === node.data ? seen.orig : node.data;
        originals.text.set(node, { orig: orig, out: out });
        node.data = out;
    }

    function setAttr(el, name, out) {
        var map = originals.attr.get(el);
        if (!map) { map = {}; originals.attr.set(el, map); }
        var live = el.getAttribute(name);
        var seen = map[name];
        var orig = seen && seen.out === live ? seen.orig : live;
        map[name] = { orig: orig, out: out };
        el.setAttribute(name, out);
    }

    function translateAttr(el, name) {
        if (!el.hasAttribute || !el.hasAttribute(name)) return;
        var out = t(el.getAttribute(name));
        if (out !== el.getAttribute(name)) setAttr(el, name, out);
    }

    function translateNode(node) {
        if (node.nodeType === 1) {  // element
            if (SKIP[node.nodeName]) return;
            ATTRS.forEach(function (name) { translateAttr(node, name); });
            Array.prototype.slice.call(node.childNodes).forEach(translateNode);
            return;
        }
        if (node.nodeType === 3) {  // text
            var parent = node.parentNode;
            if (!parent || SKIP[parent.nodeName]) return;
            var out = t(node.data);
            if (out !== node.data) setText(node, out);
        }
    }

    /** Put every string we changed back to English. */
    function restore() {
        originals.text.forEach(function (entry, node) {
            if (node.isConnected && node.data === entry.out) node.data = entry.orig;
        });
        originals.text.clear();
        originals.attr.forEach(function (map, el) {
            Object.keys(map).forEach(function (name) {
                if (el.isConnected && el.getAttribute(name) === map[name].out) {
                    el.setAttribute(name, map[name].orig);
                }
            });
        });
        originals.attr.clear();
    }

    /* ------------------------------------------------------------------
       Public behaviour
       ------------------------------------------------------------------ */

    function paintButtons() {
        var code = current();
        buttons.forEach(function (button) {
            button.classList.toggle("is-active", button.getAttribute("data-lang") === code);
            button.setAttribute("aria-pressed", button.getAttribute("data-lang") === code ? "true" : "false");
        });
    }

    function set(code) {
        if (CODES.indexOf(code) === -1) return;
        try {
            global.localStorage.setItem(STORAGE_KEY, code);
        } catch (err) { /* nothing to persist to; still switch for this page */ }
        global.document.documentElement.lang = code;
        global.document.documentElement.setAttribute("data-lang", code);
        if (code === "el") translateNode(global.document.body);
        else restore();
        paintButtons();
    }

    /** Translate the whole page. Safe to call again after inserting markup. */
    function apply() {
        if (current() === "el") translateNode(global.document.body);
        paintButtons();
    }

    /* Build the EN / ΕΛ switch wherever the template asked for one. */
    function buildSwitch(slot) {
        var wrap = global.document.createElement("div");
        wrap.className = "lang-switch";
        wrap.setAttribute("role", "group");
        wrap.setAttribute("aria-label", "Language");

        [["en", "EN"], ["el", "ΕΛ"]].forEach(function (pair) {
            var button = global.document.createElement("button");
            button.type = "button";
            button.className = "lang-btn";
            button.setAttribute("data-lang", pair[0]);
            button.textContent = pair[1];
            global.Dom.on(button, "click", function () {
                if (current() !== pair[0]) set(pair[0]);
            });
            buttons.push(button);
            wrap.appendChild(button);
        });

        slot.appendChild(wrap);
    }

    /* Content rendered after load — messages, statistics, toasts — needs the
       same treatment, so watch for it rather than sprinkling calls around. */
    function observe() {
        if (!global.MutationObserver) return;
        var observer = new global.MutationObserver(function (records) {
            if (current() !== "el") return;
            records.forEach(function (record) {
                if (record.type === "characterData") translateNode(record.target);
                else if (record.type === "attributes") translateAttr(record.target, record.attributeName);
                else Array.prototype.slice.call(record.addedNodes).forEach(translateNode);
            });
        });
        observer.observe(global.document.body, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true,
            attributeFilter: ATTRS
        });
    }

    global.document.documentElement.lang = current();
    global.document.documentElement.setAttribute("data-lang", current());

    global.Dom.on(global.document, "DOMContentLoaded", function () {
        global.Dom.$$("[data-lang-switch]").forEach(buildSwitch);
        apply();
        observe();
    });

    global.I18n = { t: t, set: set, apply: apply, current: current, codes: CODES };
})(window);
