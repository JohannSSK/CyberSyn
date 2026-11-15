/**
 * CyberSyn — Unified Client Application Controller
 * Handles all 6 backend endpoints:
 *   1. POST /api/admin/login
 *   2. POST /api/admin (add / remove)
 *   3. POST /api/admin/employee (add / remove)
 *   4. POST /api/admin/employee/login
 *   5. POST /api/admin/employee/settings
 *   6. POST /api/admin/employee/chat
 */

document.addEventListener('DOMContentLoaded', () => {
    // ==========================================
    // Application State Store
    // ==========================================
    const state = {
        parentId: sessionStorage.getItem('cybersyn_parent_id') || null,
        employeeId: sessionStorage.getItem('cybersyn_employee_id') || null,
        employeeUsername: sessionStorage.getItem('cybersyn_employee_user') || null,
        lastInterceptedPrompt: null,
        settings: JSON.parse(sessionStorage.getItem('cybersyn_settings') || 'null') || {
            check1: true,
            check2: true,
            check3: true,
            API_KEY: '',
            MODEL_NAME: 'gpt-4o-mini'
        }
    };

    // ==========================================
    // DOM Element Handles
    // ==========================================
    const views = {
        portal: document.getElementById('portal-view'),
        workspace: document.getElementById('workspace-view')
    };

    const admin = {
        username: document.getElementById('admin-username'),
        password: document.getElementById('admin-password'),
        btnLogin: document.getElementById('btn-admin-login'),
        btnRegister: document.getElementById('btn-admin-register'),
        btnDelete: document.getElementById('btn-admin-delete'),
        sessionBadge: document.getElementById('admin-session-badge'),
        activeLabel: document.getElementById('active-admin-label'),
        btnLogout: document.getElementById('btn-admin-logout')
    };

    const employee = {
        card: document.getElementById('employee-card'),
        lockOverlay: document.getElementById('employee-lock-overlay'),
        username: document.getElementById('employee-username'),
        password: document.getElementById('employee-password'),
        btnLogin: document.getElementById('btn-employee-login'),
        btnCreate: document.getElementById('btn-employee-create'),
        btnDelete: document.getElementById('btn-employee-delete')
    };

    const workspace = {
        displayUser: document.getElementById('display-employee-user'),
        displayParent: document.getElementById('display-parent-id'),
        syncBadge: document.getElementById('settings-sync-badge'),
        activeChecksSummary: document.getElementById('active-checks-summary'),
        check1: document.getElementById('setting-check1'),
        check2: document.getElementById('setting-check2'),
        check3: document.getElementById('setting-check3'),
        apiKey: document.getElementById('setting-api-key'),
        modelName: document.getElementById('setting-model-name'),
        btnSaveSettings: document.getElementById('btn-save-settings'),
        btnLogout: document.getElementById('btn-workspace-logout'),
        chatStream: document.getElementById('chat-stream'),
        chatForm: document.getElementById('form-chat-send'),
        promptInput: document.getElementById('prompt-input'),
        btnSendPrompt: document.getElementById('btn-send-prompt'),
        btnClearChat: document.getElementById('btn-clear-chat')
    };

    const modal = {
        container: document.getElementById('intercept-modal'),
        stage: document.getElementById('intercept-stage'),
        cause: document.getElementById('intercept-cause'),
        score: document.getElementById('intercept-score'),
        matches: document.getElementById('intercept-matches'),
        toggleBypass: document.getElementById('toggle-bypass-controls'),
        bypassPanel: document.getElementById('bypass-controls-panel'),
        bypassPassword: document.getElementById('bypass-admin-password'),
        btnExecuteBypass: document.getElementById('btn-execute-bypass'),
        btnClose: document.getElementById('btn-close-modal'),
        btnDismiss: document.getElementById('btn-dismiss-modal')
    };

    // ==========================================
    // UI Helpers (Toast, Views & Sync status)
    // ==========================================
    function showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;

        const icons = {
            success: '✅',
            error: '🛑',
            warning: '⚠️',
            info: 'ℹ️'
        };

        toast.innerHTML = `
            <span>${icons[type] || 'ℹ️'}</span>
            <div style="flex: 1;">${escapeHTML(message)}</div>
        `;

        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    function switchView(viewName) {
        if (viewName === 'workspace') {
            views.portal.classList.add('hidden');
            views.workspace.classList.remove('hidden');
            applySettingsToUI();
        } else {
            views.workspace.classList.add('hidden');
            views.portal.classList.remove('hidden');
        }
    }

    function updateAdminAuthState() {
        if (state.parentId) {
            admin.sessionBadge.classList.remove('hidden');
            admin.activeLabel.textContent = `Admin ID: ${state.parentId}`;
            employee.card.classList.remove('locked');
            employee.lockOverlay.classList.add('hidden');
        } else {
            admin.sessionBadge.classList.add('hidden');
            admin.activeLabel.textContent = 'Admin ID: --';
            employee.card.classList.add('locked');
            employee.lockOverlay.classList.remove('hidden');
        }
    }

    function updateActiveChecksSummary() {
        const activeCount = [
            workspace.check1.checked,
            workspace.check2.checked,
            workspace.check3.checked
        ].filter(Boolean).length;
        workspace.activeChecksSummary.textContent = `${activeCount}/3 Checks Active`;
    }

    function applySettingsToUI() {
        workspace.check1.checked = Boolean(state.settings.check1);
        workspace.check2.checked = Boolean(state.settings.check2);
        workspace.check3.checked = Boolean(state.settings.check3);
        workspace.apiKey.value = state.settings.API_KEY || '';
        workspace.modelName.value = state.settings.MODEL_NAME || 'gpt-4o-mini';
        updateActiveChecksSummary();
    }

    function markSettingsUnsaved() {
        updateActiveChecksSummary();
        workspace.syncBadge.textContent = 'Modified';
        workspace.syncBadge.classList.add('unsaved');
    }

    // ==========================================
    // 1 & 2. ADMIN APIs (/api/admin/login & /api/admin)
    // ==========================================
    async function handleAdminLogin() {
        const username = admin.username.value.trim();
        const password = admin.password.value.trim();

        if (!username || !password) {
            showToast('Please provide both admin username and password.', 'warning');
            return;
        }

        try {
            const response = await fetch('/api/admin/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });

            const data = await response.json();

            if (data.success && data.Parent_id !== undefined) {
                state.parentId = data.Parent_id;
                sessionStorage.setItem('cybersyn_parent_id', data.Parent_id);
                updateAdminAuthState();
                showToast(`Admin authorized. Tenant Parent_id: ${data.Parent_id}`, 'success');
                admin.password.value = '';
            } else {
                showToast(data.reason || 'Admin authentication failed.', 'error');
            }
        } catch (err) {
            console.error('Admin Login Error:', err);
            showToast('Network error while connecting to Admin Login API.', 'error');
        }
    }

    async function handleAdminAccountAction(method) {
        const username = admin.username.value.trim();
        const password = admin.password.value.trim();

        if (!username || !password) {
            showToast('Admin username and password are required.', 'warning');
            return;
        }

        try {
            const response = await fetch('/api/admin', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ method, username, password })
            });

            const data = await response.json();

            if (!data.error) {
                if (method === 'add') {
                    state.parentId = data.Parent_id;
                    sessionStorage.setItem('cybersyn_parent_id', data.Parent_id);
                    updateAdminAuthState();
                    showToast(`Admin registered successfully. Assigned Parent_id: ${data.Parent_id}`, 'success');
                } else {
                    handleAdminLogout();
                    showToast('Admin account removed successfully.', 'info');
                }
            } else {
                showToast(data.error_message || `Admin action '${method}' failed.`, 'error');
            }
        } catch (err) {
            console.error('Admin API Error:', err);
            showToast(`Gateway connection error during admin ${method}.`, 'error');
        }
    }

    function handleAdminLogout() {
        state.parentId = null;
        sessionStorage.removeItem('cybersyn_parent_id');
        updateAdminAuthState();
        showToast('Admin session signed out.', 'info');
    }

    // ==========================================
    // 3 & 4. EMPLOYEE APIs (/api/admin/employee & /login)
    // ==========================================
    async function handleEmployeeLogin() {
        if (!state.parentId) {
            showToast('Step 1 Required: Please authenticate as Admin first.', 'warning');
            return;
        }

        const username = employee.username.value.trim();
        const password = employee.password.value.trim();

        if (!username || !password) {
            showToast('Please enter employee credentials.', 'warning');
            return;
        }

        try {
            const response = await fetch('/api/admin/employee/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    Parent_id: state.parentId,
                    username,
                    password
                })
            });

            const data = await response.json();

            if (!data.error) {
                state.employeeId = data.Employee_id;
                state.employeeUsername = username;
                sessionStorage.setItem('cybersyn_employee_id', data.Employee_id);
                sessionStorage.setItem('cybersyn_employee_user', username);

                workspace.displayUser.textContent = username;
                workspace.displayParent.textContent = `Admin ID: ${state.parentId}`;

                workspace.chatStream.innerHTML = '';
                if (Array.isArray(data.CHAT_LOGS) && data.CHAT_LOGS.length > 0) {
                    renderChatLogs(data.CHAT_LOGS);
                } else {
                    appendSystemMessage('Protected AI session active. All active DLP scanner stages are standing by.');
                }

                switchView('workspace');
                showToast(`Welcome, ${username}! AI Workspace unlocked.`, 'success');
            } else {
                showToast(data.error_message || 'Employee login failed.', 'error');
            }
        } catch (err) {
            console.error('Employee Login Error:', err);
            showToast('Gateway connection error during employee login.', 'error');
        }
    }

    async function handleEmployeeAccountAction(method) {
        if (!state.parentId) {
            showToast('Admin verification required before managing employees.', 'warning');
            return;
        }

        const username = employee.username.value.trim();
        const password = employee.password.value.trim();

        if (!username || !password) {
            showToast('Employee username and password are required.', 'warning');
            return;
        }

        try {
            const response = await fetch('/api/admin/employee', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    method,
                    Parent_id: state.parentId,
                    username,
                    password
                })
            });

            const data = await response.json();

            if (!data.error) {
                showToast(`Employee '${username}' ${method === 'add' ? 'created' : 'removed'} successfully.`, 'success');
                employee.password.value = '';
            } else {
                showToast(data.error_message || `Employee action '${method}' failed.`, 'error');
            }
        } catch (err) {
            console.error('Employee Management Error:', err);
            showToast(`Gateway connection error during employee ${method}.`, 'error');
        }
    }

    function handleWorkspaceLogout() {
        state.employeeId = null;
        state.employeeUsername = null;
        sessionStorage.removeItem('cybersyn_employee_id');
        sessionStorage.removeItem('cybersyn_employee_user');
        switchView('portal');
        showToast('Signed out of AI workspace.', 'info');
    }

    // ==========================================
    // 5. SETTINGS API (/api/admin/employee/settings)
    // ==========================================
    async function syncSettingsWithBackend() {
        if (!state.parentId || !state.employeeId) {
            showToast('Authentication required before synchronizing settings.', 'warning');
            return;
        }

        const settingsPayload = {
            Parent_id: state.parentId,
            Employee_id: state.employeeId,
            check1: Boolean(workspace.check1.checked),
            check2: Boolean(workspace.check2.checked),
            check3: Boolean(workspace.check3.checked),
            API_KEY: workspace.apiKey.value.trim(),
            MODEL_NAME: workspace.modelName.value.trim() || 'gpt-4o-mini'
        };

        try {
            workspace.btnSaveSettings.disabled = true;
            workspace.btnSaveSettings.textContent = 'Syncing...';

            const response = await fetch('/api/admin/employee/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settingsPayload)
            });

            const data = await response.json();

            if (response.ok && !data.error) {
                state.settings = {
                    check1: data.check1 !== undefined ? Boolean(data.check1) : settingsPayload.check1,
                    check2: data.check2 !== undefined ? Boolean(data.check2) : settingsPayload.check2,
                    check3: data.check3 !== undefined ? Boolean(data.check3) : settingsPayload.check3,
                    API_KEY: data.API_KEY !== undefined ? data.API_KEY : settingsPayload.API_KEY,
                    MODEL_NAME: data.MODEL_NAME || settingsPayload.MODEL_NAME
                };

                applySettingsToUI();
                sessionStorage.setItem('cybersyn_settings', JSON.stringify(state.settings));

                workspace.syncBadge.textContent = 'Synced';
                workspace.syncBadge.classList.remove('unsaved');
                showToast('DLP scanner rules & model settings updated.', 'success');
            } else {
                showToast(data.error_message || 'Failed to update settings.', 'error');
            }
        } catch (err) {
            console.error('Settings API Error:', err);
            showToast('Network error while saving settings.', 'error');
        } finally {
            workspace.btnSaveSettings.disabled = false;
            workspace.btnSaveSettings.textContent = 'Save Configuration';
        }
    }

    // ==========================================
    // 6. AI CHAT & DLP API (/api/admin/employee/chat)
    // ==========================================
    async function handleChatSubmit(event) {
        if (event) event.preventDefault();

        const promptText = workspace.promptInput.value.trim();
        if (!promptText) return;

        appendMessageBubble(promptText, 'user');
        workspace.promptInput.value = '';

        await sendChatPrompt(promptText, false);
    }

    async function sendChatPrompt(promptText, isBypass = false) {
        if (!state.parentId || !state.employeeId) {
            showToast('Session expired. Please sign in again.', 'error');
            return;
        }

        const chatPayload = {
            Parent_id: state.parentId,
            Employee_id: state.employeeId,
            check1: Boolean(workspace.check1.checked),
            check2: Boolean(workspace.check2.checked),
            check3: Boolean(workspace.check3.checked),
            API_KEY: workspace.apiKey.value.trim(),
            MODEL_NAME: workspace.modelName.value.trim() || 'gpt-4o-mini',
            prompt: promptText,
            bypass: Boolean(isBypass)
        };

        const scanId = appendScanningIndicator(isBypass);

        try {
            workspace.btnSendPrompt.disabled = true;

            const response = await fetch('/api/admin/employee/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(chatPayload)
            });

            const data = await response.json();
            removeScanningIndicator(scanId);

            // CASE 1: Prompt Blocked by DLP Firewall
            if (data.blocked === true) {
                const blockInfo = data.block_info || {
                    stage: 'DLP Inspection',
                    main_cause: 'Sensitive Content Detected',
                    score: 1.0,
                    matches: []
                };

                state.lastInterceptedPrompt = promptText;
                appendInterceptChatCard(blockInfo);
                openInterceptModal(blockInfo);
                showToast(`Intercepted by ${blockInfo.stage || 'DLP Firewall'}`, 'error');
                return;
            }

            // CASE 2: Prompt Approved & Replied by AI
            if (data.blocked === false) {
                const reply = data.reply_message || 'Prompt processed successfully.';
                appendMessageBubble(reply, 'ai', isBypass);

                if (isBypass) {
                    closeInterceptModal();
                    showToast('Prompt executed under administrative bypass.', 'warning');
                }
            } else if (data.error) {
                showToast(data.error_message || 'Gateway returned an error while processing prompt.', 'error');
            }
        } catch (err) {
            removeScanningIndicator(scanId);
            console.error('Chat API Error:', err);
            showToast('Network error while communicating with Chat Gateway.', 'error');
        } finally {
            workspace.btnSendPrompt.disabled = false;
        }
    }

    async function handleExecuteBypass() {
        if (!state.lastInterceptedPrompt) {
            showToast('No intercepted prompt found to bypass.', 'warning');
            return;
        }

        const bypassPassword = modal.bypassPassword.value.trim();

        // If admin entered a password, verify against /api/admin/login first
        if (bypassPassword && admin.username.value.trim()) {
            try {
                const verifyRes = await fetch('/api/admin/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        username: admin.username.value.trim(),
                        password: bypassPassword
                    })
                });

                const verifyData = await verifyRes.json();
                if (!verifyData.success) {
                    showToast('Authorization denied: Invalid admin password.', 'error');
                    return;
                }
            } catch (err) {
                console.error('Bypass verification error:', err);
            }
        }

        modal.bypassPassword.value = '';
        await sendChatPrompt(state.lastInterceptedPrompt, true);
    }

    // ==========================================
    // DOM Rendering & Formatting
    // ==========================================
    function appendMessageBubble(text, sender, isBypass = false) {
        const bubble = document.createElement('div');
        bubble.className = `message-bubble ${sender}-bubble ${isBypass ? 'bypassed' : ''}`;

        let headerLabel = sender === 'user'
            ? (state.employeeUsername || 'Employee')
            : `AI Model (${workspace.modelName.value.trim() || 'Response'})`;

        if (sender === 'ai' && isBypass) {
            headerLabel += ' — [ADMIN BYPASS]';
        }

        bubble.innerHTML = `
            <div class="bubble-header">${escapeHTML(headerLabel)}</div>
            <div class="bubble-content">${escapeHTML(text)}</div>
        `;

        workspace.chatStream.appendChild(bubble);
        workspace.chatStream.scrollTop = workspace.chatStream.scrollHeight;
    }

    function appendSystemMessage(text) {
        const bubble = document.createElement('div');
        bubble.className = 'message-bubble system-bubble';
        bubble.innerHTML = `
            <div class="bubble-header">System Notification</div>
            <div class="bubble-content">${escapeHTML(text)}</div>
        `;
        workspace.chatStream.appendChild(bubble);
        workspace.chatStream.scrollTop = workspace.chatStream.scrollHeight;
    }

    function appendScanningIndicator(isBypass) {
        const id = 'scan-' + Date.now();
        const bubble = document.createElement('div');
        bubble.id = id;
        bubble.className = 'message-bubble scanning-bubble';
        bubble.textContent = isBypass
            ? '⚡ Forwarding prompt directly to model (bypass: true)...'
            : '🛡️ Inspecting prompt through active CyberSyn DLP stages...';
        workspace.chatStream.appendChild(bubble);
        workspace.chatStream.scrollTop = workspace.chatStream.scrollHeight;
        return id;
    }

    function removeScanningIndicator(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    function appendInterceptChatCard(blockInfo) {
        const bubble = document.createElement('div');
        bubble.className = 'message-bubble intercept-bubble';
        bubble.innerHTML = `
            <div class="bubble-header" style="color: var(--color-danger)">⚠️ DLP Interception Alert</div>
            <div class="bubble-content">
                <strong>Stage:</strong> ${escapeHTML(blockInfo.stage || 'DLP Inspector')} |
                <strong>Cause:</strong> ${escapeHTML(blockInfo.main_cause || 'Security Policy Violation')} |
                <strong>Score:</strong> ${escapeHTML(String(blockInfo.score ?? '1.0'))}
            </div>
        `;
        workspace.chatStream.appendChild(bubble);
        workspace.chatStream.scrollTop = workspace.chatStream.scrollHeight;
    }

    function renderChatLogs(logs) {
        logs.forEach(entry => {
            if (typeof entry === 'string') {
                appendMessageBubble(entry, 'ai');
            } else if (entry && typeof entry === 'object') {
                if (entry.prompt || entry.user) {
                    appendMessageBubble(entry.prompt || entry.user, 'user');
                }
                if (entry.reply_message || entry.response || entry.bot) {
                    appendMessageBubble(entry.reply_message || entry.response || entry.bot, 'ai');
                }
            }
        });
    }

    function openInterceptModal(blockInfo) {
        modal.stage.textContent = blockInfo.stage || 'Inspection Pipeline';
        modal.cause.textContent = blockInfo.main_cause || 'Security Rule Triggered';
        modal.score.textContent = typeof blockInfo.score === 'number'
            ? blockInfo.score.toFixed(2)
            : String(blockInfo.score ?? '1.00');

        modal.matches.innerHTML = '';
        if (Array.isArray(blockInfo.matches) && blockInfo.matches.length > 0) {
            blockInfo.matches.forEach(m => {
                const item = document.createElement('div');
                item.className = 'match-item';
                item.innerHTML = `
                    <div class="match-header">
                        <span>Rule: ${escapeHTML(m.rule || 'DLP Trigger')}</span>
                        <span>Line: ${escapeHTML(String(m.line ?? 1))}</span>
                    </div>
                    <div class="match-snippet">${escapeHTML(m.snippet || m.match || 'Sensitive token detected')}</div>
                `;
                modal.matches.appendChild(item);
            });
        } else {
            modal.matches.innerHTML = '<div class="match-item">Blocked based on contextual or model risk threshold.</div>';
        }

        modal.bypassPanel.classList.add('hidden');
        modal.bypassPassword.value = '';
        modal.container.classList.remove('hidden');
    }

    function closeInterceptModal() {
        modal.container.classList.add('hidden');
    }

    function escapeHTML(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // ==========================================
    // Event Listeners Binding
    // ==========================================
    // Admin events
    admin.btnLogin.addEventListener('click', handleAdminLogin);
    admin.btnRegister.addEventListener('click', () => handleAdminAccountAction('add'));
    admin.btnDelete.addEventListener('click', () => handleAdminAccountAction('remove'));
    admin.btnLogout.addEventListener('click', handleAdminLogout);

    // Employee events
    employee.btnLogin.addEventListener('click', handleEmployeeLogin);
    employee.btnCreate.addEventListener('click', () => handleEmployeeAccountAction('add'));
    employee.btnDelete.addEventListener('click', () => handleEmployeeAccountAction('remove'));

    // Settings listeners (auto-sync on checkbox change + input listeners)
    [workspace.check1, workspace.check2, workspace.check3].forEach(chk => {
        chk.addEventListener('change', () => {
            markSettingsUnsaved();
            syncSettingsWithBackend();
        });
    });

    workspace.modelName.addEventListener('input', markSettingsUnsaved);
    workspace.apiKey.addEventListener('input', markSettingsUnsaved);
    workspace.btnSaveSettings.addEventListener('click', syncSettingsWithBackend);

    // Chat listeners
    workspace.btnLogout.addEventListener('click', handleWorkspaceLogout);
    workspace.chatForm.addEventListener('submit', handleChatSubmit);
    workspace.btnClearChat.addEventListener('click', () => {
        workspace.chatStream.innerHTML = '';
        appendSystemMessage('Chat view cleared.');
    });

    workspace.promptInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleChatSubmit();
        }
    });

    // Intercept Modal listeners
    modal.btnClose.addEventListener('click', closeInterceptModal);
    modal.btnDismiss.addEventListener('click', closeInterceptModal);
    modal.toggleBypass.addEventListener('click', () => {
        modal.bypassPanel.classList.toggle('hidden');
    });
    modal.btnExecuteBypass.addEventListener('click', handleExecuteBypass);

    // ==========================================
    // Bootstrap Session
    // ==========================================
    updateAdminAuthState();
    if (state.parentId && state.employeeId) {
        workspace.displayUser.textContent = state.employeeUsername || 'Employee';
        workspace.displayParent.textContent = `Admin ID: ${state.parentId}`;
        switchView('workspace');
    } else {
        switchView('portal');
    }
});
