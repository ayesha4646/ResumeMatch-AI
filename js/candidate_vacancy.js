
// ============================================================
// RESUMEMATCH AI - CANDIDATE VACANCY PAGE
// Public HR vacancy listing
// ============================================================

document.addEventListener("DOMContentLoaded", function () {

    // ========================================================
    // ELEMENTS
    // ========================================================

    const vacanciesList =
        document.getElementById("vacanciesList");

    const emptyState =
        document.getElementById("emptyState");

    const sortFilter =
        document.getElementById("sortSelect");

    const vacancyCount =
        document.getElementById("vacancyCount");

    const hrToken =
        getHRTokenFromURL();


    // ========================================================
    // DATA
    // ========================================================

    let vacancies = [];


    // ========================================================
    // GET HR TOKEN
    // ========================================================

    function getHRTokenFromURL() {

        const pathParts =
            window.location.pathname
                .split("/")
                .filter(function (part) {
                    return part.trim() !== "";
                });


        if (
            pathParts.length >= 2 &&
            pathParts[0] === "jobs"
        ) {

            return pathParts[1];
        }


        return "";
    }


    // ========================================================
    // INVALID URL
    // ========================================================

    if (!hrToken) {

        showError(
            "Invalid candidate page."
        );

        return;
    }


    // ========================================================
    // API HELPER
    // ========================================================

    async function apiRequest(url, options = {}) {

        const response =
            await fetch(
                url,
                {
                    credentials: "same-origin",

                    ...options,

                    headers: {
                        "Accept":
                            "application/json",

                        ...(options.headers || {})
                    },

                    cache: "no-store"
                }
            );


        const contentType =
            response.headers.get(
                "content-type"
            ) || "";


        let data = null;
        let rawText = "";


        if (
            contentType.includes(
                "application/json"
            )
        ) {

            data =
                await response.json();

        } else {

            rawText =
                await response.text();

            try {

                data =
                    JSON.parse(
                        rawText
                    );

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
                        .replace(
                            /<[^>]*>/g,
                            " "
                        )
                        .replace(
                            /\s+/g,
                            " "
                        )
                        .trim();


                if (cleanText) {

                    message =
                        cleanText.substring(
                            0,
                            250
                        );
                }
            }


            throw new Error(
                message
            );
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

    async function loadVacancies() {

        try {

            vacanciesList.innerHTML = `
                <div class="vacancy-loading">
                    Loading vacancies...
                </div>
            `;


            const apiUrl =
                `/api/public/jobs/${encodeURIComponent(
                    hrToken
                )}`;


            const data =
                await apiRequest(
                    apiUrl,
                    {
                        method: "GET"
                    }
                );


            console.log(
                "[Candidate Page] Public vacancies:",
                data
            );


            if (
                Array.isArray(
                    data.vacancies
                )
            ) {

                vacancies =
                    data.vacancies;

            } else {

                throw new Error(
                    data.message ||
                    "Vacancies data was not returned correctly."
                );
            }


            vacancies =
                vacancies
                    .map(
                        normalizeVacancy
                    )
                    .filter(
                        function (vacancy) {

                            return (
                                vacancy.status ===
                                "published"
                            );
                        }
                    );


            renderVacancies();


        } catch (error) {

            console.error(
                "[Candidate Page] Loading error:",
                error
            );


            showError(
                error.message ||
                "Please refresh the page."
            );
        }
    }


    // ========================================================
    // NORMALIZE
    // ========================================================

    function normalizeVacancy(vacancy) {

        return {

            ...vacancy,

            id:
                vacancy.id,

            public_token:
                vacancy.public_token || "",

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
    // STATUS
    // ========================================================

    function normalizeStatus(status) {

        const value =
            String(
                status || "published"
            )
                .trim()
                .toLowerCase();


        if (
            value === "active" ||
            value === "published"
        ) {

            return "published";
        }


        return value;
    }


    // ========================================================
    // RENDER
    // ========================================================

    function renderVacancies() {

        let filtered =
            [...vacancies];


        const sortValue =
            sortFilter
                ? sortFilter.value
                : "newest";


        filtered.sort(
            function (a, b) {

                switch (sortValue) {

                    case "oldest":

                        return compareDates(
                            a.created_at,
                            b.created_at,
                            false
                        );


                    case "ending-soon":

                        return compareDates(
                            a.application_end_date,
                            b.application_end_date,
                            false
                        );


                    case "newest":

                    default:

                        return compareDates(
                            a.created_at,
                            b.created_at,
                            true
                        );
                }
            }
        );


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
        // EMPTY
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
                .map(
                    createVacancyCard
                )
                .join("");
    }


    // ========================================================
    // CREATE CARD
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


        const vacancyId =
            String(
                vacancy.id
            );


        const vacancyToken =
            vacancy.public_token ||
            "";


     const applyUrl =
    vacancyToken
        ? `/careers/${encodeURIComponent(
            vacancyToken
        )}/apply`
        : "#";


        return `
            <article
                class="vacancy-card"
                data-vacancy-id="${escapeHTML(
                    vacancyId
                )}"
            >

                <div class="vacancy-main">

                    <!-- =================================================
                         HEADER
                    ================================================== -->

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


                        <div class="card-actions">

                            <span
                                class="status-badge status-active"
                            >

                                <span class="status-dot"></span>

                                Active

                            </span>

                        </div>

                    </div>


                    <!-- =================================================
                         DESCRIPTION
                    ================================================== -->

                    <p
                        class="vacancy-description"
                        id="description-${escapeHTML(
                            vacancyId
                        )}"
                    >
                        ${escapeHTML(
                            shortDescription
                        )}
                    </p>


                    <!-- =================================================
                         BOTTOM INFO
                    ================================================== -->

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


                        <!-- COLLAPSED APPLY -->

                        <a
                            href="${applyUrl}"
                            class="apply-now-btn collapsed-apply"
                        >
                            Apply Now 
                        </a>

                    </div>


                    <!-- =================================================
                         MORE DETAILS
                    ================================================== -->

                    <div>

                        <span
                            class="details-toggle"
                            role="button"
                            tabindex="0"
                            onclick="toggleDetails('${escapeHTML(
                                vacancyId
                            )}')"
                            onkeydown="
                                if (
                                    event.key === 'Enter' ||
                                    event.key === ' '
                                ) {
                                    event.preventDefault();
                                    toggleDetails(
                                        '${escapeHTML(
                                            vacancyId
                                        )}'
                                    );
                                }
                            "
                        >

                            <span
                                id="details-label-${escapeHTML(
                                    vacancyId
                                )}"
                            >
                                More details
                            </span>

                            <span
                                class="details-arrow"
                            ></span>

                        </span>

                    </div>


                    <!-- =================================================
                         EXPANDED DETAILS
                    ================================================== -->

                    <div
                        class="vacancy-details"
                        id="details-${escapeHTML(
                            vacancyId
                        )}"
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


                            ${
                                vacancy.required_skills
                                    ? `
                                        <div class="detail-block detail-full">

                                            <h4>
                                                Required Skills
                                            </h4>

                                            <p>
                                                ${escapeHTML(
                                                    vacancy.required_skills
                                                )}
                                            </p>

                                        </div>
                                    `
                                    : ""
                            }


                            ${
                                vacancy.responsibilities
                                    ? `
                                        <div class="detail-block detail-full">

                                            <h4>
                                                Responsibilities
                                            </h4>

                                            <p>
                                                ${escapeHTML(
                                                    vacancy.responsibilities
                                                )}
                                            </p>

                                        </div>
                                    `
                                    : ""
                            }


                            ${
                                vacancy.requirements
                                    ? `
                                        <div class="detail-block detail-full">

                                            <h4>
                                                Requirements
                                            </h4>

                                            <p>
                                                ${escapeHTML(
                                                    vacancy.requirements
                                                )}
                                            </p>

                                        </div>
                                    `
                                    : ""
                            }

                        </div>


                        <!-- =============================================
                             EXPANDED APPLY BUTTON
                        ============================================== -->

                        <div class="expanded-apply">

                            <a
                                href="${applyUrl}"
                                class="apply-now-btn"
                            >
                                Apply Now 
                            </a>

                        </div>

                    </div>

                </div>

            </article>
        `;
    }


    // ========================================================
    // TOGGLE DETAILS
    // ========================================================

    window.toggleDetails =
        function (id) {

            const card =
                document.querySelector(
                    `.vacancy-card[data-vacancy-id="${id}"]`
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
                !description
            ) {
                return;
            }


            const vacancy =
                vacancies.find(
                    function (item) {

                        return (
                            String(item.id) ===
                            String(id)
                        );
                    }
                );


            if (!vacancy) {
                return;
            }


            const isExpanded =
                card.classList.contains(
                    "expanded"
                );


            if (!isExpanded) {

                description.textContent =
                    vacancy.job_description ||
                    "No job description provided.";


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
    // SORT
    // ========================================================

    if (sortFilter) {

        sortFilter.addEventListener(
            "change",
            renderVacancies
        );
    }


    // ========================================================
    // DATE COMPARISON
    // ========================================================

    function compareDates(
        valueA,
        valueB,
        descending
    ) {

        const a =
            dateValue(valueA);

        const b =
            dateValue(valueB);


        if (
            a === 0 &&
            b === 0
        ) {
            return 0;
        }

        if (a === 0) {
            return 1;
        }

        if (b === 0) {
            return -1;
        }


        return descending
            ? b - a
            : a - b;
    }


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

            return String(
                value
            );
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
    // ERROR
    // ========================================================

    function showError(message) {

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
                        message ||
                        "Please refresh the page."
                    )}
                </p>

            </div>

        `;


        if (emptyState) {

            emptyState.style.display =
                "none";
        }
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
    // INITIAL LOAD
    // ========================================================

    loadVacancies();

});

