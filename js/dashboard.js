
 // ============================================================
 // RESUMEMATCH AI
 // DASHBOARD JAVASCRIPT
 // ============================================================

document.addEventListener("DOMContentLoaded", () => {

    const greetingText = document.getElementById("greetingText");
    const totalVacanciesKpi = document.getElementById("totalVacanciesKpi");
    const activeVacanciesKpi = document.getElementById("activeVacanciesKpi");
    const totalCandidatesKpi = document.getElementById("totalCandidatesKpi");
    const strongCandidatesKpi = document.getElementById("strongCandidatesKpi");
    const vacancyList = document.getElementById("vacancyList");
    const vacancyPerformanceChart = document.getElementById("vacancyPerformanceChart");

    // ========================================================
    // GREETING
    // ========================================================

    function updateGreeting() {
        if (!greetingText) return;

        const hour = new Date().getHours();
        let greeting;

        if (hour >= 5 && hour < 12) greeting = "Good morning";
        else if (hour >= 12 && hour < 18) greeting = "Good afternoon";
        else if (hour >= 18 && hour < 22) greeting = "Good evening";
        else greeting = "Good night";

        const name = String(
            greetingText.dataset.userName || "Ayesha"
        ).trim();

        greetingText.textContent = `${greeting}, ${name}`;
    }

    updateGreeting();
    setInterval(updateGreeting, 60000);

    // ========================================================
    // FETCH DASHBOARD
    // ========================================================

    async function refreshDashboard() {
        try {
            const response = await fetch("/api/dashboard/summary", {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                headers: {
                    "Accept": "application/json",
                    "Cache-Control": "no-cache"
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            if (!data || !data.stats) {
                throw new Error("Invalid dashboard response.");
            }

            // =================================================
            // EXISTING KPIs — UNCHANGED
            // =================================================

            if (totalVacanciesKpi) {
                totalVacanciesKpi.textContent =
                    Number(data.stats.total_vacancies || 0);
            }

            if (activeVacanciesKpi) {
                activeVacanciesKpi.textContent =
                    Number(data.stats.active_vacancies || 0);
            }

            if (totalCandidatesKpi) {
                totalCandidatesKpi.textContent =
                    Number(data.stats.total_candidates || 0);
            }

            if (strongCandidatesKpi) {
                strongCandidatesKpi.textContent =
                    Number(data.stats.strong_candidates || 0);
            }

            // =================================================
            // RECENT VACANCIES — UNCHANGED
            // =================================================

            const vacancies = data.recent_vacancies || [];
            renderRecentVacancies(vacancies);

            // =================================================
            // NEW: VACANCY PERFORMANCE CHART
            // =================================================

            renderVacancyPerformance(vacancies);

        } catch (error) {
            console.error("Dashboard update error:", error);

            if (vacancyPerformanceChart &&
                !vacancyPerformanceChart.dataset.loaded) {
                vacancyPerformanceChart.innerHTML = `
                    <div class="chart-empty">
                        Unable to load vacancy performance.
                        Please try refreshing the page.
                    </div>
                `;
            }
        }
    }

    // ========================================================
    // RECENT VACANCIES
    // ========================================================

    function renderRecentVacancies(vacancies) {
        if (!vacancyList) return;

        if (!Array.isArray(vacancies) || vacancies.length === 0) {
            vacancyList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">
                        <svg viewBox="0 0 24 24">
                            <rect x="3" y="6" width="18" height="15" rx="2"></rect>
                            <path d="M8 6V4.5A1.5 1.5 0 0 1 9.5 3h5A1.5 1.5 0 0 1 16 4.5V6"></path>
                        </svg>
                    </div>
                    <h3>No vacancies yet</h3>
                    <p>Create your first vacancy to start receiving applications.</p>
                    <a href="/create-vacancy" class="primary-button">
                        Create Vacancy
                    </a>
                </div>
            `;
            return;
        }

        vacancyList.innerHTML = vacancies.slice(0, 5).map(vacancy => {
            const title = escapeHTML(vacancy.job_title || "Untitled Vacancy");
            const date = escapeHTML(vacancy.opening_date || "");
            const status = escapeHTML(vacancy.status || "");
            const applications = Number(vacancy.applications || 0);

            return `
                <div class="vacancy-row">
                    <div class="vacancy-info">
                        <div class="vacancy-title">${title}</div>
                        <div class="vacancy-meta">
                            ${date ? `<span>${date}</span>` : ""}
                            ${status ? `
                                ${date ? '<span class="dot-separator">•</span>' : ""}
                                <span>${status}</span>
                            ` : ""}
                        </div>
                    </div>
                    <div class="vacancy-applications">
                        <strong>${applications}</strong>
                        <span>applications</span>
                    </div>
                </div>
            `;
        }).join("");
    }

    // ========================================================
    // VACANCY PERFORMANCE
    // ========================================================

    function renderVacancyPerformance(vacancies) {
        if (!vacancyPerformanceChart) return;

        if (!Array.isArray(vacancies) || vacancies.length === 0) {
            vacancyPerformanceChart.innerHTML = `
                <div class="chart-empty">
                    <p>No vacancy data available yet.</p>
                    <span>Create a vacancy to see its applicant activity.</span>
                </div>
            `;
            vacancyPerformanceChart.dataset.loaded = "true";
            return;
        }

        const chartVacancies = vacancies
            .map(vacancy => ({
                title: String(vacancy.job_title || "Untitled Vacancy"),
                applications: Math.max(
                    0,
                    Number(vacancy.applications) || 0
                )
            }))
            .sort((a, b) => b.applications - a.applications)
            .slice(0, 5);

        const maxApplications = Math.max(
            1,
            ...chartVacancies.map(vacancy => vacancy.applications)
        );

        vacancyPerformanceChart.innerHTML = `
            <div class="performance-chart">
                ${chartVacancies.map((vacancy, index) => {
                    const percentage =
                        (vacancy.applications / maxApplications) * 100;

                    return `
                        <div class="performance-item">
                            <div class="performance-label">
                                <span class="performance-title"
                                      title="${escapeHTML(vacancy.title)}">
                                    ${escapeHTML(vacancy.title)}
                                </span>
                                <strong>${vacancy.applications}</strong>
                            </div>
                            <div class="performance-track">
                                <div class="performance-bar bar-${index + 1}"
                                     style="width: ${percentage}%">
                                </div>
                            </div>
                        </div>
                    `;
                }).join("")}
            </div>
            <p class="performance-footnote">
                Showing up to 5 vacancies from the dashboard data.
            </p>
        `;

        vacancyPerformanceChart.dataset.loaded = "true";
    }

    // ========================================================
    // ESCAPE HTML
    // ========================================================

    function escapeHTML(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // ========================================================
    // FIRST LOAD
    // ========================================================

    refreshDashboard();

    // ========================================================
    // AUTOMATIC REFRESH
    // ========================================================

    setInterval(refreshDashboard, 5000);

    // ========================================================
    // REFRESH WHEN TAB BECOMES ACTIVE
    // ========================================================

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            refreshDashboard();
        }
    });

});
