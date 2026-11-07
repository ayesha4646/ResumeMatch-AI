// ============================================================
// RESUMEMATCH AI - VACANCIES PAGE
// Backend-connected version
// Original design/layout preserved
// ============================================================

document.addEventListener("DOMContentLoaded", () => {

    const vacanciesList =
        document.getElementById("vacanciesList");

    const emptyState =
        document.getElementById("emptyState");

    const searchInput =
        document.getElementById("searchInput");

    const searchBtn =
        document.getElementById("searchBtn");

    const statusFilter =
        document.getElementById("statusFilter");

    const sortFilter =
        document.getElementById("sortSelect");

    const vacancyCount =
        document.getElementById("vacancyCount");

    let vacancies = [];

    let lastSignature = "";
    let isLoading = false;


    // ========================================================
    // API HELPER
    // ========================================================

    async function apiRequest(url, options = {}) {

        const response = await fetch(url, {
            credentials: "same-origin",
            ...options,

            headers: {
                "Accept": "application/json",
                ...(options.headers || {})
            }
        });


        const contentType =
            response.headers.get("content-type") || "";


        let data = null;
        let rawText = "";


        if (contentType.includes("application/json")) {

            data =
                await response.json();

        } else {

            rawText =
                await response.text();

            try {

                data =
                    JSON.parse(rawText);

            } catch {

                data = null;
            }
        }


        if (!response.ok) {

            let message =
                data?.message ||
                data?.error ||
                `Server returned HTTP ${response.status}`;


            if (!data && rawText) {

                const cleanText =
                    rawText
                        .replace(/<[^>]*>/g, " ")
                        .replace(/\s+/g, " ")
                        .trim();


                if (cleanText) {

                    message =
                        cleanText.substring(
                            0,
                            250
                        );
                }
            }


            throw new Error(message);
        }


        if (!data) {

            throw new Error(
                "Server did not return JSON data."
            );
        }


        return data;
    }


    // ========================================================
    // LOAD VACANCIES
    // ========================================================

    async function loadVacancies(silent = false) {

        // Background refreshes never overlap each other.
        if (silent && isLoading) {
            return;
        }

        isLoading = true;

        try {

            if (!silent) {

                vacanciesList.innerHTML = `
                    <div class="vacancy-loading">
                        Loading vacancies...
                    </div>
                `;
            }


            const data =
                await apiRequest(
                    "/api/vacancies",
                    {
                        method: "GET",
                        cache: "no-store"
                    }
                );


            let list;

            if (Array.isArray(data)) {

                list = data;

            } else if (Array.isArray(data.vacancies)) {

                list = data.vacancies;

            } else {

                throw new Error(
                    data.message ||
                    "Vacancies data was not returned correctly."
                );
            }


            const normalized =
                list.map(normalizeVacancy);

            const signature =
                JSON.stringify(normalized);


            // Nothing changed on the server, so leave the page alone.
            if (silent && signature === lastSignature) {
                return;
            }


            lastSignature = signature;
            vacancies = normalized;


            if (silent) {

                renderPreservingState();

            } else {

                renderVacancies();
            }


        } catch (error) {

            // A failed background refresh should never wipe the page.
            if (silent) {

                console.warn(
                    "Vacancies auto-refresh failed:",
                    error
                );

                return;
            }


            console.error(
                "Vacancy loading error:",
                error
            );


            vacanciesList.innerHTML = `
                <div class="vacancy-error">

                    <div class="vacancy-error-icon">
                        !
                    </div>

                    <h3>
                        Unable to load vacancies
                    </h3>

                    <p>
                        ${escapeHTML(
                            error.message ||
                            "Please refresh the page."
                        )}
                    </p>

                </div>
            `;


            if (emptyState) {

                emptyState.style.display =
                    "none";
            }

        } finally {

            isLoading = false;
        }
    }


    // Re-draws the list for a background refresh while keeping
    // expanded cards open and the scroll position unchanged.
    function renderPreservingState() {

        const menuIsOpen =
            [...document.querySelectorAll(".action-menu")]
                .some(menu => menu.style.display === "block");

        // Don't close a menu the user is using. The next refresh
        // will draw the new data once the menu is closed.
        if (menuIsOpen) {

            lastSignature = "";

            return;
        }


        const expandedIds =
            [...document.querySelectorAll(".vacancy-card.expanded")]
                .map(card => card.dataset.vacancyId);

        const scrollY =
            window.scrollY;


        renderVacancies();


        expandedIds.forEach(id => {

            if (typeof window.toggleDetails === "function") {

                window.toggleDetails(id);
            }
        });


        window.scrollTo(0, scrollY);
    }


    // ========================================================
    // NORMALIZE VACANCY
    // ========================================================

    function normalizeVacancy(vacancy) {

        return {

            ...vacancy,

            id:
                vacancy.id,

            job_title:
                vacancy.job_title || "",

            job_description:
                vacancy.job_description ??
                vacancy.description ??
                "",

            location:
                vacancy.location || "",

            salary:
                vacancy.salary || "",

            employment_type:
                vacancy.employment_type || "",

            work_mode:
                vacancy.work_mode || "",

            opening_date:
                vacancy.opening_date || "",

            application_end_date:
                vacancy.application_end_date ??
                vacancy.closing_date ??
                "",

            portfolio_required:
                Boolean(
                    vacancy.portfolio_required
                ),

            applicant_count:
                Number(
                    vacancy.applicant_count ??
                    vacancy.applications ??
                    0
                ),

            status:
                normalizeStatus(
                    vacancy.status
                ),

            created_at:
                vacancy.created_at || "",

            published_at:
                vacancy.published_at || "",

            department:
                vacancy.department || "",

            experience:
                vacancy.experience || "",

            responsibilities:
                vacancy.responsibilities || "",

            requirements:
                vacancy.requirements || "",

            required_skills:
                vacancy.required_skills || ""
        };
    }


    // ========================================================
    // STATUS NORMALIZATION
    // ========================================================

    function normalizeStatus(status) {

        const value =
            String(
                status || "draft"
            )
            .trim()
            .toLowerCase();


        if (
            value === "active" ||
            value === "published"
        ) {

            return "published";
        }


        if (
            value === "draft" ||
            value === "processing" ||
            value === "closed"
        ) {

            return value;
        }


        return "draft";
    }


    // ========================================================
    // RENDER VACANCIES
    // ========================================================

    function renderVacancies() {

        let filtered =
            [...vacancies];


        // ====================================================
        // SEARCH (job title only, matches from the start of
        // the title or the start of any word in the title)
        // ====================================================

        const search =
            searchInput
                ? searchInput.value
                    .trim()
                    .toLowerCase()
                : "";


        if (search) {

            // Escape special regex characters typed by the user.
            const escapedSearch =
                search.replace(
                    /[.*+?^${}()|[\]\\]/g,
                    "\\$&"
                );

            const titleMatcher =
                new RegExp(
                    `(^|[\\s\\-/(,])${escapedSearch}`
                );

            filtered =
                filtered.filter(
                    vacancy =>
                        titleMatcher.test(
                            String(
                                vacancy.job_title || ""
                            ).toLowerCase()
                        )
                );
        }


        // ====================================================
        // STATUS FILTER
        // ====================================================

        const selectedStatus =
            statusFilter
                ? statusFilter.value
                    .toLowerCase()
                : "all";


        if (
            selectedStatus &&
            selectedStatus !== "all"
        ) {

            const normalizedFilter =
                selectedStatus === "active"
                    ? "published"
                    : selectedStatus;


            filtered =
                filtered.filter(
                    vacancy =>
                        vacancy.status ===
                        normalizedFilter
                );
        }


        // ====================================================
        // SORT
        // ====================================================

        const sortValue =
            sortFilter
                ? sortFilter.value
                : "newest";


        filtered.sort((a, b) => {

            switch (sortValue) {

                case "oldest":

                    return (
                        dateValue(
                            a.created_at
                        ) -
                        dateValue(
                            b.created_at
                        )
                    );


                case "applicants-high":

                    return (
                        Number(
                            b.applicant_count || 0
                        ) -
                        Number(
                            a.applicant_count || 0
                        )
                    );


                case "applicants-low":

                    return (
                        Number(
                            a.applicant_count || 0
                        ) -
                        Number(
                            b.applicant_count || 0
                        )
                    );


                case "title-az":

                    return String(
                        a.job_title || ""
                    )
                    .localeCompare(
                        String(
                            b.job_title || ""
                        )
                    );


                case "title-za":

                    return String(
                        b.job_title || ""
                    )
                    .localeCompare(
                        String(
                            a.job_title || ""
                        )
                    );


                case "ending-soon":

                    return (
                        dateValue(
                            a.application_end_date
                        ) -
                        dateValue(
                            b.application_end_date
                        )
                    );


                case "newest":

                default:

                    return (
                        dateValue(
                            b.created_at
                        ) -
                        dateValue(
                            a.created_at
                        )
                    );
            }
        });


        // ====================================================
        // COUNT
        // ====================================================

        if (vacancyCount) {

            vacancyCount.textContent =
                `${filtered.length} ${
                    filtered.length === 1
                        ? "vacancy"
                        : "vacancies"
                }`;
        }


        // ====================================================
        // EMPTY STATE
        // ====================================================

        if (!filtered.length) {

            vacanciesList.innerHTML =
                "";


            if (emptyState) {

                emptyState.style.display =
                    "flex";
            }


            return;
        }


        if (emptyState) {

            emptyState.style.display =
                "none";
        }


        // ====================================================
        // CARDS
        // ====================================================

        vacanciesList.innerHTML =
            filtered
                .map(createVacancyCard)
                .join("");
    }


    // ========================================================
    // CREATE VACANCY CARD
    // ========================================================

    function createVacancyCard(vacancy) {

        const description =
            vacancy.job_description ||
            "No job description provided.";


        const shortDescription =
            description.length > 220
                ? description.substring(
                    0,
                    220
                ) + "..."
                : description;



        const status = String(
            vacancy.status || "draft"
        ).trim().toLowerCase();

        const statusClassMap = {
            published: "active",
            active: "active",
            draft: "draft",
            closed: "closed",
            processing: "processing"
        };

        const statusLabelMap = {
            published: "Active",
            active: "Active",
            draft: "Draft",
            closed: "Closed",
            processing: "Processing"
        };

        const statusClass =
            statusClassMap[status] || "draft";

        const statusLabel =
            statusLabelMap[status] || "Draft";


        const applicants =
            Number(
                vacancy.applicant_count || 0
            );


        const employment =
            vacancy.employment_type ||
            "Not specified";


        const location =
            vacancy.location ||
            "Not specified";


        const workMode =
            vacancy.work_mode ||
            "Not specified";


        const salary =
            vacancy.salary ||
            "Not specified";


        const openingDate =
            formatDate(
                vacancy.opening_date
            );


        const endDate =
            formatDate(
                vacancy.application_end_date
            );


        const createdDate =
            formatDate(
                vacancy.created_at
            );


        return `

            <article
                class="vacancy-card"
                data-vacancy-id="${vacancy.id}"
            >

                <div class="vacancy-main">


                    <div class="vacancy-card-header">

                        <div class="vacancy-title-area">

                            <h3 class="vacancy-title">

                                ${escapeHTML(
                                    vacancy.job_title ||
                                    "Untitled Vacancy"
                                )}

                            </h3>


                            <div class="vacancy-meta">

                                <span>
                                    ${escapeHTML(
                                        location
                                    )}
                                </span>

                                <span class="meta-separator">
                                    •
                                </span>

                                <span>
                                    ${escapeHTML(
                                        employment
                                    )}
                                </span>

                                <span class="meta-separator">
                                    •
                                </span>

                                <span>
                                    ${escapeHTML(
                                        workMode
                                    )}
                                </span>

                            </div>

                        </div>


                        <div
                            class="card-actions"
                            data-card-id="${vacancy.id}"
                        >

                            <span
                                class="status-badge status-${statusClass}"
                            >

                                <span class="status-dot"></span>

                                ${statusLabel}

                            </span>


                            <button
                                class="more-button"
                                type="button"
                                onclick="toggleMenu(${vacancy.id})"
                                aria-label="Vacancy options"
                            >
                                ⋮
                            </button>


                            <div
                                class="action-menu"
                                id="menu-${vacancy.id}"
                                style="display: none;"
                            >

                                ${menuItems(vacancy)}

                            </div>

                        </div>

                    </div>


                    <p
                        class="vacancy-description"
                        id="description-${vacancy.id}"
                    >
                        ${escapeHTML(
                            shortDescription
                        )}
                    </p>


                    <div class="vacancy-bottom">

                        <div class="vacancy-info">

                            <div class="info-item">

                                <span class="info-label">
                                    Posted
                                </span>

                                <span class="info-value">
                                    ${escapeHTML(
                                        createdDate
                                    )}
                                </span>

                            </div>


                            <div class="info-item">

                                <span class="info-label">
                                    Ends
                                </span>

                                <span class="info-value">
                                    ${escapeHTML(
                                        endDate
                                    )}
                                </span>

                            </div>


                            <div class="info-item">

                                <span class="info-label">
                                    Salary
                                </span>

                                <span class="info-value">
                                    ${escapeHTML(
                                        salary
                                    )}
                                </span>

                            </div>

                        </div>


                        <button
                            class="applicants-link"
                            type="button"
                            onclick="viewApplicants(${vacancy.id})"
                        >

                            ${applicants}

                            Applicant${
                                applicants === 1
                                    ? ""
                                    : "s"
                            }

                            →

                        </button>

                    </div>


                    <!-- =================================================
                         MORE DETAILS
                    ================================================== -->

                    <div
                        style="margin-top: 14px;"
                    >

                        <span
                            class="details-toggle"
                            role="button"
                            tabindex="0"
                            onclick="toggleDetails(${vacancy.id})"
                            onkeydown="
                                if (
                                    event.key === 'Enter' ||
                                    event.key === ' '
                                ) {
                                    event.preventDefault();
                                    toggleDetails(${vacancy.id});
                                }
                            "
                        >

                            <span
                                id="details-label-${vacancy.id}"
                            >
                                More details
                            </span>


                            <span
                                class="details-arrow"
                                id="arrow-${vacancy.id}"
                            ></span>

                        </span>

                    </div>


                    <!-- =================================================
                         DETAILS
                    ================================================== -->

                    <div
                        class="vacancy-details"
                        id="details-${vacancy.id}"
                    >

                        <div class="details-divider"></div>


                        <div class="details-grid">


                            <div class="detail-block">

                                <h4>
                                    Location
                                </h4>

                                <p>
                                    ${escapeHTML(
                                        location
                                    )}
                                </p>

                            </div>


                            <div class="detail-block">

                                <h4>
                                    Salary
                                </h4>

                                <p>
                                    ${escapeHTML(
                                        salary
                                    )}
                                </p>

                            </div>


                            <div class="detail-block">

                                <h4>
                                    Employment Type
                                </h4>

                                <p>
                                    ${escapeHTML(
                                        employment
                                    )}
                                </p>

                            </div>


                            <div class="detail-block">

                                <h4>
                                    Work Mode
                                </h4>

                                <p>
                                    ${escapeHTML(
                                        workMode
                                    )}
                                </p>

                            </div>


                            <div class="detail-block">

                                <h4>
                                    Opening Date
                                </h4>

                                <p>
                                    ${escapeHTML(
                                        openingDate
                                    )}
                                </p>

                            </div>


                            <div class="detail-block">

                                <h4>
                                    Application End Date
                                </h4>

                                <p>
                                    ${escapeHTML(
                                        endDate
                                    )}
                                </p>

                            </div>


                            <div class="detail-block">

                                <h4>
                                    Portfolio
                                </h4>

                                <p>

                                    ${
                                        vacancy.portfolio_required
                                            ? "Required"
                                            : "Not required"
                                    }

                                </p>

                            </div>


                            <div class="detail-block">

                                <h4>
                                    Applicants
                                </h4>

                                <p>
                                    ${applicants}
                                </p>

                            </div>


                            ${
                                vacancy.experience
                                    ? `

                                        <div class="detail-block">

                                            <h4>
                                                Experience
                                            </h4>

                                            <p>
                                                ${escapeHTML(
                                                    vacancy.experience
                                                )}
                                            </p>

                                        </div>

                                    `
                                    : ""
                            }


                            ${
                                vacancy.department
                                    ? `

                                        <div class="detail-block">

                                            <h4>
                                                Department
                                            </h4>

                                            <p>
                                                ${escapeHTML(
                                                    vacancy.department
                                                )}
                                            </p>

                                        </div>

                                    `
                                    : ""
                            }

                        </div>

                    </div>

                </div>

            </article>

        `;
    }


    // ========================================================
    // MENU ITEMS
    // ========================================================

    function menuItems(vacancy) {

        const status =
            vacancy.status ||
            "draft";


        let statusAction = "";


        if (status === "published") {

            statusAction = `

                <button
                    type="button"
                    onclick="closeVacancy(${vacancy.id})"
                >
                    Close Vacancy
                </button>

            `;

        } else if (status === "draft") {

            statusAction = `

                <button
                    type="button"
                    onclick="publishVacancy(${vacancy.id})"
                >
                    Publish Vacancy
                </button>

            `;

        } else if (status === "closed") {

            statusAction = `

                <button
                    type="button"
                    onclick="reopenVacancy(${vacancy.id})"
                >
                    Reopen Vacancy
                </button>

            `;
        }


        return `

            <button
                type="button"
                onclick="editVacancy(${vacancy.id})"
            >
                Edit Vacancy
            </button>


            <button
                type="button"
                onclick="viewApplicants(${vacancy.id})"
            >
                View Applicants
            </button>


            ${statusAction}


            <button
                type="button"
                onclick="duplicateVacancy(${vacancy.id})"
            >
                Duplicate Vacancy
            </button>


            <button
                type="button"
                class="danger"
                onclick="deleteVacancy(${vacancy.id})"
            >
                Delete Vacancy
            </button>

        `;
    }


    // ========================================================
    // MENU
    // ========================================================


    window.toggleMenu = function (id) {
        const menu = document.getElementById(`menu-${id}`);
        const button = document.querySelector(
            `.card-actions[data-card-id="${id}"] .more-button`
        );

        if (!menu || !button) return;

        const isOpen = menu.style.display === "block";

        // Close other open menus first.
        document.querySelectorAll(".action-menu").forEach(otherMenu => {
            otherMenu.style.display = "none";
            otherMenu.style.top = "";
            otherMenu.style.bottom = "";
        });

        if (isOpen) return;

        const rect = button.getBoundingClientRect();
        const estimatedMenuHeight = Math.min(menu.scrollHeight || 260, 360);
        const spaceBelow = window.innerHeight - rect.bottom;
        const spaceAbove = rect.top;

        menu.style.top = "";
        menu.style.bottom = "";

        // Keep the dropdown visible near the bottom of the screen.
        if (
            spaceBelow < estimatedMenuHeight + 16 &&
            spaceAbove > spaceBelow
        ) {
            menu.style.top = "auto";
            menu.style.bottom = "calc(100% + 8px)";
        }

        menu.style.display = "block";
    };



    // ========================================================
    // DETAILS
    // ========================================================

    window.toggleDetails =
        function(id) {

            const card =
                document.querySelector(
                    `.vacancy-card[data-vacancy-id="${id}"]`
                );


            const details =
                document.getElementById(
                    `details-${id}`
                );


            const description =
                document.getElementById(
                    `description-${id}`
                );


            const label =
                document.getElementById(
                    `details-label-${id}`
                );


            if (
                !card ||
                !details ||
                !description
            ) {
                return;
            }


            const isExpanded =
                card.classList.contains(
                    "expanded"
                );


            if (!isExpanded) {

                const vacancy =
                    vacancies.find(
                        item =>
                            String(item.id) ===
                            String(id)
                    );


                if (vacancy) {

                    description.textContent =
                        vacancy.job_description ||
                        "No job description provided.";
                }


                description.style.display =
                    "block";

                description.style.webkitLineClamp =
                    "unset";

                description.style.webkitBoxOrient =
                    "initial";

                description.style.overflow =
                    "visible";

                description.style.whiteSpace =
                    "pre-wrap";

                description.style.overflowWrap =
                    "anywhere";

                description.style.wordBreak =
                    "break-word";


                card.classList.add(
                    "expanded"
                );


                if (label) {

                    label.textContent =
                        "Less details";
                }


            } else {

                const vacancy =
                    vacancies.find(
                        item =>
                            String(item.id) ===
                            String(id)
                    );


                if (vacancy) {

                    const fullDescription =
                        vacancy.job_description ||
                        "No job description provided.";


                    const shortDescription =
                        fullDescription.length > 220
                            ? fullDescription.substring(
                                0,
                                220
                            ) + "..."
                            : fullDescription;


                    description.textContent =
                        shortDescription;
                }


                description.style.display =
                    "";

                description.style.webkitLineClamp =
                    "";

                description.style.webkitBoxOrient =
                    "";

                description.style.overflow =
                    "";

                description.style.whiteSpace =
                    "";

                description.style.overflowWrap =
                    "";

                description.style.wordBreak =
                    "";


                card.classList.remove(
                    "expanded"
                );


                if (label) {

                    label.textContent =
                        "More details";
                }
            }
        };


    // ========================================================
    // CLOSE
    // ========================================================

    window.closeVacancy =
        async function(id) {

            if (
                !confirm(
                    "Close this vacancy?"
                )
            ) {
                return;
            }


            await updateStatus(
                id,
                "closed"
            );
        };


    // ========================================================
    // PUBLISH
    // ========================================================

    window.publishVacancy =
        async function(id) {

            if (
                !confirm(
                    "Publish this vacancy?"
                )
            ) {
                return;
            }


            await updateStatus(
                id,
                "published"
            );
        };


    // ========================================================
    // REOPEN
    // ========================================================

    window.reopenVacancy =
        async function(id) {

            if (
                !confirm(
                    "Reopen this vacancy?"
                )
            ) {
                return;
            }


            await updateStatus(
                id,
                "published"
            );
        };


    // ========================================================
    // UPDATE STATUS
    // ========================================================

    async function updateStatus(
        id,
        status
    ) {

        try {

            await apiRequest(
                `/api/vacancies/${id}/status`,
                {
                    method: "PATCH",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            status:
                                status
                        })
                }
            );


            await loadVacancies();


        } catch (error) {

            console.error(
                "Status update error:",
                error
            );


            alert(
                error.message ||
                "Status update failed."
            );
        }
    }


    // ========================================================
    // EDIT
    // ========================================================

    window.editVacancy =
        function(id) {

            window.location.href =
                `/create-vacancy?edit=${encodeURIComponent(id)}`;
        };


    // ========================================================
    // VIEW APPLICANTS
    // ========================================================

    window.viewApplicants =
        function(id) {

            window.location.href =
                `/applicants?vacancy_id=${encodeURIComponent(id)}`;
        };


    // ========================================================
    // DUPLICATE
    // ========================================================

    window.duplicateVacancy =
        async function(id) {

            try {

                const data =
                    await apiRequest(
                        `/api/vacancies/${id}`,
                        {
                            method: "GET"
                        }
                    );


                const original =
                    data.vacancy;


                if (!original) {

                    throw new Error(
                        "Vacancy was not found."
                    );
                }


                const duplicate = {

                    job_title:
                        `${
                            original.job_title ||
                            "Vacancy"
                        } - Copy`,


                    job_description:
                        original.job_description ??
                        original.description ??
                        "",


                    location:
                        original.location ||
                        "",


                    salary:
                        original.salary ||
                        "",


                    employment_type:
                        original.employment_type ||
                        "",


                    work_mode:
                        original.work_mode ||
                        "",


                    opening_date:
                        original.opening_date ||
                        "",


                    application_end_date:
                        original.application_end_date ??
                        original.closing_date ??
                        "",


                    portfolio_required:
                        Boolean(
                            original.portfolio_required
                        ),


                    department:
                        original.department ||
                        "",


                    experience:
                        original.experience ||
                        "",


                    responsibilities:
                        original.responsibilities ||
                        "",


                    requirements:
                        original.requirements ||
                        "",


                    required_skills:
                        original.required_skills ||
                        "",


                    status:
                        "draft"
                };


                await apiRequest(
                    "/api/vacancies",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify(
                                duplicate
                            )
                    }
                );


                await loadVacancies();


            } catch (error) {

                console.error(
                    "Duplicate vacancy error:",
                    error
                );


                alert(
                    error.message ||
                    "Unable to duplicate vacancy."
                );
            }
        };


    // ========================================================
    // DELETE
    // ========================================================

    window.deleteVacancy =
        async function(id) {

            if (
                !confirm(
                    "Delete this vacancy permanently?"
                )
            ) {
                return;
            }


            try {

                await apiRequest(
                    `/api/vacancies/${id}`,
                    {
                        method: "DELETE"
                    }
                );


                await loadVacancies();


            } catch (error) {

                console.error(
                    "Delete vacancy error:",
                    error
                );


                alert(
                    error.message ||
                    "Unable to delete vacancy."
                );
            }
        };


    // ========================================================
    // DATE VALUE
    // ========================================================

    function dateValue(value) {

        if (!value) {
            return 0;
        }


        const normalized =
            String(value)
                .replace(
                    " ",
                    "T"
                );


        const time =
            new Date(
                normalized
            ).getTime();


        return Number.isNaN(time)
            ? 0
            : time;
    }


    // ========================================================
    // FORMAT DATE
    // ========================================================

    function formatDate(value) {

        if (!value) {
            return "Not specified";
        }


        const normalized =
            String(value)
                .replace(
                    " ",
                    "T"
                );


        const date =
            new Date(
                normalized
            );


        if (
            Number.isNaN(
                date.getTime()
            )
        ) {

            return String(value);
        }


        return date.toLocaleDateString(
            "en-US",
            {
                year: "numeric",
                month: "short",
                day: "numeric"
            }
        );
    }


    // ========================================================
    // ESCAPE HTML
    // ========================================================

    function escapeHTML(value) {

        return String(
            value ?? ""
        )
        .replace(
            /&/g,
            "&amp;"
        )
        .replace(
            /</g,
            "&lt;"
        )
        .replace(
            />/g,
            "&gt;"
        )
        .replace(
            /"/g,
            "&quot;"
        )
        .replace(
            /'/g,
            "&#039;"
        );
    }


    // ========================================================
    // SEARCH BUTTON
    // ========================================================

    if (searchBtn) {

        searchBtn.addEventListener(
            "click",
            function(event) {

                event.preventDefault();

                renderVacancies();
            }
        );
    }


    // ========================================================
    // LIVE SEARCH
    // ========================================================

    if (searchInput) {

        searchInput.addEventListener(
            "input",
            function() {

                renderVacancies();
            }
        );


        searchInput.addEventListener(
            "keydown",
            function(event) {

                if (
                    event.key === "Enter"
                ) {

                    event.preventDefault();

                    renderVacancies();
                }
            }
        );
    }


    // ========================================================
    // STATUS FILTER
    // ========================================================

    if (statusFilter) {

        statusFilter.addEventListener(
            "change",
            renderVacancies
        );
    }


    // ========================================================
    // SORT
    // ========================================================

    if (sortFilter) {

        sortFilter.addEventListener(
            "change",
            renderVacancies
        );
    }


    // ========================================================
    // CLOSE MENUS WHEN CLICKING OUTSIDE
    // ========================================================

    document.addEventListener(
        "click",
        function(event) {

            if (
                !event.target.closest(
                    ".card-actions"
                )
            ) {

                document
                    .querySelectorAll(
                        ".action-menu"
                    )
                    .forEach(
                        menu => {

                            menu.style.display =
                                "none";
                        }
                    );
            }
        }
    );


    // ========================================================
    // INITIAL LOAD
    // ========================================================

    loadVacancies();


    // ========================================================
    // AUTO REFRESH
    // ========================================================

    const REFRESH_INTERVAL_MS = 5000;

    setInterval(function () {

        if (!document.hidden) {

            loadVacancies(true);
        }

    }, REFRESH_INTERVAL_MS);


    // Refresh straight away when the user returns to the tab.
    document.addEventListener(
        "visibilitychange",
        function () {

            if (!document.hidden) {

                loadVacancies(true);
            }
        }
    );

}


);document.addEventListener("DOMContentLoaded", function () {
    const currentPath = window.location.pathname.replace(/\/+$/, "") || "/";

    document.querySelectorAll(".sidebar .nav-item").forEach(function (item) {
        const href = item.getAttribute("href");

        if (!href || href === "/logout") {
            return;
        }

        const linkPath = new URL(href, window.location.origin)
            .pathname
            .replace(/\/+$/, "") || "/";

        item.classList.toggle("active", linkPath === currentPath);
    });
});
// ============================================================
// PUBLIC APPLICATION LINK
// ============================================================

