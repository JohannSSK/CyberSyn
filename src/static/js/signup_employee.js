(function () {
    const ADMIN_TOKEN_KEY = "cybersyn_admin_token";
    const usernameInput = document.getElementById("signup-username");
    const passwordInput = document.getElementById("signup-password");
    const confirmInput = document.getElementById("signup-password-confirm");
    const msg = document.getElementById("signup-msg");
    const btn = document.getElementById("btn-signup-employee");
    const notice = document.getElementById("session-notice");
    const context = document.getElementById("session-context");
    const adminLabel = document.getElementById("session-admin-label");
    let parentId = null;

    async function loadSession() {
        const token = localStorage.getItem(ADMIN_TOKEN_KEY);
        if (!token) {
            notice.textContent = "Sign in as an administrator before adding a team member.";
            btn.disabled = true;
            return;
        }
        try {
            const res = await fetch("/api/admin/session", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ token: token })
            });
            const data = await res.json();
            if (!data.success) {
                localStorage.removeItem(ADMIN_TOKEN_KEY);
                notice.textContent = "Your administrator session has ended. Sign in again.";
                btn.disabled = true;
                return;
            }
            parentId = data.Parent_id;
            adminLabel.textContent = data.username;
            context.classList.remove("hidden");
        } catch (err) {
            notice.textContent = "Could not reach the server.";
            btn.disabled = true;
        }
    }

    async function submit() {
        if (!parentId) return;
        const username = usernameInput.value.trim();
        const password = passwordInput.value.trim();
        msg.textContent = "";
        if (!username || !password) {
            msg.textContent = "Enter a username and password.";
            return;
        }
        if (password !== confirmInput.value.trim()) {
            msg.textContent = "The passwords do not match.";
            return;
        }
        btn.disabled = true;
        btn.textContent = "Adding...";
        try {
            const res = await fetch("/api/admin/employee", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ method: "add", Parent_id: parentId, username: username, password: password })
            });
            const data = await res.json();
            if (data.error) {
                msg.textContent = data.error_message || "Could not add the team member.";
                btn.disabled = false;
                btn.textContent = "Add team member";
                return;
            }
            btn.textContent = "Added";
            setTimeout(() => { window.location.href = "/"; }, 900);
        } catch (err) {
            msg.textContent = "Could not reach the server.";
            btn.disabled = false;
            btn.textContent = "Add team member";
        }
    }

    btn.addEventListener("click", submit);
    [usernameInput, passwordInput, confirmInput].forEach(el => {
        el.addEventListener("keydown", e => { if (e.key === "Enter") submit(); });
    });
    loadSession();
})();
