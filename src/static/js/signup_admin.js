(function () {
    const ADMIN_TOKEN_KEY = "cybersyn_admin_token";
    const usernameInput = document.getElementById("signup-username");
    const passwordInput = document.getElementById("signup-password");
    const confirmInput = document.getElementById("signup-password-confirm");
    const msg = document.getElementById("signup-msg");
    const btn = document.getElementById("btn-signup-admin");

    function passwordProblem(pw) {
        if (pw.length < 8) return "Password must be at least 8 characters.";
        if (!/[0-9]/.test(pw)) return "Password must include at least one number.";
        if (!/[A-Za-z]/.test(pw)) return "Password must include at least one letter.";
        return "";
    }

    async function submit() {
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
        const problem = passwordProblem(password);
        if (problem) {
            msg.textContent = problem;
            return;
        }
        btn.disabled = true;
        btn.textContent = "Creating account...";
        try {
            const res = await fetch("/api/admin", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ method: "add", username: username, password: password })
            });
            const data = await res.json();
            if (data.error) {
                msg.textContent = data.error_message || "Could not create the account.";
                btn.disabled = false;
                btn.textContent = "Create account";
                return;
            }
            localStorage.setItem(ADMIN_TOKEN_KEY, data.session_token);
            window.location.href = "/";
        } catch (err) {
            msg.textContent = "Could not reach the server.";
            btn.disabled = false;
            btn.textContent = "Create account";
        }
    }

    btn.addEventListener("click", submit);
    [usernameInput, passwordInput, confirmInput].forEach(el => {
        el.addEventListener("keydown", e => { if (e.key === "Enter") submit(); });
    });
})();
