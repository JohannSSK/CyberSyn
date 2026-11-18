/* ==========================================================================
   core/i18n.js — English / Greek interface language toggle.

   Every page in CyberSyn is authored in plain colleague-like English. When
   the visitor chooses Greek, this module translates visible copy, dynamic
   messages, form placeholders, accessible labels and document titles on the
   fly, keeps original English text on each DOM node so switching back is
   exact, and remembers the choice in localStorage ("cybersyn_lang").

   Dispatches "cybersyn:lang" on document whenever the language changes so
   data-driven screens (workspace, statistics, team, settings, account) can
   re-render counts, dates and dynamic strings cleanly.
   ========================================================================== */

(function (global) {
    "use strict";

    var STORAGE_KEY = "cybersyn_lang";
    var DEFAULT = "en";

    /* ----------------------------------------------------------------------
       Greek dictionary — keyed by exact trimmed English text.
       Technical terms that Greek professionals use naturally stay direct
       (ΑΦΜ / AFM, ΑΜΚΑ / AMKA, IBAN, API, model / μοντέλο, provider / πάροχος,
       prompt injection, CSV, UTC). Zero emoji, zero hype adjectives.
       ---------------------------------------------------------------------- */
    var EL = {
        // ---- Page titles ----
        "Sign in — CyberSyn": "Σύνδεση — CyberSyn",
        "Workspace — CyberSyn": "Χώρος εργασίας — CyberSyn",
        "Settings — CyberSyn": "Ρυθμίσεις — CyberSyn",
        "Account — CyberSyn": "Λογαριασμός — CyberSyn",
        "Profile — CyberSyn": "Προφίλ — CyberSyn",
        "Statistics — CyberSyn": "Στατιστικά — CyberSyn",
        "Team — CyberSyn": "Ομάδα — CyberSyn",
        "Help — CyberSyn": "Βοήθεια — CyberSyn",
        "Create administrator — CyberSyn": "Δημιουργία διαχειριστή — CyberSyn",
        "Delete administrator — CyberSyn": "Διαγραφή διαχειριστή — CyberSyn",
        "Add team member — CyberSyn": "Προσθήκη μέλους — CyberSyn",
        "Remove team member — CyberSyn": "Αφαίρεση μέλους — CyberSyn",

        // ---- Navigation, sidebar & language ----
        "Workspace navigation": "Πλοήγηση χώρου εργασίας",
        "Chat": "Συνομιλία",
        "Profile": "Λογαριασμός",
        "Account": "Λογαριασμός",
        "Help": "Βοήθεια",
        "Help & info": "Βοήθεια & απόρρητο",
        "Administrator": "Διαχειριστής",
        "Admin": "Διαχειριστής",
        "Settings": "Ρυθμίσεις",
        "Statistics": "Στατιστικά",
        "Team": "Ομάδα",
        "Sign out": "Αποσύνδεση",
        "Toggle sidebar": "Εναλλαγή πλευρικής στήλης",
        "Toggle navigation": "Εναλλαγή μενού",
        "Member": "Μέλος",
        "Member —": "Μέλος —",
        "Workspace": "Χώρος εργασίας",
        "Workspace —": "Χώρος εργασίας —",
        "Administrator-managed workspace": "Χώρος υπό διαχείριση οργανισμού",
        "Administrator unlocked": "Πρόσβαση διαχειριστή ενεργή",
        "Lock": "Κλείδωμα",
        "Lock now": "Κλείδωμα τώρα",
        "Lock administrator access now": "Άμεσο κλείδωμα πρόσβασης διαχειριστή",
        "Administrator access locked.": "Η πρόσβαση διαχειριστή κλειδώθηκε.",
        "Switch language": "Αλλαγή γλώσσας",
        "Language": "Γλώσσα",
        "Signed out.": "Αποσυνδεθήκατε.",
        "This tab can be closed safely.": "Μπορείτε να κλείσετε αυτή την καρτέλα με ασφάλεια.",

        // ---- Common controls & modals ----
        "Continue": "Συνέχεια",
        "Cancel": "Ακύρωση",
        "Confirm": "Επιβεβαίωση",
        "Save": "Αποθήκευση",
        "Save title": "Αποθήκευση τίτλου",
        "Save settings": "Αποθήκευση ρυθμίσεων",
        "Refresh": "Ανανέωση",
        "Download CSV": "Λήψη CSV",
        "Unlock": "Ξεκλείδωμα",
        "Rename": "Μετονομασία",
        "Title": "Τίτλος",
        "Please confirm": "Επιβεβαίωση",
        "Are you sure?": "Θέλετε να συνεχίσετε;",
        "Back to chat": "Πίσω στη συνομιλία",
        "Back to sign in": "Πίσω στη σύνδεση",
        "You": "Εσείς",
        "edited": "επεξεργασμένο",
        "today": "σήμερα",
        "today · UTC": "σήμερα · UTC",
        "match": "εύρημα",
        "Saved": "Αποθηκευμένο",
        "saved": "αποθηκευμένο",
        "No key saved": "Χωρίς κλειδί",
        "API key saved": "Κλειδί API αποθηκευμένο",
        "no API key yet": "χωρίς κλειδί API",

        // ---- Sign-in portal ----
        "Use AI at work without exposing what matters.":
            "Χρησιμοποιήστε τεχνητή νοημοσύνη στη δουλειά χωρίς να εκθέτετε όσα μετρούν.",
        "Every message you send is checked on your own computer before an AI model ever sees it, so client and company details stay with your team.":
            "Κάθε μήνυμα ελέγχεται στον δικό σας υπολογιστή πριν το δει οποιοδήποτε μοντέλο, ώστε τα στοιχεία πελατών και εταιρείας να μένουν στην ομάδα σας.",
        "Checked on this machine": "Έλεγχος σε αυτόν τον υπολογιστή",
        "All three checks run locally. Nothing leaves for review.":
            "Και οι τρεις έλεγχοι τρέχουν τοπικά. Τίποτα δεν φεύγει για έλεγχο.",
        "Aware of Greek records": "Αναγνώριση ελληνικών στοιχείων",
        "Spots AFM, AMKA, IBANs, phone numbers, names and company details.":
            "Εντοπίζει ΑΦΜ, ΑΜΚΑ, IBAN, τηλέφωνα, ονόματα και εταιρικά στοιχεία.",
        "Guided by your administrator": "Με εποπτεία διαχειριστή",
        "Your administrator manages access, sets the checks and approves one-off exceptions.":
            "Ο διαχειριστής ορίζει την πρόσβαση, ρυθμίζει τους ελέγχους και εγκρίνει μεμονωμένες εξαιρέσεις.",
        "Self-hosted AI security gateway · Local screening":
            "Αυτοφιλοξενούμενη πύλη ασφάλειας ΤΝ · Τοπικός έλεγχος",
        "Step 1 of 2": "Βήμα 1 από 2",
        "Step 2 of 2": "Βήμα 2 από 2",
        "Administrator sign in": "Σύνδεση διαχειριστή",
        "Sign in with your administrator account to unlock this workspace.":
            "Συνδεθείτε με τον λογαριασμό διαχειριστή για να ανοίξετε τον χώρο εργασίας.",
        "Team member sign in": "Σύνδεση μέλους ομάδας",
        "Sign in with your team member account to open your chats.":
            "Συνδεθείτε με τον λογαριασμό μέλους για να ανοίξετε τις συνομιλίες σας.",
        "Username": "Όνομα χρήστη",
        "Password": "Κωδικός πρόσβασης",
        "Confirm password": "Επιβεβαίωση κωδικού",
        "Your administrator username": "Όνομα χρήστη διαχειριστή",
        "Your member username": "Όνομα χρήστη μέλους",
        "Your password": "Ο κωδικός σας",
        "Choose a username": "Επιλέξτε όνομα χρήστη",
        "Choose a password": "Επιλέξτε κωδικό",
        "Type the password again": "Πληκτρολογήστε ξανά τον κωδικό",
        "Create administrator account": "Δημιουργία διαχειριστή",
        "Delete account": "Διαγραφή λογαριασμού",
        "Signed in as administrator": "Συνδεδεμένος διαχειριστής",
        "Switch administrator": "Αλλαγή διαχειριστή",
        "Open workspace": "Άνοιγμα χώρου εργασίας",
        "Add team member": "Προσθήκη μέλους",
        "Remove team member": "Αφαίρεση μέλους",
        "Team statistics": "Στατιστικά ομάδας",
        "Every message is checked on this computer before it reaches the AI. Your words never leave first.":
            "Κάθε μήνυμα ελέγχεται σε αυτόν τον υπολογιστή πριν φτάσει στην ΤΝ. Τα λόγια σας δεν φεύγουν ποτέ πρώτα.",

        // ---- Account management pages & confirmation modals ----
        "Create account": "Δημιουργία λογαριασμού",
        "Delete this account": "Διαγραφή λογαριασμού",
        "Remove this member": "Αφαίρεση μέλους",
        "The administrator username": "Όνομα χρήστη διαχειριστή",
        "That account's password": "Κωδικός αυτού του λογαριασμού",
        "The member username": "Όνομα χρήστη μέλους",
        "That member's password": "Κωδικός αυτού του μέλους",
        "Create a new administrator account for this CyberSyn installation. Each administrator manages their own group of team members.":
            "Δημιουργήστε έναν νέο λογαριασμό διαχειριστή. Κάθε διαχειριστής διαχειρίζεται τη δική του ομάδα μελών.",
        "Delete an administrator account and remove its team member accounts. Confirm with that account's password.":
            "Διαγράψτε έναν λογαριασμό διαχειριστή και τους λογαριασμούς των μελών του. Επιβεβαιώστε με τον κωδικό του.",
        "Every team member account, setting and access to its chats under this administrator is deleted. Block and activity log rows are kept.":
            "Διαγράφονται όλοι οι λογαριασμοί μελών, οι ρυθμίσεις και η πρόσβαση στις συνομιλίες τους. Τα αρχεία αποκλεισμών και δραστηριότητας διατηρούνται.",
        "Add a team member under the administrator currently signed in. They will use these details on step 2 of the sign-in page.":
            "Προσθέστε ένα μέλος κάτω από τον συνδεδεμένο διαχειριστή. Θα συνδέεται με αυτά τα στοιχεία στο βήμα 2.",
        "Remove a team member account from this workspace. Confirm with that member's password.":
            "Αφαιρέστε έναν λογαριασμό μέλους από αυτόν τον χώρο εργασίας. Επιβεβαιώστε με τον κωδικό του μέλους.",
        "Their account, access to chats and saved settings are deleted. Block and activity log rows are kept.":
            "Ο λογαριασμός, η πρόσβαση στις συνομιλίες και οι αποθηκευμένες ρυθμίσεις διαγράφονται. Τα αρχεία αποκλεισμών και δραστηριότητας διατηρούνται.",
        "At least 8 characters, with at least one letter and one number.":
            "Τουλάχιστον 8 χαρακτήρες, με τουλάχιστον ένα γράμμα και έναν αριθμό.",
        "One administrator per workspace.": "Ένας διαχειριστής ανά χώρο εργασίας.",
        "Your administrator account holds this workspace: you add team members, choose which checks run, and approve one-off exceptions.":
            "Ο λογαριασμός διαχειριστή κρατά αυτόν τον χώρο εργασίας: προσθέτετε μέλη, επιλέγετε ποιους ελέγχους τρέχουν και εγκρίνετε μεμονωμένες εξαιρέσεις.",
        "New workspace": "Νέος χώρος εργασίας",
        "Pick a username and a password for this workspace. Store the password somewhere safe — there is no reset link on a local server.":
            "Επιλέξτε όνομα χρήστη και κωδικό για αυτόν τον χώρο εργασίας. Φυλάξτε τον κωδικό με ασφάλεια — σε τοπικό διακομιστή δεν υπάρχει σύνδεσμος επαναφοράς.",
        "Your account lives only on this computer.":
            "Ο λογαριασμός σας αποθηκεύεται μόνο σε αυτόν τον υπολογιστή.",
        "This removes the workspace.": "Αφαιρεί ολόκληρο τον χώρο εργασίας.",
        "Deleting an administrator account removes its team member accounts and settings. Block and activity logs remain in the local database.":
            "Η διαγραφή λογαριασμού διαχειριστή αφαιρεί τους λογαριασμούς και τις ρυθμίσεις των μελών του. Τα αρχεία αποκλεισμών και δραστηριότητας παραμένουν στην τοπική βάση.",
        "Delete administrator account": "Διαγραφή λογαριασμού διαχειριστή",
        "Enter the username and password of the administrator account you want to remove. You will be asked to confirm once more before anything changes.":
            "Εισαγάγετε το όνομα χρήστη και τον κωδικό του διαχειριστή που θέλετε να αφαιρέσετε. Θα ζητηθεί μία ακόμη επιβεβαίωση πριν αλλάξει οτιδήποτε.",
        "Nothing leaves this computer. Removed accounts cannot be restored.":
            "Τίποτα δεν φεύγει από αυτόν τον υπολογιστή. Οι διαγραμμένοι λογαριασμοί δεν επαναφέρονται.",
        "One seat per colleague.": "Μία θέση για κάθε συνάδελφο.",
        "Each person gets their own sign-in, private conversations, and the safety checks you set for this workspace.":
            "Κάθε μέλος έχει δική του σύνδεση, προσωπικές συνομιλίες και τους ελέγχους ασφάλειας που ορίζετε για τον χώρο εργασίας.",
        "New team member": "Νέο μέλος ομάδας",
        "Set a username and password for your colleague. They will use both on step 2 of the sign-in screen.":
            "Ορίστε όνομα χρήστη και κωδικό για τον συνάδελφό σας. Θα τα χρησιμοποιεί στο βήμα 2 της σελίδας σύνδεσης.",
        "New members start with this workspace's default safety checks.":
            "Τα νέα μέλη ξεκινούν με τους προεπιλεγμένους ελέγχους ασφάλειας του χώρου εργασίας.",
        "Close a member seat cleanly.": "Κλείσιμο θέσης μέλους.",
        "Removing a team member ends their active sessions and removes their account, chats and settings. Block and activity logs stay intact.":
            "Η αφαίρεση μέλους τερματίζει τις ενεργές συνεδρίες του και διαγράφει τον λογαριασμό, την πρόσβαση στις συνομιλίες και τις ρυθμίσεις του. Τα αρχεία αποκλεισμών και δραστηριότητας διατηρούνται.",
        "Enter the team member's username and password to remove their seat. You will confirm once more before the account is removed.":
            "Εισαγάγετε το όνομα χρήστη και τον κωδικό του μέλους για να αφαιρέσετε τη θέση του. Θα ζητηθεί μία ακόμη επιβεβαίωση πριν την αφαίρεση.",
        "Any open sessions for this member end straight away.":
            "Τυχόν ανοιχτές συνεδρίες αυτού του μέλους τερματίζονται αμέσως.",
        "Remove account": "Αφαίρεση λογαριασμού",
        "Keep account": "Διατήρηση λογαριασμού",
        "Remove member": "Αφαίρεση μέλους",
        "Keep member": "Διατήρηση μέλους",
        "Removed: this administrator account, its member accounts, saved settings and active sessions.":
            "Διαγράφονται: αυτός ο διαχειριστής, οι λογαριασμοί μελών του, οι ρυθμίσεις και οι ενεργές συνεδρίες.",
        "Kept: block and activity log rows stay in the local database.":
            "Διατηρούνται: οι εγγραφές αποκλεισμών και δραστηριότητας μένουν στην τοπική βάση.",
        "Removed: their member account, saved settings and access to their chats.":
            "Διαγράφονται: ο λογαριασμός μέλους, οι αποθηκευμένες ρυθμίσεις και η πρόσβαση στις συνομιλίες του.",
        "Kept: block and activity log rows stay in team statistics.":
            "Διατηρούνται: οι εγγραφές αποκλεισμών και δραστηριότητας μένουν στα στατιστικά ομάδας.",

        // ---- Chat workspace, first-run starters, tracker & blocked card ----
        "Conversations": "Συνομιλίες",
        "Conversation": "Συνομιλία",
        "New chat": "Νέα συνομιλία",
        "Start a new chat": "Νέα συνομιλία",
        "Rename this chat": "Μετονομασία συνομιλίας",
        "Chat title": "Τίτλος συνομιλίας",
        "Short title for this conversation": "Σύντομος τίτλος για τη συνομιλία",
        "Delete this chat": "Διαγραφή συνομιλίας",
        "Remove conversation": "Διαγραφή συνομιλίας",
        "Delete this chat?": "Να διαγραφεί αυτή η συνομιλία;",
        "Delete chat": "Διαγραφή συνομιλίας",
        "Keep chat": "Διατήρηση συνομιλίας",
        "Removed: every message in this conversation is deleted.":
            "Διαγράφονται: όλα τα μηνύματα αυτής της συνομιλίας.",
        "Kept: workspace block and activity logs stay intact.":
            "Διατηρούνται: τα αρχεία αποκλεισμών και δραστηριότητας του χώρου εργασίας.",
        "Remove message": "Διαγραφή μηνύματος",
        "Delete this message": "Διαγραφή μηνύματος",
        "Delete this message?": "Να διαγραφεί αυτό το μήνυμα;",
        "Delete message": "Διαγραφή μηνύματος",
        "Keep message": "Διατήρηση μηνύματος",
        "Removed: this message and its reply leave the conversation.":
            "Διαγράφονται: αυτό το μήνυμα και η απάντησή του αφαιρούνται από τη συνομιλία.",
        "Search this chat": "Αναζήτηση στη συνομιλία",
        "Search this chat…": "Αναζήτηση στη συνομιλία…",
        "Clear search": "Καθαρισμός αναζήτησης",
        "No conversations yet — your chats appear here once you send a message.":
            "Δεν υπάρχουν ακόμη συνομιλίες — εμφανίζονται εδώ μόλις στείλετε το πρώτο μήνυμα.",
        "What are we working on today?": "Πάνω σε τι δουλεύουμε σήμερα;",
        "Pick a starter to fill the message box — nothing leaves until you send it.":
            "Επιλέξτε μια πρόταση για να συμπληρωθεί το πεδίο — τίποτα δεν στέλνεται πριν πατήσετε αποστολή.",
        "Starter prompts": "Προτάσεις εκκίνησης",
        "Summarise this contract in three bullet points":
            "Συνόψισε αυτή τη σύμβαση σε τρία σημεία",
        "Draft a client update email":
            "Γράψε ένα email ενημέρωσης πελάτη",
        "Review this function for bugs":
            "Έλεγξε αυτή τη συνάρτηση για σφάλματα",
        "Every message is checked on this computer through three local checks before it reaches the AI.":
            "Κάθε μήνυμα περνά από τρεις τοπικούς ελέγχους σε αυτόν τον υπολογιστή πριν φτάσει στην ΤΝ.",
        "Start the conversation": "Ξεκινήστε τη συνομιλία",
        "Write a message below. Every line is checked on this computer before it reaches the AI.":
            "Γράψτε ένα μήνυμα παρακάτω. Κάθε γραμμή ελέγχεται σε αυτόν τον υπολογιστή πριν φτάσει στην ΤΝ.",
        "No messages match": "Δεν βρέθηκαν αντίστοιχα μηνύματα",
        "Message": "Μήνυμα",
        "Write a message… (Enter to send, Shift+Enter for a new line)":
            "Γράψτε ένα μήνυμα… (Enter για αποστολή, Shift+Enter για νέα γραμμή)",
        "Send message": "Αποστολή μηνύματος",
        "Checked on this computer before anything reaches the AI.":
            "Ελέγχεται σε αυτόν τον υπολογιστή πριν φτάσει οτιδήποτε στην ΤΝ.",
        "Local safety checks": "Τοπικοί έλεγχοι ασφάλειας",
        "Checking locally before sending…": "Τοπικός έλεγχος πριν την αποστολή…",
        "Still checking — normal on a long paste.":
            "Ο έλεγχος συνεχίζεται — φυσιολογικό σε μεγάλο κείμενο.",
        "Still waiting — normal on a long paste.":
            "Η αναμονή συνεχίζεται — φυσιολογικό σε μεγάλο κείμενο.",
        "Checking the message": "Έλεγχος μηνύματος",
        "All checks passed.": "Όλοι οι έλεγχοι ολοκληρώθηκαν.",
        "Waiting for the AI reply…": "Αναμονή απάντησης από την ΤΝ…",
        "Sending once with administrator approval…":
            "Μεμονωμένη αποστολή με έγκριση διαχειριστή…",
        "Sent once with administrator approval — this was logged.":
            "Στάλθηκε μία φορά με έγκριση διαχειριστή — η ενέργεια καταγράφηκε.",
        "Nicely rewritten — that went through cleanly.":
            "Καθαρή αναδιατύπωση — πέρασε όλους τους ελέγχους.",
        "Copy the answer": "Αντιγραφή απάντησης",
        "Edit this message": "Επεξεργασία μηνύματος",
        "Generate a different answer": "Δημιουργία νέας απάντησης",

        // ---- Three screening stages & blocked card ----
        "Personal & Greek IDs": "Προσωπικά & ελληνικά στοιχεία",
        "Personal data": "Προσωπικά στοιχεία",
        "Confidential context": "Εμπιστευτικό περιεχόμενο",
        "Context": "Συμφραζόμενα",
        "Prompt injection": "Εντολές παράκαμψης (prompt injection)",
        "Injection": "Εντολές παράκαμψης",
        "Personal data check": "Έλεγχος προσωπικών στοιχείων",
        "Context check": "Έλεγχος συμφραζομένων",
        "Prompt injection check": "Έλεγχος εντολών παράκαμψης",
        "Check": "Έλεγχος",
        "Local check": "Τοπικός έλεγχος",
        "a local check": "έναν τοπικό έλεγχο",
        "Checking for personal and Greek identifiers":
            "Έλεγχος για προσωπικά και ελληνικά στοιχεία",
        "Checking for confidential context":
            "Έλεγχος για εμπιστευτικό περιεχόμενο",
        "Checking for prompt injection":
            "Έλεγχος για κρυφές εντολές (prompt injection)",
        "Stopped — this looks like personal data":
            "Κρατήθηκε — μοιάζει με προσωπικά στοιχεία",
        "Stopped — this looks like client or company data":
            "Κρατήθηκε — μοιάζει με στοιχεία πελάτη ή εταιρείας",
        "Stopped — this looks like a hidden instruction":
            "Κρατήθηκε — μοιάζει με κρυφή εντολή προς το μοντέλο",
        "Stopped — a local check flagged this message":
            "Κρατήθηκε — ένας τοπικός έλεγχος επισήμανε το μήνυμα",
        "Check 1 looks for personal identifiers and Greek ID numbers.":
            "Ο Έλεγχος 1 εντοπίζει προσωπικά στοιχεία και ελληνικούς αριθμούς όπως ΑΦΜ και ΑΜΚΑ.",
        "Check 2 looks for confidential company material.":
            "Ο Έλεγχος 2 εντοπίζει εμπιστευτικό εταιρικό ή πελατειακό περιεχόμενο.",
        "Check 3 looks for instructions aimed at the model itself.":
            "Ο Έλεγχος 3 εντοπίζει εντολές που προσπαθούν να παρακάμψουν τους κανόνες του μοντέλου.",
        "A local check matched this message.":
            "Ένας τοπικός έλεγχος εντόπισε ευαίσθητο περιεχόμενο σε αυτό το μήνυμα.",
        "Nothing left this computer. Your message stayed here and was not sent to the AI.":
            "Τίποτα δεν έφυγε από αυτόν τον υπολογιστή. Το μήνυμά σας έμεινε εδώ και δεν στάλθηκε στην ΤΝ.",
        "Why was this stopped?": "Γιατί κρατήθηκε αυτό το μήνυμα;",
        "Ask an administrator to approve this once, or rephrase without the flagged details.":
            "Ζητήστε από έναν διαχειριστή μεμονωμένη έγκριση ή διατυπώστε ξανά το μήνυμα χωρίς τα επισημασμένα στοιχεία.",
        "Edit in message box": "Επεξεργασία στο πεδίο",
        "Put my text back in the message box":
            "Επαναφορά του κειμένου μου στο πεδίο μηνύματος",
        "Approve once": "Έγκριση για μία φορά",
        "Approve & send": "Έγκριση & αποστολή",
        "One-off approvals need the administrator password and are recorded in the audit log.":
            "Οι μεμονωμένες εγκρίσεις απαιτούν τον κωδικό διαχειριστή και καταγράφονται στο αρχείο ελέγχου.",

        // ---- Administrator step-up modal ----
        "Administrator approval": "Επιβεβαίωση διαχειριστή",
        "Administrator username": "Όνομα χρήστη διαχειριστή",
        "Administrator password": "Κωδικός διαχειριστή",
        "This shows team-wide activity.": "Εμφανίζει στοιχεία για όλη την ομάδα.",
        "This page": "Αυτή η σελίδα",
        "safety checks, the model and the API key":
            "τους ελέγχους ασφάλειας, το μοντέλο και το κλειδί API",
        "team activity, blocks and trends":
            "τη δραστηριότητα της ομάδας, τους αποκλεισμούς και τις τάσεις",
        "every member and how their gate is configured":
            "κάθε μέλος της ομάδας και τη ρύθμιση των ελέγχων του",

        // ---- Settings page ----
        "Safety settings": "Ρυθμίσεις ασφάλειας",
        "Safety checks": "Έλεγχοι ασφάλειας",
        "Local safety checks, provider connection and the model answering your messages.":
            "Οι τοπικοί έλεγχοι ασφάλειας, η σύνδεση παρόχου και το μοντέλο που απαντά στα μηνύματά σας.",
        "Each check runs on this computer in order before a message reaches the AI. Changing these checks requires the administrator password and is recorded in the audit log.":
            "Κάθε έλεγχος εκτελείται τοπικά με τη σειρά πριν φτάσει το μήνυμα στην ΤΝ. Κάθε αλλαγή απαιτεί τον κωδικό διαχειριστή και καταγράφεται στο αρχείο ελέγχου.",
        "AFM with checksum, AMKA, IBANs, phone numbers, email addresses, payment cards and names in English and Greek.":
            "ΑΦΜ με έλεγχο εγκυρότητας, ΑΜΚΑ, IBAN, τηλέφωνα, email, κάρτες πληρωμών και ονόματα στα ελληνικά και αγγλικά.",
        "Contracts and NDAs, internal financials, HR and payroll notes, credentials and source code.":
            "Συμβάσεις και NDA, εσωτερικά οικονομικά στοιχεία, μισθοδοσία και HR, διαπιστευτήρια και πηγαίος κώδικας.",
        "Hidden instructions and override attempts — especially common in pasted emails, web pages and documents.":
            "Κρυφές οδηγίες και απόπειρες παράκαμψης κανόνων — συχνές σε επικολλημένα email, ιστοσελίδες και έγγραφα.",
        "All three checks are turned off. Messages from this account will go straight to the AI provider until at least one check is turned back on.":
            "Και οι τρεις έλεγχοι είναι ανενεργοί. Τα μηνύματα αυτού του λογαριασμού θα στέλνονται απευθείας στον πάροχο ΤΝ μέχρι να ενεργοποιηθεί τουλάχιστον ένας.",
        "(AFM, AMKA, IBAN, phones, Greek IDs, names) will not be flagged.":
            "(ΑΦΜ, ΑΜΚΑ, IBAN, τηλέφωνα, ελληνικές ταυτότητες, ονόματα) δεν θα επισημαίνονται.",
        "Context:": "Συμφραζόμενα:",
        "Legal, financial, HR and customer records will not be flagged.":
            "Νομικά, οικονομικά, στοιχεία HR και αρχεία πελατών δεν θα επισημαίνονται.",
        "Prompt-injection": "Εντολές παράκαμψης (prompt injection):",
        "attempts will not be flagged.":
            "Οι απόπειρες παράκαμψης δεν θα επισημαίνονται.",
        "Save checks": "Αποθήκευση ελέγχων",
        "Unsaved changes": "Μη αποθηκευμένες αλλαγές",
        "Approve": "Έγκριση",
        "Safety checks saved.": "Οι έλεγχοι ασφάλειας αποθηκεύτηκαν.",
        "Changing the local safety checks requires the administrator password and is recorded in the audit log.":
            "Η αλλαγή των τοπικών ελέγχων απαιτεί τον κωδικό διαχειριστή και καταγράφεται στο αρχείο ελέγχου.",
        "AI connection": "Σύνδεση ΤΝ",
        "Provider": "Πάροχος",
        "Detect automatically": "Αυτόματος εντοπισμός",
        "Leave this on automatic detection and your key is matched against each supported provider.":
            "Αφήστε τον αυτόματο εντοπισμό και το κλειδί σας θα δοκιμαστεί στους υποστηριζόμενους παρόχους.",
        "Base URL": "Διεύθυνση βάσης (Base URL)",
        "Address for that provider. Leave blank to use its standard hosted endpoint.":
            "Η διεύθυνση επικοινωνίας του παρόχου. Αφήστε κενό για την προεπιλεγμένη διεύθυνση.",
        "Refresh list": "Ανανέωση λίστας",
        "Paste an API key below and available models are listed automatically.":
            "Επικολλήστε ένα κλειδί API παρακάτω και τα διαθέσιμα μοντέλα θα εμφανιστούν αυτόματα.",
        "Checking which models this key can reach…":
            "Έλεγχος διαθέσιμων μοντέλων για αυτό το κλειδί…",
        "That key returned no usable models. Check the provider and key.":
            "Το κλειδί δεν επέστρεψε διαθέσιμα μοντέλα. Ελέγξτε τον πάροχο και το κλειδί.",
        "Paste your API key…": "Επικολλήστε το κλειδί API…",
        "No key saved yet.": "Δεν έχει αποθηκευτεί κλειδί ακόμη.",
        "Save connection": "Αποθήκευση σύνδεσης",
        "Connection saved.": "Η σύνδεση αποθηκεύτηκε.",
        "Choose a model or paste an API key before saving.":
            "Επιλέξτε μοντέλο ή επικολλήστε ένα κλειδί API πριν την αποθήκευση.",
        "Changing the provider, model or API key requires the administrator password and is recorded in the audit log.":
            "Η αλλαγή παρόχου, μοντέλου ή κλειδιού API απαιτεί τον κωδικό διαχειριστή και καταγράφεται στο αρχείο ελέγχου.",
        "Encrypted on this computer and never sent back in full to the browser.":
            "Κρυπτογραφείται σε αυτόν τον υπολογιστή και δεν επιστρέφεται ποτέ ολόκληρο στο πρόγραμμα περιήγησης.",
        "1. Personal data": "1. Προσωπικά στοιχεία",
        "2. Context": "2. Συμφραζόμενα",
        "3. Prompt injection": "3. Εντολές παράκαμψης (prompt injection)",
        "Model": "Μοντέλο",
        "API key": "Κλειδί API",

        // ---- Profile page ----
        "Your account, active safety checks and sign-in details.":
            "Ο λογαριασμός σας, οι ενεργοί έλεγχοι ασφάλειας και τα στοιχεία σύνδεσής σας.",
        "Account details": "Στοιχεία λογαριασμού",
        "Member ID": "Αναγνωριστικό μέλους",
        "Workspace ID": "Αναγνωριστικό χώρου εργασίας",
        "Change username": "Αλλαγή ονόματος χρήστη",
        "New username": "Νέο όνομα χρήστη",
        "Current password": "Τρέχων κωδικός",
        "Change password": "Αλλαγή κωδικού",
        "New password": "Νέος κωδικός",
        "Fill in both the new username and your current password.":
            "Συμπληρώστε το νέο όνομα χρήστη και τον τρέχοντα κωδικό σας.",
        "Fill in both your current password and a new password.":
            "Συμπληρώστε τον τρέχοντα και τον νέο κωδικό σας.",
        "Pick a new password that differs from your current one.":
            "Επιλέξτε έναν νέο κωδικό διαφορετικό από τον τρέχοντα.",
        "Username updated.": "Το όνομα χρήστη ενημερώθηκε.",
        "Password updated.": "Ο κωδικός ενημερώθηκε.",
        "Sent": "Στάλθηκαν",
        "Answered": "Απαντήθηκαν",
        "Blocked": "Κρατήθηκαν",
        "All time": "Συνολικά",
        "Passed checks": "Πέρασαν τους ελέγχους",
        "Held back locally": "Έμειναν τοπικά",

        // ---- Statistics & Team pages ----
        "Volume, stopped messages and approvals across this workspace.":
            "Όγκος μηνυμάτων, αποκλεισμοί και εγκρίσεις σε όλο τον χώρο εργασίας.",
        "Trend window": "Χρονικό παράθυρο",
        "7 days": "7 ημέρες",
        "14 days": "14 ημέρες",
        "30 days": "30 ημέρες",
        "Members": "Μέλη",
        "Active seats": "Ενεργές θέσεις",
        "Messages sent": "Μηνύματα",
        "Overrides": "Εγκρίσεις",
        "Block rate": "Ποσοστό αποκλεισμού",
        "Share of messages": "Μερίδιο μηνυμάτων",
        "Keys configured": "Ρυθμισμένα κλειδιά",
        "Stored encrypted": "Κρυπτογραφημένα",
        "Blocked and approved, per day": "Κρατημένα και εγκεκριμένα, ανά ημέρα",
        "Daily blocks and approvals": "Ημερήσιοι αποκλεισμοί και εγκρίσεις",
        "Approved override": "Εγκεκριμένη εξαίρεση",
        "Approved by administrator": "Εγκρίθηκε από διαχειριστή",
        "Why messages were stopped": "Γιατί κρατήθηκαν τα μηνύματα",
        "Which check stopped them": "Ποιος έλεγχος τα κράτησε",
        "Per team member": "Ανά μέλος ομάδας",
        "Activity log (UTC)": "Αρχείο δραστηριότητας (UTC)",
        "Everyone in this workspace, their active checks and their model setup.":
            "Όλα τα μέλη του χώρου εργασίας, οι ενεργοί έλεγχοι και το μοντέλο τους.",
        "No daily activity yet": "Δεν υπάρχει ακόμη ημερήσια κίνηση",
        "This fills in as your team works. Daily blocks and approvals appear here.":
            "Συμπληρώνεται καθώς εργάζεται η ομάδα σας. Εδώ εμφανίζονται οι ημερήσιοι αποκλεισμοί και οι εγκρίσεις.",
        "This fills in as your team works. You will see daily blocks and one-off approvals here.":
            "Συμπληρώνεται καθώς εργάζεται η ομάδα σας. Εδώ θα βλέπετε τους ημερήσιους αποκλεισμούς και τις μεμονωμένες εγκρίσεις.",
        "Nothing stopped yet": "Κανένα μήνυμα δεν κρατήθηκε ακόμη",
        "This fills in as your team works. Categories appear here whenever a check stops a message.":
            "Συμπληρώνεται καθώς εργάζεται η ομάδα σας. Οι κατηγορίες εμφανίζονται όταν ένας έλεγχος κρατήσει μήνυμα.",
        "All three checks are quiet": "Και οι τρεις έλεγχοι είναι ήσυχοι",
        "When a local check holds back a message, its share of blocks appears here.":
            "Όταν ένας τοπικός έλεγχος κρατήσει μήνυμα, το μερίδιό του εμφανίζεται εδώ.",
        "No team members yet": "Δεν υπάρχουν ακόμη μέλη ομάδας",
        "Add a colleague from step 2 of the sign-in screen to see their activity here.":
            "Προσθέστε έναν συνάδελφο από το βήμα 2 της σελίδας σύνδεσης για να δείτε εδώ τη δραστηριότητά του.",
        "Add a colleague from step 2 of the sign-in screen — their seat and active checks appear here.":
            "Προσθέστε έναν συνάδελφο από το βήμα 2 της σελίδας σύνδεσης — η θέση και οι έλεγχοί του εμφανίζονται εδώ.",
        "No activity recorded yet": "Δεν έχει καταγραφεί ακόμη δραστηριότητα",
        "This fills in as your team works. Sign-ins, sent messages, blocks and approvals appear here with UTC timestamps.":
            "Συμπληρώνεται καθώς εργάζεται η ομάδα σας. Συνδέσεις, μηνύματα, αποκλεισμοί και εγκρίσεις εμφανίζονται εδώ σε ώρα UTC.",

        // ---- Activity timeline event labels ----
        "Override approved": "Εγκρίθηκε εξαίρεση",
        "Message sent": "Μήνυμα στάλθηκε",
        "Signed in": "Σύνδεση",
        "Signed out": "Αποσύνδεση",
        "Checks or model updated": "Ενημέρωση ελέγχων ή μοντέλου",
        "Chat started": "Νέα συνομιλία",
        "Chat deleted": "Διαγραφή συνομιλίας",
        "Message edited": "Επεξεργασία μηνύματος",
        "Message deleted": "Διαγραφή μηνύματος",
        "Answer regenerated": "Νέα απάντηση",

        // ---- Help & quiet-trust privacy guide ----
        "Guide": "Οδηγός",
        "How CyberSyn works": "Πώς λειτουργεί το CyberSyn",
        "What runs before a message reaches the AI, what stays on this computer, and what administrators can and cannot see.":
            "Τι ελέγχεται πριν φτάσει ένα μήνυμα στην ΤΝ, τι μένει σε αυτόν τον υπολογιστή και τι βλέπουν οι διαχειριστές.",
        "The short version": "Με λίγα λόγια",
        "CyberSyn sits between your team and the AI provider you choose. Every message goes through local safety checks on this computer first — only messages that pass are forwarded over the network.":
            "Το CyberSyn βρίσκεται ανάμεσα στην ομάδα σας και τον πάροχο ΤΝ που επιλέγετε. Κάθε μήνυμα περνά πρώτα από τοπικούς ελέγχους σε αυτόν τον υπολογιστή — μόνο όσα περνούν στέλνονται στο δίκτυο.",
        "Write your message as usual": "Γράψτε το μήνυμά σας κανονικά",
        "Draft an email, paste code, summarise a note or ask a question in Chat. Nothing leaves this computer while you type.":
            "Συντάξτε email, επικολλήστε κώδικα, συνοψίστε ένα κείμενο ή κάντε μια ερώτηση στη Συνομιλία. Τίποτα δεν φεύγει όσο πληκτρολογείτε.",
        "Three checks inspect it locally": "Τρεις έλεγχοι το εξετάζουν τοπικά",
        "In order, CyberSyn checks for personal data, sensitive workplace context and hidden prompt-injection instructions.":
            "Με τη σειρά, το CyberSyn ελέγχει για προσωπικά στοιχεία, ευαίσθητο εργασιακό περιεχόμενο και κρυφές εντολές prompt injection.",
        "Sent if clear — held back if not": "Στέλνεται αν είναι καθαρό — κρατείται αν όχι",
        "Clear messages go to your configured model. Flagged messages stay on this computer and show you exactly what matched so you can edit or ask for a one-off approval.":
            "Τα καθαρά μηνύματα πηγαίνουν στο επιλεγμένο μοντέλο. Τα επισημασμένα μένουν σε αυτόν τον υπολογιστή και δείχνουν ακριβώς τι ταίριαξε, ώστε να τα διορθώσετε ή να ζητήσετε μεμονωμένη έγκριση.",
        "The three local checks": "Οι τρεις τοπικοί έλεγχοι",
        "Catches names, email addresses, phone numbers, payment cards, IBANs and Greek national numbers such as AFM and AMKA before they reach an external model.":
            "Εντοπίζει ονόματα, email, τηλέφωνα, κάρτες πληρωμών, IBAN και ελληνικούς αριθμούς όπως ΑΦΜ και ΑΜΚΑ πριν φτάσουν σε εξωτερικό μοντέλο.",
        "Reads the surrounding sentence to spot confidential plans, internal credentials or client information that does not follow a fixed number format.":
            "Διαβάζει τα συμφραζόμενα για να εντοπίσει εμπιστευτικά σχέδια, εσωτερικά διαπιστευτήρια ή στοιχεία πελατών που δεν ακολουθούν σταθερή μορφή αριθμού.",
        "Detects hidden instructions trying to override how the model behaves — common in pasted web pages, forwarded emails and shared documents.":
            "Αναγνωρίζει κρυφές οδηγίες που επιχειρούν να αλλάξουν τη συμπεριφορά του μοντέλου — συχνές σε επικολλημένες ιστοσελίδες, προωθημένα email και κοινόχρηστα έγγραφα.",
        "When a message is held back": "Όταν ένα μήνυμα κρατείται",
        "A stopped message is never sent to the AI provider. The card in your chat names the check that held it back, highlights every matched phrase, and includes a “Why was this stopped?” panel with the category, line number and character offsets.":
            "Ένα κρατημένο μήνυμα δεν στέλνεται ποτέ στον πάροχο ΤΝ. Η κάρτα στη συνομιλία αναφέρει ποιος έλεγχος το σταμάτησε, δείχνει κάθε φράση που ταίριαξε και περιλαμβάνει την ενότητα «Γιατί κρατήθηκε αυτό το μήνυμα;» με την κατηγορία, τη γραμμή και τις θέσεις χαρακτήρων.",
        "From there you have two options: select":
            "Από εκεί έχετε δύο επιλογές: πατήστε",
        "to replace the flagged detail with a placeholder and send again, or select":
            "για να αντικαταστήσετε το επισημασμένο στοιχείο και να στείλετε ξανά, ή πατήστε",
        "so an administrator can enter their password to send that single message and record the approval.":
            "ώστε ένας διαχειριστής να εισαγάγει τον κωδικό του, να σταλεί μόνο αυτό το μήνυμα και να καταγραφεί η έγκριση.",
        "Privacy, visibility and deletion": "Απόρρητο, ορατότητα και διαγραφή",
        "CyberSyn runs on a computer managed by your organisation. Here is what is stored locally and who can read it:":
            "Το CyberSyn λειτουργεί σε υπολογιστή που διαχειρίζεται ο οργανισμός σας. Δείτε τι αποθηκεύεται τοπικά και ποιος έχει πρόσβαση:",
        "Conversations and AI replies": "Συνομιλίες και απαντήσεις ΤΝ",
        "Full messages and model replies are stored in this workspace’s local database for your account. Administrator screens do not load full chat threads or AI answers.":
            "Τα πλήρη μηνύματα και οι απαντήσεις του μοντέλου αποθηκεύονται στην τοπική βάση του χώρου εργασίας για τον λογαριασμό σας. Οι σελίδες διαχειριστή δεν φορτώνουν ολόκληρες συνομιλίες ή απαντήσεις ΤΝ.",
        "What administrators can see": "Τι μπορούν να δουν οι διαχειριστές",
        "After entering the administrator password on Statistics or Team, an administrator can view message counts, block rates, which check and category triggered, UTC timestamps, and the first 80 characters of logged prompts (sent, regenerated, blocked and approved messages) in the activity log.":
            "Αφού εισαγάγει τον κωδικό διαχειριστή στα Στατιστικά ή στην Ομάδα, ο διαχειριστής βλέπει πλήθος μηνυμάτων, ποσοστά αποκλεισμού, ποιος έλεγχος και ποια κατηγορία ενεργοποιήθηκαν, χρονικές σημάνσεις UTC και τους πρώτους 80 χαρακτήρες των καταγεγραμμένων μηνυμάτων (απεσταλμένων, ανανεωμένων, κρατημένων και εγκεκριμένων) στο αρχείο δραστηριότητας.",
        "Deleting messages, chats and accounts": "Διαγραφή μηνυμάτων, συνομιλιών και λογαριασμών",
        "Deleting a message or a chat removes it from your conversation history straight away; append-only block records, activity log entries and message counters remain in the local database for auditing. Removing a member or administrator deletes their sign-in, active sessions and saved model/key settings immediately; historical audit entries remain in the database file until wiped on disk.":
            "Η διαγραφή μηνύματος ή συνομιλίας το αφαιρεί αμέσως από το ιστορικό σας· οι εγγραφές αποκλεισμών, το αρχείο δραστηριότητας και οι μετρητές μηνυμάτων παραμένουν στην τοπική βάση για έλεγχο. Η αφαίρεση μέλους ή διαχειριστή διαγράφει αμέσως τη σύνδεση, τις ενεργές συνεδρίες και τις αποθηκευμένες ρυθμίσεις μοντέλου/κλειδιού· οι ιστορικές εγγραφές ελέγχου παραμένουν στο αρχείο βάσης μέχρι να διαγραφεί από τον δίσκο.",
        "API keys, sessions and external requests": "Κλειδιά API, συνεδρίες και εξωτερικές συνδέσεις",
        "Provider API keys are encrypted before they are saved and shown masked everywhere on screen. Session tokens are stored as SHA-256 hashes and expire after 7 days. Typefaces are bundled locally (Instrument Serif, Inter and JetBrains Mono under the SIL Open Font License 1.1) — CyberSyn makes outbound requests only to the AI provider configured for your seat.":
            "Τα κλειδιά API των παρόχων κρυπτογραφούνται πριν αποθηκευτούν και εμφανίζονται με απόκρυψη σε κάθε οθόνη. Τα διακριτικά συνεδρίας αποθηκεύονται ως κατακερματισμοί SHA-256 και λήγουν μετά από 7 ημέρες. Οι γραμματοσειρές περιλαμβάνονται τοπικά (Instrument Serif, Inter και JetBrains Mono υπό την άδεια SIL Open Font License 1.1) — το CyberSyn συνδέεται εξωτερικά μόνο με τον πάροχο ΤΝ της θέσης σας.",
        "Models and API keys": "Μοντέλα και κλειδιά API",
        "CyberSyn works with OpenAI, Anthropic Claude, Google Gemini, Mistral, Cohere, Groq, DeepSeek and xAI Grok. An administrator selects the model and saves the matching provider API key for each signed-in member on the":
            "Το CyberSyn συνεργάζεται με OpenAI, Anthropic Claude, Google Gemini, Mistral, Cohere, Groq, DeepSeek και xAI Grok. Ο διαχειριστής επιλέγει το μοντέλο και αποθηκεύει το αντίστοιχο κλειδί API για κάθε συνδεδεμένο μέλος στη σελίδα",
        "page.": ".",
        "Everyday shortcuts and tips": "Καθημερινές συντομεύσεις και συμβουλές",
        "Press": "Πατήστε",
        "to send a message and": "για αποστολή μηνύματος και",
        "to add a new line.": "για αλλαγή γραμμής.",
        "Use the search box at the top of Chat to filter the open conversation; press":
            "Χρησιμοποιήστε το πεδίο αναζήτησης πάνω στη Συνομιλία για φιλτράρισμα· πατήστε",
        "to clear it.": "για καθαρισμό.",
        "Administrator pages stay unlocked in the current tab for 15 minutes after entering the password. Use":
            "Οι σελίδες διαχειριστή μένουν ξεκλείδωτες στην τρέχουσα καρτέλα για 15 λεπτά μετά την εισαγωγή του κωδικού. Πατήστε",
        "in the sidebar to close that window immediately.":
            "στην πλευρική στήλη για άμεσο κλείδωμα.",
        "On Statistics, use": "Στα Στατιστικά, επιλέξτε",
        "to export workspace totals and trends, or print either Statistics or Team cleanly to A4 — API keys and prompt excerpts are omitted on paper.":
            "για εξαγωγή συνόλων και τάσεων, ή εκτυπώστε τα Στατιστικά ή την Ομάδα σε A4 — τα κλειδιά API και τα αποσπάσματα μηνυμάτων παραλείπονται στο χαρτί.",

        // ---- Toasts, form checks & remedy-oriented errors ----
        "Type your administrator username to continue.":
            "Πληκτρολογήστε το όνομα χρήστη διαχειριστή για να συνεχίσετε.",
        "Type your password to continue.":
            "Πληκτρολογήστε τον κωδικό σας για να συνεχίσετε.",
        "Type the team member's username first.":
            "Πληκτρολογήστε πρώτα το όνομα χρήστη του μέλους.",
        "Type the team member's password to open the workspace.":
            "Πληκτρολογήστε τον κωδικό του μέλους για να ανοίξετε τον χώρο εργασίας.",
        "Choose a username.": "Επιλέξτε όνομα χρήστη.",
        "Choose a password first.": "Επιλέξτε πρώτα κωδικό πρόσβασης.",
        "Those passwords do not match. Type the same password in both boxes.":
            "Οι κωδικοί δεν ταιριάζουν. Πληκτρολογήστε τον ίδιο κωδικό και στα δύο πεδία.",
        "Administrator account created. You can sign in now.":
            "Ο λογαριασμός διαχειριστή δημιουργήθηκε. Μπορείτε να συνδεθείτε τώρα.",
        "Type the administrator username you want to delete.":
            "Πληκτρολογήστε το όνομα χρήστη του διαχειριστή προς διαγραφή.",
        "Type that account's password to confirm.":
            "Πληκτρολογήστε τον κωδικό αυτού του λογαριασμού για επιβεβαίωση.",
        "Administrator account deleted.": "Ο λογαριασμός διαχειριστή διαγράφηκε.",
        "Sign in as an administrator first.": "Συνδεθείτε πρώτα ως διαχειριστής.",
        "Type the member username you want to remove.":
            "Πληκτρολογήστε το όνομα χρήστη του μέλους προς αφαίρεση.",
        "Type that member's password to confirm.":
            "Πληκτρολογήστε τον κωδικό αυτού του μέλους για επιβεβαίωση.",
        "Enter the administrator password.": "Εισαγάγετε τον κωδικό διαχειριστή.",
        "Enter the administrator username.": "Εισαγάγετε το όνομα χρήστη διαχειριστή.",
        "That password did not match. Check it and try again.":
            "Ο κωδικός δεν ταίριαξε. Ελέγξτε τον και δοκιμάστε ξανά.",
        "Administrator approval was cancelled.": "Η επιβεβαίωση διαχειριστή ακυρώθηκε.",
        "Your session ended. Sign in again to continue.":
            "Η συνεδρία σας έληξε. Συνδεθείτε ξανά για να συνεχίσετε.",
        "your session ended": "η συνεδρία σας έληξε",
        "the server is unhappy": "ο διακομιστής αντιμετώπισε σφάλμα",
        "That took longer than expected. Check your connection and try again.":
            "Η απόκριση καθυστέρησε. Ελέγξτε τη σύνδεσή σας και δοκιμάστε ξανά.",
        "Could not reach the gateway. Check that the server is running and try again.":
            "Δεν ήταν δυνατή η επικοινωνία με την πύλη. Βεβαιωθείτε ότι ο διακομιστής λειτουργεί και δοκιμάστε ξανά.",
        "That message was empty — type a line first.":
            "Το μήνυμα ήταν κενό — γράψτε πρώτα μια γραμμή.",
        "Answer copied.": "Η απάντηση αντιγράφηκε.",
        "Clipboard access was blocked — select the text to copy it.":
            "Δεν επιτράπηκε η πρόσβαση στο πρόχειρο — επιλέξτε το κείμενο για αντιγραφή.",
        "Message updated.": "Το μήνυμα ενημερώθηκε.",
        "Message deleted.": "Το μήνυμα διαγράφηκε.",
        "New answer ready.": "Η νέα απάντηση είναι έτοιμη.",
        "Nothing to delete yet — this chat has no saved messages.":
            "Δεν υπάρχει κάτι για διαγραφή — αυτή η συνομιλία δεν έχει αποθηκευμένα μηνύματα.",
        "Chat deleted.": "Η συνομιλία διαγράφηκε.",
        "Chat renamed.": "Η συνομιλία μετονομάστηκε.",
        "Settings saved.": "Οι ρυθμίσεις αποθηκεύτηκαν.",
        "CSV downloaded.": "Το αρχείο CSV κατέβηκε.",
        "Wait for statistics to load before downloading CSV.":
            "Περιμένετε να φορτώσουν τα στατιστικά πριν κατεβάσετε το CSV.",

        // ---- Server error strings (untouched backend contracts) ----
        "Your session has ended. Sign in again.":
            "Η συνεδρία σας έληξε. Συνδεθείτε ξανά.",
        "Administrator approval is needed. Sign in as administrator.":
            "Χρειάζεται επιβεβαίωση διαχειριστή. Συνδεθείτε ως διαχειριστής.",
        "Enter both your username and password.":
            "Συμπληρώστε όνομα χρήστη και κωδικό.",
        "Incorrect username or password.":
            "Λανθασμένο όνομα χρήστη ή κωδικός.",
        "That username is already taken.":
            "Αυτό το όνομα χρήστη χρησιμοποιείται ήδη.",
        "Use a password of at least 8 characters with letters and numbers.":
            "Χρησιμοποιήστε κωδικό τουλάχιστον 8 χαρακτήρων με γράμματα και αριθμούς.",
        "Write a message first.":
            "Γράψτε πρώτα ένα μήνυμα.",
        "No API key is configured for this account. Ask an administrator to add one in Settings.":
            "Δεν έχει ρυθμιστεί κλειδί API για αυτόν τον λογαριασμό. Ζητήστε από έναν διαχειριστή να προσθέσει ένα στις Ρυθμίσεις.",
        "The saved API key could not be read. Ask an administrator to re-enter it in Settings.":
            "Δεν ήταν δυνατή η ανάγνωση του αποθηκευμένου κλειδιού API. Ζητήστε από έναν διαχειριστή να το εισαγάγει ξανά στις Ρυθμίσεις.",
        "That chat could not be found.":
            "Η συνομιλία δεν βρέθηκε.",
        "That message could not be found.":
            "Το μήνυμα δεν βρέθηκε.",
        "Paste an API key first.":
            "Επικολλήστε πρώτα ένα κλειδί API.",
        "That key returned no models.":
            "Αυτό το κλειδί δεν επέστρεψε διαθέσιμα μοντέλα.",
        "Too many attempts. Please wait a minute and try again.":
            "Πολλές προσπάθειες. Περιμένετε ένα λεπτό και δοκιμάστε ξανά."
    };

    /* ----------------------------------------------------------------------
       Patterns for strings with numbers or names filled in at runtime.
       ---------------------------------------------------------------------- */
    var PATTERNS = [
        [/^(\d+) of 3 checks active$/, function (m) {
            return m[1] + " από 3 έλεγχοι ενεργοί";
        }],
        [/^(\d+) of 3 active$/, function (m) {
            return m[1] + " από 3 ενεργοί";
        }],
        [/^(\d+) of 3 checks on$/, function (m) {
            return m[1] + " από 3 έλεγχοι ενεργοί";
        }],
        [/^Check (\d) · (.+)$/, function (m) {
            return "Έλεγχος " + m[1] + " · " + (EL[m[2]] || m[2]);
        }],
        [/^(\d+) messages?$/, function (m) {
            return m[1] === "1" ? "1 μήνυμα" : m[1] + " μηνύματα";
        }],
        [/^line (\d+)$/, function (m) {
            return "γραμμή " + m[1];
        }],
        [/^Member #(\d+)$/, function (m) {
            return "Μέλος #" + m[1];
        }],
        [/^Workspace (#?)(\d+)$/, function (m) {
            return "Χώρος εργασίας " + m[1] + m[2];
        }],
        [/^Workspace: (.+)$/, function (m) {
            return "Χώρος εργασίας: " + m[1];
        }],
        [/^Password for (.+)$/, function (m) {
            return "Κωδικός για " + m[1];
        }],
        [/^Signed in as (.+)\.$/, function (m) {
            return "Συνδεθήκατε ως " + m[1] + ".";
        }],
        [/^Delete administrator (.+)\?$/, function (m) {
            return "Να διαγραφεί ο διαχειριστής " + m[1] + ";";
        }],
        [/^Remove (.+) from this workspace\?$/, function (m) {
            return "Να αφαιρεθεί το μέλος " + m[1] + " από τον χώρο εργασίας;";
        }],
        [/^(.+) added — they can sign in now\.$/, function (m) {
            return "Το μέλος " + m[1] + " προστέθηκε — μπορεί να συνδεθεί τώρα.";
        }],
        [/^(.+) removed from this workspace\.$/, function (m) {
            return "Το μέλος " + m[1] + " αφαιρέθηκε από τον χώρο εργασίας.";
        }],
        [/^(.+) needs the administrator password$/, function (m) {
            return "Η ενότητα «" + (EL[m[1]] || m[1]) + "» χρειάζεται κωδικό διαχειριστή";
        }],
        [/^This page shows (.+)\.$/, function (m) {
            return "Αυτή η σελίδα εμφανίζει " + (EL[m[1]] || m[1]) + ".";
        }],
        [/^The server could not finish that request \((.+)\)\. Try again\.$/, function (m) {
            return "Ο διακομιστής δεν ολοκλήρωσε το αίτημα (" + (EL[m[1]] || m[1]) + "). Δοκιμάστε ξανά.";
        }],
        [/^(\d+)s ago$/, function (m) { return "πριν " + m[1] + " δευτ."; }],
        [/^(\d+) min ago$/, function (m) { return "πριν " + m[1] + " λεπτά"; }],
        [/^(\d+) h ago$/, function (m) {
            return m[1] === "1" ? "πριν 1 ώρα" : "πριν " + m[1] + " ώρες";
        }],
        [/^(\d+) d ago$/, function (m) {
            return m[1] === "1" ? "πριν 1 ημέρα" : "πριν " + m[1] + " ημέρες";
        }]
    ];

    /* ----------------------------------------------------------------------
       Language state
       ---------------------------------------------------------------------- */

    function readStored() {
        try {
            var value = localStorage.getItem(STORAGE_KEY);
            return value === "el" ? "el" : DEFAULT;
        } catch (_err) {
            return DEFAULT;
        }
    }

    var current = readStored();
    var applying = false;

    function translate(text) {
        if (current !== "el" || !text) return text;
        var trimmed = String(text).replace(/\s+/g, " ").trim();
        if (!trimmed) return text;
        if (Object.prototype.hasOwnProperty.call(EL, trimmed)) {
            return replaceKeepingWhitespace(text, trimmed, EL[trimmed]);
        }
        for (var i = 0; i < PATTERNS.length; i++) {
            var match = trimmed.match(PATTERNS[i][0]);
            if (match) {
                return replaceKeepingWhitespace(text, trimmed, PATTERNS[i][1](match));
            }
        }
        return text;
    }

    function replaceKeepingWhitespace(raw, _trimmed, replacement) {
        var lead = (raw.match(/^\s*/) || [""])[0];
        var tail = (raw.match(/\s*$/) || [""])[0];
        return lead + replacement + tail;
    }

    /* ----------------------------------------------------------------------
       DOM walker — translates text nodes, placeholders, titles and aria-labels
       while skipping code blocks, user messages, model names and usernames.
       ---------------------------------------------------------------------- */

    var SKIP_TEXT_TAGS = { SCRIPT: 1, STYLE: 1, CODE: 1, PRE: 1, TEXTAREA: 1 };
    var SKIP_ATTR_TAGS = { SCRIPT: 1, STYLE: 1, CODE: 1, PRE: 1 };
    var SKIP_SELECTOR = [
        "[data-no-i18n]",
        ".bubble-user",
        ".bubble-ai",
        ".chat-item-title",
        ".blocked-match code",
        ".blocked-detail-row",
        ".tl-prefix",
        ".avatar",
        ".user-name",
        "[data-member-name]",
        "#sidebar-username",
        "#profile-username",
        "#profile-model",
        "#admin-badge-name",
        ".lang-switch",
        "select#setting-model"
    ].join(", ");

    var ATTRS = ["placeholder", "title", "aria-label"];

    function shouldSkip(element, forAttr) {
        if (!element || element.nodeType !== 1) return false;
        var tags = forAttr ? SKIP_ATTR_TAGS : SKIP_TEXT_TAGS;
        if (tags[element.tagName]) return true;
        if (element.closest && element.closest(SKIP_SELECTOR)) return true;
        return false;
    }

    function applyTextNode(node) {
        var parent = node.parentElement;
        if (!parent || shouldSkip(parent, false)) return;

        if (node.__i18nSource === undefined) {
            var raw = node.nodeValue;
            if (!raw || !raw.trim()) return;
            node.__i18nSource = raw;
        }
        var target = current === "el" ? translate(node.__i18nSource) : node.__i18nSource;
        if (node.nodeValue !== target) node.nodeValue = target;
    }

    function applyAttributes(element) {
        if (shouldSkip(element, true)) return;
        for (var i = 0; i < ATTRS.length; i++) {
            var attr = ATTRS[i];
            if (!element.hasAttribute(attr)) continue;
            var live = element.getAttribute(attr);
            var key = "__i18n_" + attr;
            var last = "__i18n_last_" + attr;
            if (element[key] === undefined ||
                (element[last] !== undefined && live !== element[last])) {
                element[key] = live;
            }
            var target = current === "el" ? translate(element[key]) : element[key];
            if (live !== target) {
                element.setAttribute(attr, target);
            }
            element[last] = target;
        }
    }

    var titleSource = null;

    function applyTitle() {
        if (titleSource === null) titleSource = document.title;
        var target = current === "el" ? translate(titleSource) : titleSource;
        if (document.title !== target) document.title = target;
    }

    function applyRoot(root) {
        if (!root || applying) return;
        applying = true;
        try {
            document.documentElement.lang = current;
            applyTitle();

            var target = root.nodeType === 1 ? root : document.body;
            if (!target) return;

            applyAttributes(target);
            var elements = target.querySelectorAll("[placeholder], [title], [aria-label]");
            for (var i = 0; i < elements.length; i++) applyAttributes(elements[i]);

            var walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT, null, false);
            var node;
            while ((node = walker.nextNode())) applyTextNode(node);

            updateSwitches();
        } finally {
            applying = false;
        }
    }

    /* ----------------------------------------------------------------------
       The EN | ΕΛ language toggle control
       ---------------------------------------------------------------------- */

    function buildSwitch(compact) {
        var box = document.createElement("div");
        box.className = "lang-switch" + (compact ? " lang-switch-compact" : "");
        box.setAttribute("role", "group");
        box.setAttribute("aria-label", current === "el" ? EL["Language"] : "Language");

        [
            { code: "en", label: "EN", tip: "English" },
            { code: "el", label: "ΕΛ", tip: "Ελληνικά" }
        ].forEach(function (option) {
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "lang-btn";
            btn.dataset.lang = option.code;
            btn.textContent = option.label;
            btn.title = option.tip;
            btn.setAttribute("aria-label", option.tip);
            btn.addEventListener("click", function () { setLanguage(option.code); });
            box.appendChild(btn);
        });
        return box;
    }

    function mountSwitches() {
        var slot = document.querySelector("[data-lang-switch]");
        var foot = document.querySelector(".sidebar-foot");
        if (slot && !slot.querySelector(".lang-switch")) {
            slot.appendChild(buildSwitch(true));
        } else if (foot && !foot.querySelector(".lang-switch")) {
            var row = document.createElement("div");
            row.className = "sidebar-lang";
            row.appendChild(buildSwitch(true));
            foot.insertBefore(row, foot.firstChild);
        }

        var authMain = document.querySelector(".auth-main");
        var isAuth = authMain || document.querySelector(".auth-shell");
        if (isAuth && !document.querySelector(".auth-lang")) {
            var corner = document.createElement("div");
            corner.className = "auth-lang";
            corner.appendChild(buildSwitch(false));
            (authMain || document.body).appendChild(corner);
        }

        updateSwitches();
    }

    function updateSwitches() {
        var label = current === "el" ? EL["Language"] : "Language";
        var groups = document.querySelectorAll(".lang-switch");
        for (var g = 0; g < groups.length; g++) {
            groups[g].setAttribute("aria-label", label);
        }
        var buttons = document.querySelectorAll(".lang-switch button[data-lang]");
        for (var i = 0; i < buttons.length; i++) {
            var active = buttons[i].dataset.lang === current;
            buttons[i].classList.toggle("is-active", active);
            buttons[i].setAttribute("aria-pressed", active ? "true" : "false");
        }
    }

    function setLanguage(lang) {
        var next = lang === "el" ? "el" : "en";
        var changed = next !== current;
        current = next;
        try { localStorage.setItem(STORAGE_KEY, current); } catch (_err) { /* ignore */ }
        applyRoot(document.body);
        if (changed && typeof document.dispatchEvent === "function") {
            try {
                document.dispatchEvent(new CustomEvent("cybersyn:lang", {
                    detail: { lang: current }
                }));
            } catch (_err) { /* older engines */ }
            applyRoot(document.body);
        }
    }

    /* ----------------------------------------------------------------------
       Live observer — picks up cards, modals and toasts built after load.
       ---------------------------------------------------------------------- */

    function startObserver() {
        if (!global.MutationObserver || !document.body) return;
        var pending = false;
        var observer = new MutationObserver(function () {
            if (applying || current !== "el" || pending) return;
            pending = true;
            (global.requestAnimationFrame || setTimeout)(function () {
                pending = false;
                applyRoot(document.body);
            }, 0);
        });
        observer.observe(document.body, {
            childList: true,
            subtree: true,
            characterData: false
        });
    }

    function init() {
        document.documentElement.lang = current;
        mountSwitches();
        if (current === "el") applyRoot(document.body);
        startObserver();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    global.I18n = {
        t: translate,
        set: setLanguage,
        current: function () { return current; },
        apply: function () { applyRoot(document.body); },
        dictionary: EL
    };
})(window);
