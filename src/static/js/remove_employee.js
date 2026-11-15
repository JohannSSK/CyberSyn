(function () {
    const ADMIN_TOKEN_KEY = "cybersyn_admin_token";
    const usernameInput = document.getElementById("remove-username");
    const passwordInput = document.getElementById("remove-password");
    const msg = document.getElementById("remove-msg");
    const btn = document.getElementById("btn-remove-employee");
    const notice = document.getElementById("session-notice");
    const context = document.getElementById("session-context");
    const adminLabel = document.getElementById("session-admin-label");
    let parentId = null;
    let confirming = null;

    const confirmBox = document.createElement("div");
    confirmBox.className = "auth-secondary hidden";
    confirmBox.style.marginTop = "12px";
    confirmBox.style.paddingTop = "0";
    confirmBox.style.borderTop = "none";
    confirmBox.style.justifyContent = "flex-start";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "auth-link";
    cancelBtn.textContent = "Cancel";
    confirmBox.appendChild(cancelBtn);
    btn.insertAdjacentElement("afterend", confirmBox);

    function resetConfirm() {
        confirming = null;
        confirmBox.classList.add("hidden");
        btn.textContent = "Remove team member";
        btn.disabled = !parentId;
    }

    function askConfirm(username) {
        confirming = username;
        msg.textContent = `Are you sure you want to delete team member ${username}? This cannot be undone.`;
        btn.textContent = `Yes, delete ${username}`;
        confirmBox.classList.remove("hidden");
        btn.focus();
    }

    cancelBtn.addEventListener("click", () => {
        msg.textContent = "";
        resetConfirm();
    });

    async function loadSession() {
        const token = localStorage.getItem(ADMIN_TOKEN_KEY);
        if (!token) {
            notice.textContent = "Sign in as an administrator before removing a team member.";
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
        if (!parentId || btn.disabled) return;
        const username = usernameInput.value.trim();
        const password = passwordInput.value.trim();
        msg.textContent = "";
        if (!username || !password) {
            msg.textContent = "Enter the team member username and password.";
            return;
        }
        if (confirming !== username) {
            askConfirm(username);
            return;
        }
        btn.disabled = true;
        btn.textContent = "Removing...";
        try {
            const res = await fetch("/api/admin/employee", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ method: "remove", Parent_id: parentId, username: username, password: password })
            });
            const data = await res.json();
            if (data.error) {
                resetConfirm();
                msg.textContent = data.error_message || "Could not remove the team member.";
                return;
            }
            btn.textContent = "Removed";
            setTimeout(() => { window.location.href = "/"; }, 900);
        } catch (err) {
            resetConfirm();
            msg.textContent = "Could not reach the server.";
        }
    }

    btn.addEventListener("click", submit);
    [usernameInput, passwordInput].forEach(el => {
        el.addEventListener("input", () => {
            if (confirming) {
                msg.textContent = "";
                resetConfirm();
            }
        });
        el.addEventListener("keydown", e => { if (e.key === "Enter") submit(); });
    });
    loadSession();
})();
