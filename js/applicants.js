(() => {
    "use strict";

    const script = document.currentScript;
    const vacancyId = script?.dataset.vacancyId;

    if (!vacancyId) {
        console.error("Applicants live refresh: vacancy ID is missing.");
        return;
    }

    const POLL_MS = 5000;

    const listEl = document.getElementById("applicants-list");
    const emptyEl = document.getElementById("empty-results");
    const resultsEl = document.getElementById("results-card");
    const liveEl = document.getElementById("live-status");
    const liveTextEl = document.getElementById("live-status-text");

    const cards = new Map();          // application id -> card element
    const latest = new Map();         // application id -> latest applicant data
    const expanded = new Set();       // ids of expanded cards
    const detailsCache = new Map();   // id -> { data, sig, loading, error }

    let requirements = { education: true, experience: true };
    let busy = false;
    let stopped = false;
    let timer = null;

    /* ---------------------------------------------------------
       Small helpers (text is always set with textContent)
       --------------------------------------------------------- */

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function toNumber(value) {
        if (value === null || value === undefined || value === "") return null;
        const number = Number(value);
        return Number.isFinite(number) ? number : null;
    }

    function fmt(value) {
        const number = toNumber(value);
        return number === null ? null : number.toFixed(2);
    }

    function humanize(value) {
        return String(value || "")
            .replace(/_/g, " ")
            .replace(/\b\w/g, c => c.toUpperCase());
    }

    function cssToken(value) {
        return String(value || "").toLowerCase().replace(/[^a-z0-9_-]/g, "");
    }

    function setLive(text, state) {
        if (liveTextEl) liveTextEl.textContent = text;
        if (liveEl) liveEl.dataset.state = state;
    }

    // value present -> number; otherwise Pending / Not required / dash.
    function scoreInfo(value, options = {}) {
        const formatted = fmt(value);

        if (formatted !== null) return { text: formatted, kind: "value" };

        if (options.required === false) {
            return { text: "Not required", kind: "muted" };
        }

        if (options.pending) return { text: "Pending", kind: "pending" };

        return { text: "—", kind: "muted" };
    }

    // Ineligible = the red eligibility tag (anything that is not
    // "eligible" and not a verification status).
    function isIneligible(a) {
        const eligibility = String(a.eligibility || "").toLowerCase();
        if (!eligibility) return false;
        if (eligibility === "eligible") return false;
        if (eligibility.includes("verif")) return false;
        return true;
    }

    // Ineligible candidates never get a rank number.
    function effectiveRank(a) {
        if (isIneligible(a)) return null;
        return toNumber(a.rank);
    }

    /* ---------------------------------------------------------
       Card skeleton
       --------------------------------------------------------- */

    function sumCell(name, label) {
        const cell = el("div", `sum-cell cell-${name}`);
        cell.dataset.label = label;
        return cell;
    }

    function createCard(id) {
        const card = el("article", "applicant-card");
        card.dataset.applicationId = id;

        const summary = el("button", "card-summary");
        summary.type = "button";
        summary.setAttribute("aria-expanded", "false");
        summary.setAttribute("aria-controls", `applicant-panel-${id}`);

        const refs = {
            summary,
            rank: sumCell("rank", "Rank"),
            candidate: sumCell("candidate", "Candidate"),
            score: sumCell("score", "Final Score /100"),
            grade: sumCell("grade", "Grade"),
            eligibility: sumCell("eligibility", "Eligibility"),
            status: sumCell("status", "Matching Status"),
            chevron: sumCell("chevron", ""),
            panel: el("div", "card-details")
        };

        refs.chevron.append(el("span", "chevron"));
        refs.panel.id = `applicant-panel-${id}`;
        refs.panel.hidden = true;

        summary.append(
            refs.rank, refs.candidate, refs.score, refs.grade,
            refs.eligibility, refs.status, refs.chevron
        );

        card.append(summary, refs.panel);
        card._r = refs;
        card._panelSig = null;

        return card;
    }

    /* ---------------------------------------------------------
       Collapsed summary
       --------------------------------------------------------- */

    function updateSummary(card, a) {
        const r = card._r;

        const rank = effectiveRank(a);

        r.rank.replaceChildren(
            el("span", "rank-value", rank === null ? "—" : `#${rank}`)
        );

        r.candidate.replaceChildren(
            el("strong", null, a.full_name || "Unnamed Candidate"),
            el("span", null, a.email || "No email")
        );

        const finalScore = fmt(a.match_score);
        if (finalScore !== null) {
            r.score.replaceChildren(el("span", "final-score", finalScore));
        } else {
            r.score.replaceChildren(el("span", "pending", "Pending"));
        }

        if (a.grade) {
            r.grade.replaceChildren(
                el("span", `grade-badge grade-${cssToken(a.grade)}`, a.grade)
            );
        } else {
            r.grade.replaceChildren(el("span", "muted-dash", "—"));
        }

        const eligibility = String(a.eligibility || "").toLowerCase();
        if (eligibility) {
            let tone = "bad";
            if (eligibility === "eligible") tone = "good";
            else if (eligibility.includes("verif")) tone = "warn";

            r.eligibility.replaceChildren(
                el("span", `elig-chip elig-${tone}`, humanize(eligibility))
            );
        } else {
            r.eligibility.replaceChildren(el("span", "pending", "Pending"));
        }

        r.status.replaceChildren(
            el("span", "status-text matching-status",
               humanize(a.matching_status || "pending"))
        );
    }

    /* ---------------------------------------------------------
       Expanded panel sections
       --------------------------------------------------------- */

    function sectionWithTitle(title) {
        const section = el("section", "detail-section");
        section.append(el("h3", null, title));
        return section;
    }

    function scoreTile(label, info) {
        const tile = el("div", `score-tile is-${info.kind}`);
        tile.append(el("span", "tile-label", label), el("strong", "tile-value", info.text));
        return tile;
    }

    function scoresSection(a) {
        const section = sectionWithTitle("Scores");
        const grid = el("div", "score-grid");

        grid.append(
            scoreTile("Final Score /100", scoreInfo(a.match_score, { pending: true })),
            scoreTile("CV Score /100", scoreInfo(a.cv_match_score)),
            scoreTile("Skills Match /100", scoreInfo(a.skills_score)),
            scoreTile("Experience Match /100", scoreInfo(a.experience_score, {
                required: requirements.experience, pending: true
            })),
            scoreTile("Education /10", scoreInfo(a.education_score, {
                required: requirements.education, pending: true
            })),
            scoreTile("Interview /10", scoreInfo(a.interview_score, { pending: true }))
        );

        section.append(grid);
        return section;
    }

    function contactSection(a) {
        const section = sectionWithTitle("Candidate");
        const list = el("div", "contact-list");

        const items = [
            ["Email", a.email],
            ["Phone", a.phone],
            ["Applied", a.applied_at]
        ];

        for (const [label, value] of items) {
            if (!value) continue;
            const item = el("div", "contact-item");
            item.append(el("span", "contact-label", label), el("span", null, value));
            list.append(item);
        }

        if (!list.children.length) return null;

        section.append(list);
        return section;
    }

    function explanationSection(a) {
        if (!a.match_explanation) return null;

        const section = sectionWithTitle("Match explanation");
        section.append(el("p", "explanation-text", String(a.match_explanation)));
        return section;
    }

    function trimNumber(value) {
        return String(Number(Number(value).toFixed(2)));
    }

    // Education / experience verification questions are not shown here.
    function isVerificationItem(item) {
        const kind = String(item.category || "").toLowerCase();
        return (
            kind.includes("verification") ||
            kind.includes("education") ||
            kind.includes("experience")
        );
    }

    function qaItem(item, index) {
        const label = `Question ${index + 1}`;

        const wrap = el("div", "qa-item");
        const head = el("div", "qa-head");
        head.append(el("span", "qa-label", label));

        const score = toNumber(item.score);
        const status = String(item.status || "").toLowerCase();

        if (score !== null) {
            const text = item.max_score != null
                ? `${trimNumber(score)} / ${item.max_score}`
                : trimNumber(score);
            head.append(el("span", "chip chip-ok", text));
        } else if (status === "failed") {
            head.append(el("span", "chip chip-bad", "Assessment failed"));
        } else {
            head.append(el("span", "pending", "Pending"));
        }

        wrap.append(head);

        if (item.question) wrap.append(el("p", "qa-question", item.question));
        wrap.append(el("p", "qa-answer", item.answer || "—"));

        if (item.feedback) {
            wrap.append(el("p", "qa-feedback", item.feedback));
        }

        return wrap;
    }

    function answersSection(entry) {
        const section = sectionWithTitle("Interview answers");

        if (!entry || (!entry.data && !entry.error)) {
            section.append(el("p", "detail-empty", "Loading…"));
            return section;
        }

        if (!entry.data) {
            section.append(el("p", "detail-empty", "Unable to load interview answers."));
            return section;
        }

        const allAnswers = Array.isArray(entry.data.answers) ? entry.data.answers : [];
        const answers = allAnswers.filter(item => !isVerificationItem(item));

        if (!answers.length) {
            section.append(el("p", "detail-empty", "No interview answers yet."));
            return section;
        }

        answers.sort((x, y) =>
            (toNumber(x.question_number) ?? 0) - (toNumber(y.question_number) ?? 0)
        );

        const list = el("div", "qa-list");
        answers.forEach((item, index) => list.append(qaItem(item, index)));
        section.append(list);
        return section;
    }

      function emailButton(action, label, applicationId) {
        const button = el("button", "email-button", label);
        button.type = "button";
        button.dataset.seAction = action;
        button.dataset.applicationId = applicationId;
        return button;
    }

    function sentBadge(a) {
        const id = String(a.application_id);
        const lib = window.selectionEmail;
        const sentAt =
            (lib && lib.sent.get(id)) || a.selection_email_sent_at || null;

        const badge = el("span", "email-sent-badge");
        badge.dataset.applicationId = id;

        if (sentAt && lib) {
            badge.textContent = lib.label(sentAt);
        } else {
            badge.hidden = true;
        }

        return badge;
    }

    function actionsSection(a, entry) {
        const wrap = el("div", "detail-actions");

        if (entry?.data && entry.data.has_cv === false) {
            wrap.append(el("span", "detail-empty", "Original CV file is not available."));
        } else {
            const link = el("a", "download-button", "Download original CV");
            link.href = `/api/applications/${encodeURIComponent(a.application_id)}/resume`;
            link.setAttribute("download", "");
            wrap.append(link);
        }

        const id = String(a.application_id);

        wrap.append(
            emailButton("send-email", "Send Email", id),
            emailButton("edit-send-email", "Edit & Send", id),
            sentBadge(a)
        );

        return wrap;
    }
    function renderPanel(card, a) {
        const id = String(a.application_id);
        const entry = detailsCache.get(id);

        const signature = JSON.stringify([
            a, requirements,
            entry ? entry.sig : null,
            entry ? Boolean(entry.error) : false,
            entry ? Boolean(entry.data) : false
        ]);

        if (card._panelSig === signature) return;
        card._panelSig = signature;

        const parts = [
            scoresSection(a),
            contactSection(a),
            explanationSection(a),
            answersSection(entry),
            actionsSection(a, entry)
        ].filter(Boolean);

        card._r.panel.replaceChildren(...parts);
    }

    /* ---------------------------------------------------------
       Lazy-loaded details (interview answers)
       --------------------------------------------------------- */

    async function loadDetails(id) {
        const entry = detailsCache.get(id) || {};
        if (entry.loading) return;

        entry.loading = true;
        detailsCache.set(id, entry);

        try {
            const response = await fetch(
                `/api/applications/${encodeURIComponent(id)}/details`,
                {
                    credentials: "same-origin",
                    cache: "no-store",
                    headers: { Accept: "application/json" }
                }
            );

            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();
            if (!data.success) throw new Error(data.message || "Invalid response");

            entry.data = data;
            entry.sig = JSON.stringify([data.answers, data.match_result, data.has_cv]);
            entry.error = null;

        } catch (error) {
            entry.error = String(error.message || error);
        } finally {
            entry.loading = false;
        }

        const card = cards.get(id);
        const applicant = latest.get(id);

        if (card && applicant && expanded.has(id)) renderPanel(card, applicant);
    }

    function toggleCard(card) {
        const id = card.dataset.applicationId;
        const open = !expanded.has(id);

        if (open) expanded.add(id);
        else expanded.delete(id);

        card.classList.toggle("is-open", open);
        card._r.summary.setAttribute("aria-expanded", String(open));
        card._r.panel.hidden = !open;

        if (open) {
            const applicant = latest.get(id);
            if (applicant) renderPanel(card, applicant);
            loadDetails(id);
        }
    }

    /* ---------------------------------------------------------
       List rendering (keyed, so expanded cards stay open)
       --------------------------------------------------------- */

    function compareApplicants(a, b) {
        const rankA = effectiveRank(a);
        const rankB = effectiveRank(b);

        if (rankA !== null && rankB !== null && rankA !== rankB) return rankA - rankB;
        if (rankA !== null && rankB === null) return -1;
        if (rankA === null && rankB !== null) return 1;

        const scoreA = toNumber(a.match_score);
        const scoreB = toNumber(b.match_score);

        if (scoreA !== null && scoreB !== null && scoreA !== scoreB) return scoreB - scoreA;
        if (scoreA !== null && scoreB === null) return -1;
        if (scoreA === null && scoreB !== null) return 1;

        return String(a.applied_at || "").localeCompare(String(b.applied_at || ""));
    }

    function updateCounters(applicants) {
        const total = document.getElementById("total-applicants-count");
        const matches = document.getElementById("completed-matches-count");
        const interviews = document.getElementById("completed-interviews-count");

        if (total) total.textContent = applicants.length;

        if (matches) {
            matches.textContent = applicants.filter(a =>
                ["completed", "preliminary_completed"].includes(
                    String(a.matching_status || "").toLowerCase()
                )
            ).length;
        }

        if (interviews) {
            interviews.textContent = applicants.filter(
                a => a.interview_score != null
            ).length;
        }
    }

    function render(applicants) {
        latest.clear();
        for (const a of applicants) latest.set(String(a.application_id), a);

        // Remove cards for applications that no longer exist.
        for (const [id, card] of cards) {
            if (!latest.has(id)) {
                card.remove();
                cards.delete(id);
                expanded.delete(id);
                detailsCache.delete(id);
            }
        }

        const sorted = [...applicants].sort(compareApplicants);

        sorted.forEach((a, index) => {
            const id = String(a.application_id);
            let card = cards.get(id);

            if (!card) {
                card = createCard(id);
                cards.set(id, card);
            }

            updateSummary(card, a);

            if (expanded.has(id)) renderPanel(card, a);

            if (listEl.children[index] !== card) {
                listEl.insertBefore(card, listEl.children[index] || null);
            }
        });

        const hasApplicants = applicants.length > 0;
        if (emptyEl) emptyEl.hidden = hasApplicants;
        if (resultsEl) resultsEl.hidden = !hasApplicants;

        updateCounters(applicants);
    }

    /* ---------------------------------------------------------
       Polling
       --------------------------------------------------------- */

    function timeLabel() {
        return new Date().toLocaleTimeString([], {
            hour: "2-digit", minute: "2-digit", second: "2-digit"
        });
    }

    async function refresh() {
        if (busy || stopped || document.hidden) return;
        busy = true;

        try {
            const response = await fetch(
                `/api/vacancies/${encodeURIComponent(vacancyId)}/applicants`,
                {
                    credentials: "same-origin",
                    cache: "no-store",
                    headers: { Accept: "application/json" }
                }
            );

            if (response.status === 401) {
                stopped = true;
                if (timer) window.clearInterval(timer);
                setLive("Session expired. Please log in again.", "error");
                return;
            }

            if (!response.ok) {
                throw new Error(`Applicants API returned HTTP ${response.status}`);
            }

            const data = await response.json();

            if (!data.success || !Array.isArray(data.applicants)) {
                throw new Error(data.message || "Invalid applicants response");
            }

            if (data.requirements) requirements = data.requirements;

            render(data.applicants);
            setLive(`Live · updated ${timeLabel()}`, "ok");

            // Keep expanded cards (interview answers) current as well.
            for (const id of expanded) loadDetails(id);

        } catch (error) {
            console.error("Applicants auto-refresh failed:", error);
            setLive("Reconnecting…", "warn");
        } finally {
            busy = false;
        }
    }

    function readInitialData() {
        const node = document.getElementById("applicants-data");
        if (!node) return null;

        try {
            const data = JSON.parse(node.textContent || "{}");
            return Array.isArray(data.applicants) ? data : null;
        } catch (error) {
            console.error("Applicants initial data is invalid:", error);
            return null;
        }
    }

    listEl.addEventListener("click", event => {
        const button = event.target.closest(".card-summary");
        if (!button) return;

        const card = button.closest(".applicant-card");
        if (card) toggleCard(card);
    });

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) refresh();
    });

    const initial = readInitialData();

    if (initial) {
        if (initial.requirements) requirements = initial.requirements;
        render(initial.applicants);
    }

    refresh();
    timer = window.setInterval(refresh, POLL_MS);
})();