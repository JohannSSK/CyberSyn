(function () {
    const ADMIN_TOKEN_KEY = "cybersyn_admin_token";
    const notice = document.getElementById("team-notice");
    const cards = document.getElementById("team-cards");
    const empty = document.getElementById("team-empty");

    function el(tag, cls, text) {
        const node = document.createElement(tag);
        if (cls) node.className = cls;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function stageLabel(stage) {
        const m = /^check([0-9]+)$/i.exec(stage || "");
        return m ? "Check " + m[1] : (stage || "Unknown");
    }

    function showNotice(text) {
        notice.textContent = text;
        notice.classList.remove("hidden");
    }

    function numberCell(label, value) {
        const box = el("div", "member-num");
        box.append(el("span", "member-num-label", label), el("strong", "member-num-value", String(value)));
        return box;
    }

    function barRow(label, count, percent, fillClass) {
        const row = el("div", "bar-row");
        const top = el("div", "bar-row-top");
        top.append(el("span", "", label), el("span", "bar-row-value", count + " (" + percent + "%)"));
        const track = el("div", "bar-track");
        const fill = el("div", "bar-fill " + (fillClass || ""));
        fill.style.width = (count > 0 ? Math.max(percent, 3) : 0) + "%";
        track.appendChild(fill);
        row.append(top, track);
        return row;
    }

    function memberCard(m) {
        const card = el("article", "member-card");

        const head = el("div", "member-head");
        head.setAttribute("role", "button");
        head.setAttribute("aria-expanded", "false");
        const who = el("div", "");
        who.append(el("div", "member-name", m.username), el("div", "member-sub", m.checks_on + " of 3 checks on"));
        const right = el("div", "member-head-right");
        const donut = el("div", "member-donut");
        donut.style.setProperty("--pct", m.block_rate);
        donut.appendChild(el("span", "member-donut-text", m.block_rate + "%"));
        right.append(donut, el("span", "member-chevron"));
        head.append(who, right);

        const details = el("div", "member-details");
        const inner = el("div", "member-details-inner");

        const nums = el("div", "member-nums");
        nums.append(numberCell("Sent", m.sent), numberCell("Answered", m.answered), numberCell("Blocked", m.blocked));

        const answeredPct = m.sent ? Math.round(100 * m.answered / m.sent) : 0;
        const blockedPct = m.sent ? 100 - answeredPct : 0;
        const split = el("div", "member-split");
        const ansBar = el("div", "member-split-ans");
        ansBar.style.width = answeredPct + "%";
        const blkBar = el("div", "member-split-blk");
        blkBar.style.width = blockedPct + "%";
        split.append(ansBar, blkBar);
        const legend = el("div", "member-legend");
        legend.append(el("span", "", "Answered " + answeredPct + "%"), el("span", "", "Blocked " + blockedPct + "%"));

        const reasonsWrap = el("div", "member-list");
        if (m.reasons.length === 0) reasonsWrap.appendChild(el("div", "member-empty", "No blocked prompts yet."));
        m.reasons.forEach(r => reasonsWrap.appendChild(barRow(r.label, r.count, r.percent, "")));

        const stagesWrap = el("div", "member-list");
        if (m.stages.length === 0) stagesWrap.appendChild(el("div", "member-empty", "No checks triggered yet."));
        m.stages.forEach(s => stagesWrap.appendChild(barRow(stageLabel(s.label), s.count, s.percent, "bar-fill-check")));

        inner.append(
            nums,
            split,
            legend,
            el("div", "member-section-title", "Block reasons"),
            reasonsWrap,
            el("div", "member-section-title", "Blocks by check"),
            stagesWrap
        );

        head.addEventListener("click", () => {
            const open = !card.classList.contains("is-open");
            card.classList.toggle("is-open", open);
            head.setAttribute("aria-expanded", String(open));
        });

        details.appendChild(inner);
        card.append(head, details);
        return card;
    }

    function renderMembers(members) {
        cards.replaceChildren();
        empty.classList.toggle("hidden", members.length > 0);
        members.forEach(m => cards.appendChild(memberCard(m)));
    }

    async function load() {
        const token = localStorage.getItem(ADMIN_TOKEN_KEY);
        if (!token) {
            document.getElementById("team-admin-line").textContent = "Not signed in";
            showNotice("Sign in as an administrator first.");
            return;
        }
        notice.classList.add("hidden");
        try {
            const res = await fetch("/api/admin/team", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ token: token })
            });
            const data = await res.json();
            if (data.error) {
                if (res.status === 401) localStorage.removeItem(ADMIN_TOKEN_KEY);
                document.getElementById("team-admin-line").textContent = "Not signed in";
                showNotice(data.error_message || "Could not load the team.");
                return;
            }
            const s = data.stats;
            document.getElementById("team-admin-line").textContent = "Signed in as " + data.admin;
            document.getElementById("stat-members").textContent = s.members;
            document.getElementById("stat-sent").textContent = s.sent;
            document.getElementById("stat-blocked").textContent = s.blocked;
            document.getElementById("stat-rate").textContent = s.block_rate + "%";
            const count = data.members.length;
            document.getElementById("team-count").textContent = count + (count === 1 ? " member" : " members");
            renderMembers(data.members);
        } catch (err) {
            showNotice("Could not reach the server.");
        }
    }

    document.getElementById("btn-team-refresh").addEventListener("click", load);
    load();
})();
