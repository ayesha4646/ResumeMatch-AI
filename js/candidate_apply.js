document.addEventListener("DOMContentLoaded", function () {

    // ========================================
    // ELEMENTS
    // ========================================

    const applicationForm =
        document.getElementById("applicationForm");

    const applicationCard =
        document.getElementById("applicationCard");

    const successCard =
        document.getElementById("successCard");

    const jobTitle =
        document.getElementById("jobTitle");


    const successJobTitle =
        document.getElementById("successJobTitle");

    const fullNameInput =
        document.getElementById("fullName");

    const emailInput =
        document.getElementById("email");

    const phoneInput =
        document.getElementById("phone");

    const resumeInput =
        document.getElementById("resume");

    const uploadBox =
        document.getElementById("uploadBox");

    const uploadEmpty =
        document.getElementById("uploadEmpty");

    const selectedFile =
        document.getElementById("selectedFile");

    const fileName =
        document.getElementById("fileName");

    const fileSize =
        document.getElementById("fileSize");

    const browseButton =
        document.getElementById("browseButton");

    const removeFile =
        document.getElementById("removeFile");

    const formError =
        document.getElementById("formError");

    const submitButton =
        document.getElementById("submitButton");

    const submitButtonText =
        document.getElementById("submitButtonText");

    const continueInterview =
        document.getElementById("continueInterview");

    const jobLocation =
        document.getElementById("jobLocation");

    const jobEmployment =
        document.getElementById("jobEmployment");

    const jobWorkMode =
        document.getElementById("jobWorkMode");


    // ========================================
    // GET VACANCY TOKEN
    // ========================================

    const pathParts =
        window.location.pathname
            .split("/")
            .filter(Boolean);

    const careersIndex =
        pathParts.indexOf("careers");

    const vacancyToken =
        careersIndex !== -1
            ? pathParts[careersIndex + 1]
            : null;


    // ========================================
    // HELPERS
    // ========================================

    function showError(message) {

        formError.textContent = message;
        formError.hidden = false;
    }


    function clearError() {

        formError.textContent = "";
        formError.hidden = true;
    }


    function formatFileSize(bytes) {

        if (bytes < 1024 * 1024) {
            return (bytes / 1024).toFixed(1) + " KB";
        }

        return (bytes / (1024 * 1024)).toFixed(2) + " MB";
    }


    function setMeta(element, icon, text) {

        element.innerHTML = `
            <span class="meta-icon">${icon}</span>
            <span>${text || "Not specified"}</span>
        `;
    }


    // ========================================
    // LOAD VACANCY
    // ========================================

    async function loadVacancy() {

 if (!vacancyToken) {

    jobTitle.textContent =
        "Position unavailable";

    return;
}

        try {

            const response = await fetch(
                `/api/public/vacancies/${encodeURIComponent(vacancyToken)}`
            );

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(
                    data.error || "Unable to load vacancy."
                );
            }

            const vacancy = data.vacancy || data;

            jobTitle.textContent =
                vacancy.job_title || "Open Position";

            successJobTitle.textContent =
                vacancy.job_title || "this position";

          

            setMeta(
                jobLocation,
                "⌖",
                vacancy.location
            );

            setMeta(
                jobEmployment,
                "◈",
                vacancy.employment_type
            );

            setMeta(
                jobWorkMode,
                "◉",
                vacancy.work_mode
            );

        } catch (error) {

            console.error(error);

            jobTitle.textContent =
                "Position unavailable";

          
        }
    }


    // ========================================
    // FILE PICKER
    // ========================================

    browseButton.addEventListener("click", function () {
        resumeInput.click();
    });


    uploadBox.addEventListener("click", function (event) {

        if (
            event.target === uploadBox ||
            event.target.closest(".upload-empty")
        ) {
            resumeInput.click();
        }
    });


    // ========================================
    // FILE VALIDATION
    // ========================================

    function handleFile(file) {

        clearError();

        if (!file) {
            return;
        }

        const maxSize =
            10 * 1024 * 1024;

        const extension =
            file.name
                .split(".")
                .pop()
                .toLowerCase();

        if (
            extension !== "pdf" &&
            file.type !== "application/pdf"
        ) {

            resumeInput.value = "";

            showError(
                "Please upload your resume as a PDF file."
            );

            return;
        }

        if (file.size > maxSize) {

            resumeInput.value = "";

            showError(
                "Resume must be 10 MB or smaller."
            );

            return;
        }


        fileName.textContent =
            file.name;

        fileSize.textContent =
            formatFileSize(file.size);

        uploadEmpty.hidden = true;
        selectedFile.hidden = false;

        uploadBox.classList.add("has-file");
    }


    resumeInput.addEventListener(
        "change",
        function () {

            const file =
                resumeInput.files[0];

            handleFile(file);
        }
    );


    // ========================================
    // REMOVE FILE
    // ========================================

    removeFile.addEventListener(
        "click",
        function (event) {

            event.stopPropagation();

            resumeInput.value = "";

            selectedFile.hidden = true;
            uploadEmpty.hidden = false;

            uploadBox.classList.remove("has-file");

            clearError();
        }
    );


    // ========================================
    // DRAG & DROP
    // ========================================

    uploadBox.addEventListener(
        "dragover",
        function (event) {

            event.preventDefault();

            uploadBox.classList.add("dragover");
        }
    );


    uploadBox.addEventListener(
        "dragleave",
        function () {

            uploadBox.classList.remove("dragover");
        }
    );


    uploadBox.addEventListener(
        "drop",
        function (event) {

            event.preventDefault();

            uploadBox.classList.remove("dragover");

            const file =
                event.dataTransfer.files[0];

            if (!file) {
                return;
            }

            const dataTransfer =
                new DataTransfer();

            dataTransfer.items.add(file);

            resumeInput.files =
                dataTransfer.files;

            handleFile(file);
        }
    );


    // ========================================
    // SUBMIT APPLICATION
    // ========================================

    applicationForm.addEventListener(
        "submit",
        async function (event) {

            event.preventDefault();

            clearError();

            const fullName =
                fullNameInput.value.trim();

            const email =
                emailInput.value.trim();

            const phone =
                phoneInput.value.trim();

            const file =
                resumeInput.files[0];


            if (!fullName) {

                showError(
                    "Please enter your full name."
                );

                fullNameInput.focus();

                return;
            }


            if (!email) {

                showError(
                    "Please enter your email address."
                );

                emailInput.focus();

                return;
            }


            if (!phone) {

                showError(
                    "Please enter your phone number."
                );

                phoneInput.focus();

                return;
            }


            if (!file) {

                showError(
                    "Please upload your resume."
                );

                return;
            }


            submitButton.disabled = true;

            submitButtonText.textContent =
                "Submitting application...";


            try {

                const formData =
                    new FormData(applicationForm);


                const response =
                    await fetch(
                        `/api/public/vacancies/${encodeURIComponent(vacancyToken)}/apply`,
                        {
                            method: "POST",
                            body: formData
                        }
                    );


                const data =
                    await response.json();


                if (!response.ok || !data.success) {

                    throw new Error(
                        data.error ||
                        "Unable to submit application."
                    );
                }


                // ========================================
                // SHOW SUCCESS
                // ========================================

                applicationCard.hidden = true;
                successCard.hidden = false;

                successJobTitle.textContent =
                    jobTitle.textContent ||
                    "this position";


                if (data.interview_url) {

                    continueInterview.dataset.url =
                        data.interview_url;

                } else {

                    continueInterview.disabled = true;

                }

                window.scrollTo({
                    top: 0,
                    behavior: "smooth"
                });


            } catch (error) {

                console.error(error);

                showError(
                    error.message ||
                    "Something went wrong. Please try again."
                );

                submitButton.disabled = false;

                submitButtonText.textContent =
                    "Submit Application";
            }
        }
    );


    // ========================================
    // CONTINUE TO AI INTERVIEW
    // ========================================

    continueInterview.addEventListener(
        "click",
        function () {

            const interviewUrl =
                continueInterview.dataset.url;

            if (!interviewUrl) {
                return;
            }

            window.location.href =
                interviewUrl;
        }
    );


    // ========================================
    // START
    // ========================================

    loadVacancy();

});