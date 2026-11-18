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
    var DATA = "[data-no-i18n],.bubble-user,.bubble-ai,.chat-item-title,.blocked-match code," +
        "[data-member-name],[data-member-avatar],#active-admin-label,#info-username," +
        "#info-model,#setting-model,.member-id strong,.tl-body small,script,style,code,pre,mark";
    function isUntranslatedElement(el) { return el && el.closest && !!el.closest(DATA); }

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
        "Open": "Άνοιγμα",
        "AI Security Gateway · Running locally": "Πύλη ασφαλείας AI · Εκτελείται τοπικά",
        "Step 1 of 2": "Βήμα 1 από 2",
        "Enter your username": "Πληκτρολογήστε το όνομα χρήστη σας",
        "Enter your password": "Πληκτρολογήστε τον κωδικό σας",
        "Enter team member password": "Πληκτρολογήστε τον κωδικό του μέλους",
        "Protected by local Python scanners. Sign-in is required each time you open this page.": "Προστασία με τοπικούς ελέγχους Python. Απαιτείται σύνδεση για πρόσβαση.",
        "One administrator per workspace.": "Ένας διαχειριστής ανά χώρο εργασίας.",
        "The administrator holds the workspace: they add team members, set the privacy policy, and approve anything the gate blocks.": "Ο διαχειριστής προσθέτει μέλη, ορίζει την πολιτική απορρήτου και εγκρίνει εξαιρέσεις όταν ένα μήνυμα αποκλείεται.",
        "New account": "Νέος λογαριασμός",
        "Choose a username and a password. This account owns the workspace, so keep the password somewhere safe — losing it means losing the team.": "Επιλέξτε όνομα χρήστη και κωδικό. Ο λογαριασμός αυτός ελέγχει τον χώρο εργασίας· φυλάξτε τον κωδικό σε ασφαλές μέρος.",
        "Choose a username": "Επιλέξτε όνομα χρήστη",
        "Choose a password": "Επιλέξτε κωδικό",
        "Confirm password": "Επιβεβαίωση κωδικού",
        "Type the password again": "Πληκτρολογήστε ξανά τον κωδικό",
        "Registration token (if required)": "Κωδικός εγγραφής (αν απαιτείται)",
        "Leave empty for the first administrator.": "Αφήστε το πεδίο κενό για τον πρώτο διαχειριστή.",
        "Create account": "Δημιουργία λογαριασμού",
        "Accounts are stored on this machine only.": "Οι λογαριασμοί αποθηκεύονται μόνο σε αυτό το μηχάνημα.",
        "This cannot be undone.": "Η ενέργεια δεν αναιρείται.",
        "Deleting an administrator removes their team members, their settings and their chat history with it. Team statistics are kept.": "Διαγράφοντας τον διαχειριστή διαγράφετε τα μέλη του, τις ρυθμίσεις τους και το ιστορικό συνομιλιών τους. Τα στατιστικά διατηρούνται.",
        "Danger zone": "Ζώνη κινδύνου",
        "Delete administrator account": "Διαγραφή λογαριασμού διαχειριστή",
        "Sign in with the account you want to delete. It is removed as soon as the password is confirmed.": "Συνδεθείτε με τον λογαριασμό που θέλετε να διαγράψετε. Η διαγραφή εκτελείται μόλις επιβεβαιωθεί ο κωδικός.",
        "The account to delete": "Λογαριασμός προς διαγραφή",
        "Its password": "Κωδικός λογαριασμού",
        "Every team member, every setting and every chat under this administrator is deleted. Statistics are kept.": "Διαγράφονται όλα τα μέλη, οι ρυθμίσεις και οι συνομιλίες αυτού του διαχειριστή. Τα στατιστικά διατηρούνται.",
        "Delete this account": "Διαγραφή αυτού του λογαριασμού",
        "Everything belonging to this workspace is erased.": "Διαγράφονται τα δεδομένα αυτού του χώρου εργασίας.",
        "One seat per person.": "Ένας λογαριασμός ανά άτομο.",
        "Each team member signs in on their own and gets their own chats, their own history, and the policy you set for them.": "Κάθε μέλος συνδέεται ξεχωριστά και έχει τις δικές του συνομιλίες, το δικό του ιστορικό και την πολιτική που ορίζετε για αυτό.",
        "New team member": "Νέο μέλος ομάδας",
        "Give them a username and a password to sign in with. They can change both later from their own profile.": "Ορίστε όνομα χρήστη και κωδικό σύνδεσης. Το μέλος μπορεί να τα αλλάξει αργότερα από το προφίλ του.",
        "At least 8 characters, including a letter and a number.": "Τουλάχιστον 8 χαρακτήρες, με ένα γράμμα και έναν αριθμό.",
        "They inherit this workspace's privacy policy.": "Το μέλος κληρονομεί την πολιτική απορρήτου του χώρου εργασίας.",
        "Their workspace goes with them.": "Με την αποχώρηση του μέλους διαγράφεται ο προσωπικός του χώρος.",
        "Removing a team member deletes their chats and their settings. Team statistics are kept, so the audit trail stays whole.": "Η αφαίρεση μέλους διαγράφει τις συνομιλίες και τις ρυθμίσεις του. Τα στατιστικά της ομάδας διατηρούνται για έλεγχο.",
        "Select a member and confirm with your administrator password.": "Επιλέξτε μέλος και επιβεβαιώστε με τον κωδικό διαχειριστή.",
        "Member username": "Όνομα χρήστη μέλους",
        "The member to remove": "Μέλος προς αφαίρεση",
        "Administrator password": "Κωδικός διαχειριστή",
        "Their chats and settings are deleted. Statistics are kept.": "Οι συνομιλίες και οι ρυθμίσεις του διαγράφονται. Τα στατιστικά διατηρούνται.",
        "Remove this member": "Αφαίρεση αυτού του μέλους",
        "Their sessions are ended immediately.": "Οι συνεδρίες του τερματίζονται αμέσως.",
        "Start a new chat": "Έναρξη νέας συνομιλίας",
        "Toggle sidebar": "Εμφάνιση ή απόκρυψη πλευρικής στήλης",
        "Rename this chat": "Μετονομασία συνομιλίας",
        "Search messages…": "Αναζήτηση μηνυμάτων…",
        "Clear search": "Καθαρισμός αναζήτησης",
        "Other conversations": "Άλλες συνομιλίες",
        "Delete this chat": "Διαγραφή συνομιλίας",
        "Ask anything… (Enter to send, Shift+Enter for a new line)": "Γράψτε μια ερώτηση… (Enter για αποστολή, Shift+Enter για νέα γραμμή)",
        "Message": "Μήνυμα",
        "Send message": "Αποστολή μηνύματος",
        "Checked on this machine before anything reaches the AI provider.": "Το μήνυμα ελέγχεται τοπικά πριν φτάσει στον πάροχο AI.",
        "Toggle navigation": "Εμφάνιση ή απόκρυψη πλοήγησης",
        "Policy, model connection and how your prompts are screened.": "Πολιτική, σύνδεση με το μοντέλο και έλεγχος των μηνυμάτων σας.",
        "Each check runs on this machine before a prompt is sent. Turn one off only with a reason — the setting is applied to every message you send.": "Κάθε έλεγχος εκτελείται τοπικά πριν από την αποστολή. Απενεργοποιήστε τον μόνο αν υπάρχει λόγος· η ρύθμιση ισχύει για κάθε μήνυμα αυτού του μέλους.",
        "AFM with checksum, AMKA, Greek phone numbers, emails and names (EN + EL)": "ΑΦΜ με ψηφίο ελέγχου, ΑΜΚΑ, ελληνικά τηλέφωνα, email και ονόματα (ΕΛ + EN)",
        "Contracts and NDAs, financials, HR and payroll, credentials, source code": "Συμβάσεις, οικονομικά στοιχεία, μισθοδοσία και διαπιστευτήρια",
        "Jailbreaks, hidden instructions and override attempts": "Κρυφές οδηγίες και απόπειρες παράκαμψης των κανόνων του μοντέλου",
        "Block proprietary source code": "Αποκλεισμός ιδιόκτητου πηγαίου κώδικα",
        "Block source-code pastes from this member. Off allows code review; other enabled checks still apply.": "Αποκλείει αποσπάσματα κώδικα από αυτό το μέλος. Όταν είναι ανενεργό, επιτρέπεται η ανασκόπηση κώδικα· οι άλλοι ενεργοί έλεγχοι εξακολουθούν να ισχύουν.",
        "Also save these checks as the workspace default for new team members": "Αποθήκευση των ελέγχων και ως προεπιλογής για νέα μέλη του χώρου εργασίας",
        "Provider": "Πάροχος",
        "Detect automatically": "Αυτόματη ανίχνευση",
        "Automatic detection uses the key prefix. For unfamiliar or shared formats, select your provider before entering a key.": "Η ανίχνευση βασίζεται στο πρόθεμα του κλειδιού. Για άγνωστες ή αμφίσημες μορφές, επιλέξτε πάροχο πριν εισαγάγετε κλειδί.",
        "Base URL": "Βασική διεύθυνση URL",
        "Where that provider is reached. Leave empty for the hosted address.": "Διεύθυνση του παρόχου. Αφήστε την κενή για την προεπιλεγμένη διεύθυνση της υπηρεσίας.",
        "Paste a key and the models it can reach are listed automatically.": "Επικολλήστε ένα κλειδί για να εμφανιστούν τα διαθέσιμα μοντέλα.",
        "Paste your API key…": "Επικολλήστε το κλειδί API…",
        "Remove saved key": "Αφαίρεση αποθηκευμένου κλειδιού",
        "Administrator username": "Όνομα χρήστη διαχειριστή",
        "Change administrator password": "Αλλαγή κωδικού διαχειριστή",
        "How the gate works, what each check looks for, and the software that makes it run.": "Πώς λειτουργεί η πύλη, τι εντοπίζει κάθε έλεγχος και σε ποιο λογισμικό βασίζεται.",
        "On this page": "Σε αυτή τη σελίδα",
        "Using the chat": "Χρήση της συνομιλίας",
        "Accounts and roles": "Λογαριασμοί και ρόλοι",
        "What is stored, and how": "Τι αποθηκεύεται και πώς",
        "Configuration": "Παραμετροποίηση",
        "Troubleshooting": "Αντιμετώπιση προβλημάτων",
        "Licences": "Άδειες χρήσης",
        "Sign in as the member whose settings you want to configure.": "Συνδεθείτε ως το μέλος του οποίου τις ρυθμίσεις θέλετε να ορίσετε.",
        "In Settings, select the provider, enter a key and save the model and checks with administrator approval.": "Στις Ρυθμίσεις, επιλέξτε πάροχο, εισαγάγετε κλειδί και αποθηκεύστε το μοντέλο και τους ελέγχους με έγκριση διαχειριστή.",
        "as the administrator to see who was blocked, why, and when.": "ως διαχειριστής για να δείτε ποιος αποκλείστηκε, πότε και γιατί.",
        "Enabled checks run in parallel under one time budget. Blocks are reported in stage order.": "Οι ενεργοί έλεγχοι εκτελούνται παράλληλα με κοινή προθεσμία. Οι αποκλεισμοί αναφέρονται με τη σειρά των σταδίων.",
        "Greek tax numbers and IBANs are checked by checksum; Greek IDs by format and context. Checks also cover AMKA dates, phones, emails, modern API keys and company names.": "Για ΑΦΜ και IBAN επαληθεύονται τα ψηφία ελέγχου, ενώ για ταυτότητες εξετάζονται η μορφή και τα συμφραζόμενα. Ελέγχονται επίσης ημερομηνίες ΑΜΚΑ, τηλέφωνα, email, σύγχρονα κλειδιά API και επωνυμίες.",
        "Local English and Greek name-recognition models check for personal names.": "Τοπικά μοντέλα αναγνωρίζουν ονόματα προσώπων στα αγγλικά και στα ελληνικά.",
        "Patterns and IBAN/card checksums detect credentials, banking data and strong indicators of confidential records. A local zero-shot model classifies ambiguous text.": "Μοτίβα και ψηφία ελέγχου IBAN και καρτών εντοπίζουν διαπιστευτήρια, τραπεζικά στοιχεία και ενδείξεις εμπιστευτικών αρχείων. Τα αμφίσημα κείμενα ταξινομούνται με τοπικό μοντέλο zero-shot.",
        "Source code is allowed by default. An administrator can switch on code blocking for an individual member in Settings without changing anyone else’s policy.": "Από προεπιλογή ο πηγαίος κώδικας επιτρέπεται. Στις Ρυθμίσεις ο διαχειριστής μπορεί να τον αποκλείσει για συγκεκριμένο μέλος χωρίς να αλλάξει την πολιτική άλλου μέλους.",
        "Instructions trying to override the model's rules, jailbreaks, and payloads hidden inside code comments.": "Οδηγίες παράκαμψης των κανόνων του μοντέλου και κρυφές εντολές μέσα σε σχόλια κώδικα.",
        "The scanner examines adjacent lines, Python, SQL and JavaScript comments, block and HTML comments, quoted strings and docstrings.": "Ο έλεγχος εξετάζει γειτονικές γραμμές, σχόλια Python, SQL, JavaScript και HTML, σχόλια πολλών γραμμών, συμβολοσειρές και docstrings.",
        "Type in the top bar to highlight matches or open a result from another chat": "Πληκτρολογήστε στην επάνω γραμμή για επισήμανση ή για άνοιγμα αποτελέσματος από άλλη συνομιλία",
        "Edit a message": "Επεξεργασία μηνύματος",
        "Pencil icon under a message you sent": "Το εικονίδιο μολυβιού κάτω από μήνυμά σας",
        "Delete a message": "Διαγραφή μηνύματος",
        "Bin icon under a message": "Το εικονίδιο κάδου κάτω από το μήνυμα",
        "Regenerate an answer": "Νέα απάντηση",
        "Circular arrow icon, when a reply exists": "Το κυκλικό βέλος όταν υπάρχει απάντηση",
        "Send anyway": "Αποστολή παρά τον αποκλεισμό",
        "On a blocked card — needs the administrator password": "Στην κάρτα αποκλεισμού, με τον κωδικό διαχειριστή",
        "Keyboard": "Πληκτρολόγιο",
        "Send the message": "Αποστολή του μηνύματος",
        "New line inside the message": "Νέα γραμμή στο μήνυμα",
        "Clear the chat search box": "Καθαρισμός πεδίου αναζήτησης συνομιλίας",
        "Two-step sign-in: the administrator signs in first, then picks which team member to work as.": "Σύνδεση σε δύο βήματα: πρώτα συνδέεται ο διαχειριστής και έπειτα επιλέγεται ο λογαριασμός μέλους.",
        "Adds and removes members, sets policy, approves overrides, sees statistics and the roster": "Προσθέτει και αφαιρεί μέλη, ορίζει πολιτική, εγκρίνει εξαιρέσεις και βλέπει στατιστικά και κατάλογο μελών",
        "Team member": "Μέλος ομάδας",
        "Their own chats, their own settings. Statistics and the roster are not shown to members": "Έχει τις δικές του συνομιλίες και ρυθμίσεις. Τα στατιστικά και ο κατάλογος δεν εμφανίζονται στα μέλη",
        "A member's session only ever reads that member's own chats. Opening another member's chat is refused by the server, not merely hidden in the interface.": "Η συνεδρία ενός μέλους διαβάζει μόνο τις δικές του συνομιλίες. Η πρόσβαση σε συνομιλία άλλου μέλους απορρίπτεται από τον διακομιστή.",
        "Inspection itself": "Ο ίδιος ο έλεγχος",
        "Detected items": "Στοιχεία που εντοπίστηκαν",
        "Matching snippets are returned to the sender for editing, never stored in the block or activity log as block evidence": "Τα αποσπάσματα επιστρέφονται στον αποστολέα για διόρθωση· δεν αποθηκεύονται ως τεκμήρια αποκλεισμού στα αρχεία συμβάντων ή δραστηριότητας",
        "The gate fails closed: if a scanner errors, times out or returns no verdict, the prompt is refused rather than forwarded. You will see an error naming the check instead of a reply.": "Αν κάποιος έλεγχος αποτύχει, λήξει η προθεσμία ή δεν υπάρξει αποτέλεσμα, η πύλη δεν προωθεί το μήνυμα. Αντί για απάντηση εμφανίζεται το όνομα του ελέγχου που απέτυχε.",
        "This is deliberate. A gateway that waves traffic through when it is unwell is worse than no gateway, because it looks like protection while providing none.": "Αυτό είναι σκόπιμο: μια πύλη που προωθεί μηνύματα ενώ δυσλειτουργεί δίνει ψευδή αίσθηση προστασίας.",
        "Chats and messages": "Συνομιλίες και μηνύματα",
        "SQLite, on the server": "Σε βάση SQLite στον διακομιστή",
        "Provider API keys": "Κλειδιά API παρόχων",
        "Encrypted at rest (Fernet), shown masked": "Κρυπτογράφηση κατά την αποθήκευση (Fernet), εμφάνιση με απόκρυψη",
        "Passwords": "Κωδικοί πρόσβασης",
        "Hashed — never stored in a readable form": "Αποθηκεύονται ως κατακερματισμένες τιμές, όχι σε αναγνώσιμη μορφή",
        "Block log": "Αρχείο αποκλεισμών",
        "Stage and category, with a timestamp": "Στάδιο και κατηγορία με χρονική σήμανση",
        "Sessions": "Συνεδρίες",
        "HttpOnly session cookies; server-side expiry and revocation": "Cookies συνεδρίας HttpOnly· λήξη και ανάκληση στον διακομιστή",
        "Discovery contacts the selected provider. Deleting a chat removes its messages, not audit events. Prompt previews are off by default and never recorded for blocked or overridden sends.": "Η ανίχνευση επικοινωνεί με τον επιλεγμένο πάροχο. Η διαγραφή συνομιλίας διαγράφει τα μηνύματα, όχι τα συμβάντα ελέγχου. Οι προεπισκοπήσεις είναι ανενεργές από προεπιλογή και δεν καταγράφονται ποτέ για αποκλεισμούς ή κατ’ εξαίρεση αποστολές.",
        "Every setting has a default; set an environment variable only when you need to override it.": "Κάθε ρύθμιση έχει προεπιλογή. Ορίστε μεταβλητή περιβάλλοντος μόνο αν θέλετε να την αλλάξετε.",
        "Bind address — default 127.0.0.1:5000": "Διεύθυνση ακρόασης — προεπιλογή 127.0.0.1:5000",
        "Where the SQLite database lives": "Διαδρομή της βάσης SQLite",
        "The Fernet key that decrypts stored API keys. Without it, a fresh key is generated and saved": "Κλειδί Fernet για τα αποθηκευμένα κλειδιά API. Αν λείπει, δημιουργείται και αποθηκεύεται νέο",
        "Seconds to wait for the provider — default 60": "Αναμονή παρόχου σε δευτερόλεπτα — προεπιλογή 60",
        "Seconds to wait for a scanner — default 60": "Αναμονή ελέγχου σε δευτερόλεπτα — προεπιλογή 60",
        "Set to 0 to disable subprocess fallback. In-process scanning is always tried first.": "Με 0 απενεργοποιείται η εφεδρική διεργασία. Πρώτα επιχειρείται πάντα έλεγχος στην κύρια διεργασία.",
        "Enabled by default. Set to 0 to skip background warm-up.": "Ενεργό από προεπιλογή. Με 0 παραλείπεται η προφόρτωση στο παρασκήνιο.",
        "Path to the encryption key file; a separate secrets volume in Docker": "Διαδρομή του αρχείου κλειδιού· στο Docker αποθηκεύεται σε ξεχωριστό τόμο",
        "Registration token for additional administrators": "Κωδικός εγγραφής για επιπλέον διαχειριστές",
        "Maximum prompt or edit length; default 16000 characters": "Μέγιστο μήκος μηνύματος ή διόρθωσης· προεπιλογή 16000 χαρακτήρες",
        "Set to 1 to include short previews of ordinary messages in the activity log": "Με 1 καταγράφονται σύντομες προεπισκοπήσεις κανονικών μηνυμάτων στο αρχείο δραστηριότητας",
        "Seconds shared by all enabled checks; default 45": "Κοινή προθεσμία για τους ενεργούς ελέγχους σε δευτερόλεπτα· προεπιλογή 45",
        "Flask debug mode — leave off in production": "Λειτουργία αποσφαλμάτωσης Flask — απενεργοποιημένη σε παραγωγή",
        "“No usable models” when refreshing models": "«Δεν υπάρχουν διαθέσιμα μοντέλα» κατά την ανανέωση",
        "The key was accepted but no chat-capable model came back. Check the key has access to a chat model on that provider, and that the provider is reachable from the server.": "Το κλειδί έγινε δεκτό αλλά δεν επιστράφηκε μοντέλο συνομιλίας. Ελέγξτε τα δικαιώματα του κλειδιού και τη σύνδεση του διακομιστή με τον πάροχο.",
        "Model discovery names the wrong provider": "Η ανίχνευση υποδεικνύει λάθος πάροχο",
        "Automatic discovery uses recognized key prefixes only. Select your provider explicitly for unfamiliar or ambiguous formats; your key is not tried against unrelated services.": "Η αυτόματη ανίχνευση βασίζεται μόνο σε γνωστά προθέματα. Για άγνωστες ή αμφίσημες μορφές επιλέξτε πάροχο· το κλειδί δεν δοκιμάζεται σε άσχετες υπηρεσίες.",
        "Every message is refused": "Όλα τα μηνύματα απορρίπτονται",
        "That is the gate failing closed. The check named in the error is the one that could not run — usually a model that failed to load.": "Η πύλη δεν προωθεί μηνύματα χωρίς επιτυχή έλεγχο. Το σφάλμα κατονομάζει τον έλεγχο που δεν εκτελέστηκε· συχνά δεν φορτώθηκε κάποιο μοντέλο.",
        "The first message is slow": "Το πρώτο μήνυμα καθυστερεί",
        "Background warm-up is enabled by default. Set CYBERSYN_WARM_MODELS=0 only if you prefer loading models on first use.": "Η προφόρτωση στο παρασκήνιο είναι ενεργή από προεπιλογή. Ορίστε CYBERSYN_WARM_MODELS=0 μόνο αν προτιμάτε φόρτωση κατά την πρώτη χρήση.",
        "Statistics will not load": "Δεν φορτώνονται τα στατιστικά",
        "Statistics are for administrators. Sign in as the administrator, then open the page.": "Τα στατιστικά προορίζονται για διαχειριστές. Ανοίξτε τη σελίδα και επιβεβαιώστε την πρόσβαση ως διαχειριστής.",
        "CyberSyn is built on other people's work. This is what each part is licensed under.": "Το CyberSyn βασίζεται σε έργα τρίτων. Ακολουθούν οι αντίστοιχες άδειες χρήσης.",
        "The application": "Η εφαρμογή",
        "No licence declared yet.": "Δεν έχει δηλωθεί άδεια χρήσης.",
        "This repository does not carry a": "Δεν υπάρχει αρχείο",
        "file, so in law the default applies: all rights reserved. If you intend to publish or distribute CyberSyn, add one — the dependency licences below are all permissive except where noted, so MIT, Apache-2.0 or BSD-3-Clause would each be a straightforward choice.": "στο αποθετήριο, επομένως διατηρούνται όλα τα δικαιώματα. Αν πρόκειται να δημοσιεύσετε ή να διανείμετε το CyberSyn, προσθέστε άδεια. Οι άδειες εξαρτήσεων είναι γενικά επιτρεπτικές, με τις εξαιρέσεις που αναφέρονται παρακάτω.",
        "Runtime dependencies": "Εξαρτήσεις εκτέλεσης",
        "Component": "Στοιχείο",
        "Licence": "Άδεια χρήσης",
        "Notes": "Σημειώσεις",
        "Web framework": "Πλαίσιο ανάπτυξης εφαρμογών ιστού",
        "Threaded production WSGI server": "Πολυνηματικός διακομιστής WSGI για παραγωγή",
        "WSGI toolkit under Flask": "Εργαλειοθήκη WSGI στην οποία βασίζεται το Flask",
        "Provider-agnostic model calls. The": "Κλήσεις μοντέλων ανεξάρτητα από τον πάροχο. Ο κατάλογος",
        "directory is separately licensed and is not used here": "έχει ξεχωριστή άδεια και δεν χρησιμοποιείται εδώ",
        "Your choice of either; Fernet key encryption": "Επιλογή μίας από τις δύο άδειες· κρυπτογράφηση κλειδιών με Fernet",
        "Name recognition": "Αναγνώριση ονομάτων",
        "Zero-shot classification": "Ταξινόμηση zero-shot",
        "Model runtime (CPU build)": "Περιβάλλον εκτέλεσης μοντέλων για CPU",
        "Models": "Μοντέλα",
        "English names": "Αγγλικά ονόματα",
        "Non-commercial.": "Μη εμπορική χρήση.",
        "Greek names. Read this one before any commercial deployment — it is the only component here that restricts commercial use, and it restricts derivative works too. A commercially licensed Greek NER model would replace it": "Ελληνικά ονόματα. Ελέγξτε αυτή την άδεια πριν από εμπορική χρήση. Περιορίζει την εμπορική χρήση και τα παράγωγα έργα. Για εμπορική εγκατάσταση μπορεί να αντικατασταθεί από κατάλληλα αδειοδοτημένο ελληνικό μοντέλο NER",
        "Confidential-context classification; derived from": "Ταξινόμηση εμπιστευτικού περιεχομένου· βασίζεται στο",
        ". Confirm on the model card before redistributing": ". Ελέγξτε την καρτέλα του μοντέλου πριν από αναδιανομή",
        "Fonts and icons": "Γραμματοσειρές και εικονίδια",
        "Inter, Instrument Serif and JetBrains Mono are each licensed under the SIL Open Font License 1.1 and are served locally. No font CDN is contacted. The interface icons in": "Οι Inter, Instrument Serif και JetBrains Mono διατίθενται με άδεια SIL Open Font License 1.1 και φορτώνονται τοπικά, χωρίς σύνδεση σε CDN. Τα εικονίδια στον κατάλογο",
        "are drawn for this project and follow the application's licence.": "σχεδιάστηκαν για αυτό το έργο και καλύπτονται από την άδεια της εφαρμογής.",
        "Licence identifiers were checked against each project's own licence file. They are recorded here for information, not as legal advice — take your own advice before distributing.": "Οι άδειες ελέγχθηκαν στα αρχεία των αντίστοιχων έργων. Οι πληροφορίες δεν αποτελούν νομική συμβουλή· ζητήστε δική σας συμβουλή πριν από διανομή.",
        "Administrator approval": "Έγκριση διαχειριστή",
        "Approve & send": "Έγκριση και αποστολή",
        "Unlock": "Ξεκλείδωμα",
        "Approve": "Έγκριση",
        "Lock now": "Κλείδωμα τώρα",
        "Back to chat": "Επιστροφή στη συνομιλία",
        "Enter the administrator username.": "Πληκτρολογήστε το όνομα χρήστη του διαχειριστή.",
        "Enter the administrator password.": "Πληκτρολογήστε τον κωδικό διαχειριστή.",
        "Administrator unlocked ·": "Πρόσβαση διαχειριστή ·",
        "Forget the administrator password for now": "Τερματισμός πρόσβασης διαχειριστή",
        "Administrator access locked.": "Η πρόσβαση διαχειριστή κλειδώθηκε.",
        "Unsaved changes": "Μη αποθηκευμένες αλλαγές",
        "Safety checks saved.": "Οι έλεγχοι αποθηκεύτηκαν.",
        "Connection saved.": "Η σύνδεση αποθηκεύτηκε.",
        "Both fields are required.": "Συμπληρώστε και τα δύο πεδία.",
        "Username updated.": "Το όνομα χρήστη ενημερώθηκε.",
        "Password updated.": "Ο κωδικός ενημερώθηκε.",
        "Administrator password updated. Previous sessions have ended.": "Ο κωδικός διαχειριστή ενημερώθηκε. Οι προηγούμενες συνεδρίες έληξαν.",
        "Invalid username or password.": "Λανθασμένο όνομα χρήστη ή κωδικός.",
        "Language": "Γλώσσα",
        "No conversations yet.": "Δεν υπάρχουν ακόμη συνομιλίες.",
        "You": "Εσείς",
        "Checking for personal and Greek identifiers": "Έλεγχος προσωπικών και ελληνικών αναγνωριστικών",
        "Checking for confidential context": "Έλεγχος εμπιστευτικού περιεχομένου",
        "Checking for prompt injection": "Έλεγχος για κρυφές εντολές",
        "Checking the message": "Έλεγχος του μηνύματος",
        "Thinking": "Επεξεργασία",
        "Sending with approval": "Αποστολή με έγκριση",
        "Waiting for the model": "Αναμονή απάντησης μοντέλου",
        "Check 1 looks for personal identifiers and Greek ID numbers.": "Ο έλεγχος 1 εντοπίζει προσωπικά και ελληνικά αναγνωριστικά.",
        "Check 2 looks for confidential company material.": "Ο έλεγχος 2 εντοπίζει εμπιστευτικό εταιρικό υλικό.",
        "Check 3 looks for instructions aimed at the model itself.": "Ο έλεγχος 3 εντοπίζει οδηγίες προς το ίδιο το μοντέλο.",
        "A local check matched this message.": "Ένας τοπικός έλεγχος εντόπισε εύρημα στο μήνυμα.",
        "the safety checks": "τους ελέγχους ασφαλείας",
        "the AI connection": "τη σύνδεση με το AI",
        "Confidential contracts, internal financials, HR and payroll records, and credentials": "Εμπιστευτικές συμβάσεις, εσωτερικά οικονομικά στοιχεία, αρχεία προσωπικού και μισθοδοσίας, διαπιστευτήρια",
        "Also save this connection, including its key, as the default for new team members": "Αποθήκευση της σύνδεσης μαζί με το κλειδί της ως προεπιλογής για νέα μέλη",
        "Refresh the list with administrator approval to use the saved key here.": "Για χρήση του αποθηκευμένου κλειδιού εδώ, ανανεώστε τη λίστα με έγκριση διαχειριστή.",
        "Chat history is deleted; statistics and audit events are retained.": "Το ιστορικό συνομιλιών διαγράφεται· τα στατιστικά και τα συμβάντα ελέγχου διατηρούνται.",
        "What stays local": "Τι παραμένει τοπικά",
        "Member sign-in ends the browser’s administrator session. A single-use approval lasts five minutes. A read-only page unlock lasts fifteen minutes; Lock now revokes it on the server.": "Η σύνδεση μέλους τερματίζει τη συνεδρία του διαχειριστή στον περιηγητή. Η έγκριση μίας χρήσης ισχύει για πέντε λεπτά. Το ξεκλείδωμα σελίδας επιτρέπει μόνο ανάγνωση για δεκαπέντε λεπτά. Το «Κλείδωμα τώρα» ανακαλεί την πρόσβαση στον διακομιστή.",
        "Screened locally; allowed prompts are sent to the selected provider": "Ελέγχονται τοπικά· τα επιτρεπόμενα μηνύματα αποστέλλονται στον επιλεγμένο πάροχο",
        "Stored encrypted; used to authenticate to the selected provider": "Αποθηκεύεται κρυπτογραφημένο και χρησιμοποιείται για την ταυτοποίηση στον επιλεγμένο πάροχο",
        "Not sent unless a workspace administrator approves an exception": "Δεν αποστέλλονται χωρίς ρητή έγκριση εξαίρεσης από τον διαχειριστή",
        "Fallback can start one subprocess if a scanner cannot be imported. It is off in Docker. A scanner that throws at runtime fails closed.": "Αν δεν είναι δυνατή η εισαγωγή ενός σαρωτή, επιτρέπεται μία εφεδρική διεργασία. Στο Docker είναι απενεργοποιημένη. Σφάλμα κατά τον έλεγχο εμποδίζει την αποστολή.",
        "Gunicorn uses one worker and eight threads by default": "Από προεπιλογή το Gunicorn χρησιμοποιεί μία διεργασία με οκτώ νήματα",
        "Set to 0 to refuse LAN and loopback provider destinations; metadata addresses are always refused": "Με 0 απορρίπτονται προορισμοί LAN και loopback· οι διευθύνσεις υπηρεσιών μεταδεδομένων απορρίπτονται πάντα",
        "Set to 1 when terminating HTTPS at a trusted reverse proxy": "Ορίστε 1 όταν η σύνδεση HTTPS τερματίζεται σε έμπιστο αντίστροφο διαμεσολαβητή",
        "Maximum JSON body size; default 256 KiB": "Μέγιστο μέγεθος σώματος JSON· προεπιλογή 256 KiB",
        "Failed credential attempts are limited per IP and username; enabled by default": "Οι αποτυχημένες προσπάθειες σύνδεσης περιορίζονται ανά IP και όνομα χρήστη· ενεργό από προεπιλογή",
        "Trust forwarded client IPs only behind a proxy that replaces the header; off by default": "Εμπιστευτείτε προωθημένες IP πελατών μόνο πίσω από διαμεσολαβητή που αντικαθιστά την κεφαλίδα· ανενεργό από προεπιλογή",
        "Set to 1 only to allow unrestricted administrator signup": "Ορίστε 1 μόνο αν θέλετε ελεύθερη εγγραφή διαχειριστών",
        "Administrator approval was cancelled.": "Η έγκριση διαχειριστή ακυρώθηκε.",
        "Administrator created. Sign in with it now.": "Ο λογαριασμός διαχειριστή δημιουργήθηκε. Συνδεθείτε με αυτόν.",
        "Administrator deleted.": "Ο λογαριασμός διαχειριστή διαγράφηκε.",
        "Answer regenerated.": "Δημιουργήθηκε νέα απάντηση.",
        "Answer regenerated": "Νέα απάντηση",
        "Chat deleted.": "Η συνομιλία διαγράφηκε.",
        "Chat deleted": "Διαγραφή συνομιλίας",
        "Chat renamed.": "Η συνομιλία μετονομάστηκε.",
        "Chat started": "Έναρξη συνομιλίας",
        "Choose a username.": "Επιλέξτε όνομα χρήστη.",
        "Copied to clipboard.": "Αντιγράφηκε στο πρόχειρο.",
        "Could not copy.": "Η αντιγραφή απέτυχε.",
        "Delete this chat? Its messages are removed. Team statistics are kept.": "Να διαγραφεί η συνομιλία; Τα μηνύματά της θα διαγραφούν. Τα στατιστικά της ομάδας διατηρούνται.",
        "Delete this message? It is removed from the chat history.": "Να διαγραφεί το μήνυμα από το ιστορικό συνομιλίας;",
        "Enter that account's password.": "Πληκτρολογήστε τον κωδικό του λογαριασμού.",
        "Enter the member to remove.": "Εισαγάγετε το μέλος προς αφαίρεση.",
        "Enter the team member's username and password.": "Πληκτρολογήστε το όνομα και τον κωδικό του μέλους.",
        "Enter the username to delete.": "Πληκτρολογήστε το όνομα χρήστη προς διαγραφή.",
        "Enter your username and password.": "Πληκτρολογήστε το όνομα χρήστη και τον κωδικό σας.",
        "Enter a password.": "Πληκτρολογήστε έναν κωδικό.",
        "Message deleted": "Διαγραφή μηνύματος",
        "Message deleted.": "Το μήνυμα διαγράφηκε.",
        "Message edited": "Επεξεργασία μηνύματος",
        "Message sent": "Αποστολή μηνύματος",
        "Message updated.": "Το μήνυμα ενημερώθηκε.",
        "No activity recorded yet. Steps appear here as members use the workspace.": "Δεν έχει καταγραφεί ακόμη δραστηριότητα. Οι ενέργειες των μελών θα εμφανίζονται εδώ.",
        "No team members yet. Add one from the sign-in screen.": "Δεν υπάρχουν ακόμη μέλη. Προσθέστε ένα από την οθόνη σύνδεσης.",
        "Nothing recorded yet. Messages that trip a check will appear here.": "Δεν υπάρχει ακόμη καταγραφή. Εδώ θα εμφανιστούν τα μηνύματα που ενεργοποιούν έλεγχο.",
        "Nothing to save yet.": "Δεν υπάρχει κάτι προς αποθήκευση.",
        "Override approved": "Έγκριση εξαίρεσης",
        "Policy changed": "Αλλαγή πολιτικής",
        "Signed in": "Σύνδεση",
        "Signed out": "Αποσύνδεση",
        "That key returned no usable models.": "Το κλειδί δεν επέστρεψε διαθέσιμα μοντέλα.",
        "That password was not accepted.": "Ο κωδικός δεν έγινε δεκτός.",
        "The message cannot be empty.": "Το μήνυμα δεν μπορεί να είναι κενό.",
        "The new password must differ from the current one.": "Ο νέος κωδικός πρέπει να διαφέρει από τον τρέχοντα.",
        "The request took too long. Try again.": "Το αίτημα καθυστέρησε υπερβολικά. Δοκιμάστε ξανά.",
        "This chat has not been saved yet.": "Αυτή η συνομιλία δεν έχει αποθηκευτεί ακόμη.",
        "Those passwords do not match.": "Οι κωδικοί δεν ταιριάζουν.",
        "Your session has ended. Sign in again.": "Η συνεδρία σας έληξε. Συνδεθείτε ξανά.",
        "just now": "μόλις τώρα",
        "not set": "δεν έχει οριστεί",
        "This page": "Αυτή η σελίδα",
        "Write a message below. Your enabled checks run here before the prompt is sent to the provider.": "Γράψτε ένα μήνυμα παρακάτω. Πριν από την αποστολή στον πάροχο εφαρμόζονται οι ενεργοί τοπικοί έλεγχοι.",
        "Nothing left this machine. The message was screened on this computer, matched a rule, and was refused before it reached any AI provider.": "Δεν στάλθηκε τίποτα στον πάροχο. Το μήνυμα ελέγχθηκε τοπικά και αποκλείστηκε επειδή ενεργοποίησε έναν κανόνα.",
        "Invalid employee username or password.": "Λάθος όνομα χρήστη ή κωδικός μέλους.",
        "Current password is incorrect.": "Ο τρέχων κωδικός δεν είναι σωστός.",
        "Invalid administrator password.": "Ο κωδικός διαχειριστή δεν είναι σωστός.",
        "Too many attempts. Try again later.": "Πάρα πολλές προσπάθειες. Δοκιμάστε ξανά αργότερα.",
        "Member password must be at least 8 characters.": "Ο κωδικός μέλους πρέπει να έχει τουλάχιστον 8 χαρακτήρες.",
        "Member password must include at least one number.": "Ο κωδικός μέλους πρέπει να περιέχει τουλάχιστον ένα ψηφίο.",
        "Member password must include at least one letter.": "Ο κωδικός μέλους πρέπει να περιέχει τουλάχιστον ένα γράμμα.",
        "That member username is already taken.": "Το όνομα μέλους χρησιμοποιείται ήδη.",
        "That username is already taken.": "Το όνομα χρήστη χρησιμοποιείται ήδη.",
        "Changing these settings needs the administrator password.": "Η αλλαγή αυτών των ρυθμίσεων απαιτεί τον κωδικό διαχειριστή.",
        "Check the saved provider and its base URL in Settings.": "Ελέγξτε τον αποθηκευμένο πάροχο και τη βασική του διεύθυνση στις Ρυθμίσεις.",
        "Select a provider supported by this gateway.": "Επιλέξτε έναν από τους υποστηριζόμενους παρόχους.",
        "Paste an API key first.": "Επικολλήστε πρώτα ένα κλειδί API.",
        "Save this HTTP base with administrator approval first.": "Αποθηκεύστε πρώτα τη διεύθυνση HTTP με έγκριση διαχειριστή.",
        "AI API Error: the provider request failed. Check the saved key, model and base URL.": "Το αίτημα προς τον πάροχο απέτυχε. Ελέγξτε το αποθηκευμένο κλειδί, το μοντέλο και τη βασική διεύθυνση.",
        "Check model card": "Δείτε την κάρτα του μοντέλου",
        "Classification weights derived from": "Βάρη ταξινόμησης που προέρχονται από το",
        "Check the upstream licence for each exact package or model version before redistributing it. A library licence does not automatically cover its model weights.": "Ελέγξτε την άδεια της συγκεκριμένης έκδοσης κάθε πακέτου ή μοντέλου πριν από αναδιανομή. Η άδεια μιας βιβλιοθήκης δεν καλύπτει αυτομάτως τα βάρη των μοντέλων της.",
        "Model discovery": "Αναζήτηση μοντέλων",
        "the saved key": "το αποθηκευμένο κλειδί",
        "This page shows team activity, blocks and trends. Enter the administrator password to open it.": "Αυτή η σελίδα εμφανίζει δραστηριότητα, αποκλεισμούς και τάσεις της ομάδας. Πληκτρολογήστε τον κωδικό διαχειριστή.",
        "This page shows every member and how their gate is configured. Enter the administrator password to open it.": "Αυτή η σελίδα εμφανίζει τα μέλη και τις ρυθμίσεις τους. Πληκτρολογήστε τον κωδικό διαχειριστή.",
        "Asking the provider which models this key can reach…": "Αναζήτηση διαθέσιμων μοντέλων για αυτό το κλειδί…"
    };

    /* Strings that embed a number or a name cannot be exact-matched. */
    var PATTERNS = [
        [/^(.+) — CyberSyn$/, function (_, name) { return t(name) + " — CyberSyn"; }],
        [/^Welcome back, (.+)\.$/, "Καλώς ήρθες ξανά, $1."],
        [/^(.+) can sign in now\.$/, "Ο χρήστης $1 μπορεί πλέον να συνδεθεί."],
        [/^(.+) was removed\.$/, "Αφαιρέθηκε το μέλος $1."],
        [/^Member since (.+)$/, "Μέλος από $1"],
        [/^(.+) · today$/, "$1 · σήμερα"],
        [/^(\d+) (second|minute|hour|day|week|month|year)s? ago$/, function (_, n, unit) {
            var units = {second:"δευτ.", minute:"λεπτά", hour:"ώρες", day:"μέρες", week:"εβδομάδες", month:"μήνες", year:"χρόνια"};
            return "πριν από " + n + " " + units[unit];
        }],
        [/^(\d+) of (\d+) messages blocked$/, "Αποκλείστηκαν $1 από $2 μηνύματα"],
        [/^Nothing in this chat contains "(.+)"\.$/, "Δεν βρέθηκε το «$1» σε αυτή τη συνομιλία."],
        [/^Not sent — stopped by (.+)$/, function (_, stage) { return "Δεν στάλθηκε — αποκλείστηκε από τον έλεγχο: " + t(stage); }],
        [/^line (\d+)$/, "γραμμή $1"],
        [/^(.+)…$/, function (m, label) { return t(label) + "…"; }],
        [/^Check (\d) · (.+)$/, function (m, n, label) { return "Έλεγχος " + n + " · " + t(label); }],
        [/^(.*?\.) It stopped on (.+?)(?: at line (\d+))?\.$/, function (m, why, cause, line) {
            return t(why) + " Εύρημα: " + cause + (line ? " στη γραμμή " + line : "") + ".";
        }],
        [/^(.+) needs the administrator password$/, function (m, action) { return t(action) + " — απαιτείται κωδικός διαχειριστή"; }],
        [/^Changing (.+) needs the administrator password\. It is recorded in the audit trail\.$/, function (m, what) {
            return "Για να αλλάξετε " + t(what) + " απαιτείται κωδικός διαχειριστή. Η αλλαγή καταγράφεται.";
        }],
        [/^Change (the .+)$/, function (m, what) { return "Αλλάξτε " + t(what); }],
        [/^(\d+) min$/, "$1 λεπτά"],
        [/^Use the saved key at (.+) · (.+)\?$/, function (_, provider, base) { return "Χρήση του αποθηκευμένου κλειδιού στο " + provider + " · " + (base === "hosted address" ? "διεύθυνση παρόχου" : base) + ";"; }],
        [/^Replace saved key (.+)$/, "Αντικατάσταση αποθηκευμένου κλειδιού $1"],
        [/^(\d+) models? on (.+)\.$/, function (_, n, provider) { return n + (n === "1" ? " μοντέλο" : " μοντέλα") + " · " + provider; }],
        [/^Password for (.+)$/, "Κωδικός για $1"],
        [/^Workspace (\d+)$/, "Χώρος εργασίας $1"],
        [/^(\d+) of (\d+)$/, "$1 από $2"],
        [/^Saved key: (.+) — paste a new one to replace it\.$/, "Αποθηκευμένο κλειδί: $1 — επικολλήστε νέο για αντικατάσταση."],
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

    /** Translate one string. Preserves the original when there is no translation. */
    function t(text) {
        if (current() !== "el") return text;
        var source = String(text == null ? "" : text);
        var trimmed = source.trim();
        var core = trimmed.replace(/\s+/g, " ");
        if (!core) return source;

        var out = null;
        if (Object.prototype.hasOwnProperty.call(EXACT, core)) {
            out = EXACT[core];
        } else {
            for (var i = 0; i < PATTERNS.length && out === null; i++) {
                if (PATTERNS[i][0].test(trimmed)) out = trimmed.replace(PATTERNS[i][0], PATTERNS[i][1]);
            }
        }
        if (out === null || out === core) return source;

        // Keep the leading and trailing whitespace the node had.
        return source.replace(source.trim(), function () { return out; });
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
        if (isUntranslatedElement(el) || !el.hasAttribute || !el.hasAttribute(name)) return;
        var out = t(el.getAttribute(name));
        if (out !== el.getAttribute(name)) setAttr(el, name, out);
    }

    function translateNode(node) {
        if (node.nodeType === 1) {  // element
            if (isUntranslatedElement(node)) return;
            ATTRS.forEach(function (name) { translateAttr(node, name); });
            Array.prototype.slice.call(node.childNodes).forEach(translateNode);
            return;
        }
        if (node.nodeType === 3) {  // text
            var parent = node.parentNode;
            if (!parent || parent.nodeName === "TEXTAREA" || parent.nodeName === "INPUT" || isUntranslatedElement(parent)) return;
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
        if (code === "el") apply();
        else restore();
        paintButtons();
    }

    /** Translate the whole page. Safe to call again after inserting markup. */
    function apply() {
        if (current() === "el") {
            translateNode(global.document.body);
            var title = global.document.querySelector("title");
            if (title) translateNode(title);
        }
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