const publicJobsUrlElement =
    document.getElementById("publicJobsUrl");

const copyPublicJobsLinkBtn =
    document.getElementById("copyPublicJobsLinkBtn");


if (publicJobsUrlElement && copyPublicJobsLinkBtn) {

    copyPublicJobsLinkBtn.addEventListener(
        "click",
        async function () {

            const publicJobsUrl =
                publicJobsUrlElement.textContent.trim();

            if (!publicJobsUrl) {
                return;
            }

            try {

                await navigator.clipboard.writeText(
                    publicJobsUrl
                );

            } catch (error) {

                const textarea =
                    document.createElement("textarea");

                textarea.value =
                    publicJobsUrl;

                textarea.style.position =
                    "fixed";

                textarea.style.opacity =
                    "0";

                document.body.appendChild(
                    textarea
                );

                textarea.select();

                document.execCommand(
                    "copy"
                );

                textarea.remove();
            }

            const originalText =
                copyPublicJobsLinkBtn.textContent;

            copyPublicJobsLinkBtn.textContent =
                "Copied";

            copyPublicJobsLinkBtn.classList.add(
                "copied"
            );

            setTimeout(function () {

                copyPublicJobsLinkBtn.textContent =
                    originalText;

                copyPublicJobsLinkBtn.classList.remove(
                    "copied"
                );

            }, 1500);

        }
    );

}