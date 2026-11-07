document.addEventListener("DOMContentLoaded", () => {
    const $ = id => document.getElementById(id);

    const welcomeScreen = $("welcomeScreen");
    const interviewScreen = $("interviewScreen");
    const waitingScreen = $("waitingScreen");
    const verificationIntro = $("verificationIntro");
    const completionScreen = $("completionScreen");

    const waitingOrbit = $("waitingOrbit");
    const waitingEyebrow = $("waitingEyebrow");
    const waitingTitle = $("waitingTitle");
    const waitingText = $("waitingText");
    const waitingRetryButton = $("waitingRetryButton");

    const startInterviewButton = $("startInterviewButton");
    const startError = $("startError");
    const nextButton = $("nextButton");
    const answerInput = $("answerInput");
    const answerError = $("answerError");
    const actionHint = $("actionHint");
    const characterCount = $("characterCount");
    const questionText = $("questionText");
    const questionType = $("questionType");
    const progressCount = $("progressCount");
    const progressFill = $("progressFill");

    const vacancyToken = document.body.dataset.vacancyToken?.trim();
    const applicationToken = document.body.dataset.applicationToken?.trim();

    let questions = [];
    let verificationQuestions = [];
    let answers = {};            // answers entered so far (saved or saving)
    let drafts = {};             // unsent text kept when navigating
    let currentQuestionIndex = 0;
    let verificationIndex = 0;
    let interviewStarted = false;
    let interviewCompleted = false;
    let interviewPhase = "standard";

    // Answers are saved one at a time, in order, in the background.
    const saveQueue = [];
    let queueRunning = false;
    let failedSave = null;
    const drainWaiters = [];

    if (
        !applicationToken ||
        !vacancyToken ||
        !startInterviewButton ||
        !nextButton ||
        !answerInput
    ) {
        console.error("Interview page is missing required tokens or elements.");
        if (startInterviewButton) startInterviewButton.disabled = true;
        alert("This interview link or page is incomplete. Please reopen the link provided after applying.");
        return;
    }

    const nextLabel = nextButton.querySelector("span");

    // ========================================================
    // API
    // ========================================================

    async function api(url, method = "GET", body = null) {
        const response = await fetch(url, {
            method,
            credentials: "same-origin",
            cache: "no-store",
            headers: { "Content-Type": "application/json" },
            ...(body !== null ? { body: JSON.stringify(body) } : {})
        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            const error = new Error(
                data.message || `Request failed (${response.status})`
            );
            error.status = response.status;
            throw error;
        }

        return data;
    }

    // ========================================================
    // SCREEN AND INPUT HELPERS
    // ========================================================

    function showScreen(screen) {
        [
            welcomeScreen,
            interviewScreen,
            waitingScreen,
            verificationIntro,
            completionScreen
        ].forEach(element => {
            if (!element) return;

            const shouldHide = element !== screen;

            element.hidden = shouldHide;
            element.classList.toggle("hidden", shouldHide);
        });
    }

    function showWaiting(title, text, eyebrow = "PLEASE WAIT") {
        waitingOrbit.classList.remove("is-error");
        waitingRetryButton.classList.add("hidden");
        waitingRetryButton.onclick = null;

        waitingEyebrow.textContent = eyebrow;
        waitingTitle.textContent = title;
        waitingText.textContent = text;

        showScreen(waitingScreen);
    }

    function showWaitingError(title, text, retry) {
        waitingOrbit.classList.add("is-error");

        waitingEyebrow.textContent = "SOMETHING WENT WRONG";
        waitingTitle.textContent = title;
        waitingText.textContent = text;

        waitingRetryButton.classList.remove("hidden");
        waitingRetryButton.onclick = retry;

        showScreen(waitingScreen);
    }

    function setNextLabel(text) {
        if (nextLabel) nextLabel.textContent = text;
    }

    function updateCharacterCount() {
        if (characterCount) {
            characterCount.textContent =
                `${answerInput.value.length} / 1500`;
        }
    }

    function updateNextButton() {
        nextButton.disabled = !answerInput.value.trim();
    }

    function updateSaveHint() {
        if (!actionHint) return;

        const saving = (queueRunning || saveQueue.length > 0) && !failedSave;

        actionHint.classList.toggle("is-saving", saving);
        actionHint.textContent = saving
            ? "Saving your answers…"
            : "Your answers are saved as you go.";
    }

    function getQuestionId(question) {
        return String(question?.id || "");
    }

    function findFirstUnansweredQuestion() {
        return questions.findIndex(
            question =>
                !String(answers[getQuestionId(question)] || "").trim()
        );
    }

    function findFirstUnansweredVerificationQuestion() {
        return verificationQuestions.findIndex(
            question =>
                !String(answers[getQuestionId(question)] || "").trim()
        );
    }

    function updateProgress(index, total) {
        if (progressCount) {
            progressCount.textContent = `${index + 1} / ${total}`;
        }

        if (progressFill) {
            progressFill.style.width =
                `${total ? ((index + 1) / total) * 100 : 0}%`;
        }
    }

    // ========================================================
    // DISPLAY QUESTIONS
    // ========================================================

    function showQuestion(index) {
        if (index < 0 || index >= questions.length) {
            void finalizeInterview();
            return;
        }

        currentQuestionIndex = index;
        interviewPhase = "standard";

        const question = questions[index];
        const questionId = getQuestionId(question);

        questionText.textContent =
            question.question ||
            question.text ||
            "Please provide the requested information.";

        questionType.textContent = "INTERVIEW QUESTION";
        answerInput.value = answers[questionId] || drafts[questionId] || "";
        answerError.textContent = "";

        setNextLabel(
            index === questions.length - 1 ? "Finish Interview" : "Next Question"
        );

        updateProgress(index, questions.length);
        updateCharacterCount();
        updateNextButton();
        answerInput.focus();
    }

    function showVerificationQuestion(index) {
        if (index < 0 || index >= verificationQuestions.length) {
            showFirstInterviewQuestion();
            return;
        }

        verificationIndex = index;
        interviewPhase = "verification";

        const question = verificationQuestions[index];
        const questionId = getQuestionId(question);

        questionText.textContent =
            question.question ||
            question.text ||
            "Please provide the requested information.";

        questionType.textContent =
            question.type === "education_verification"
                ? "EDUCATION VERIFICATION"
                : question.type === "experience_verification"
                    ? "EXPERIENCE VERIFICATION"
                    : "BACKGROUND VERIFICATION";

        answerInput.value = answers[questionId] || drafts[questionId] || "";
        answerError.textContent = "";

        setNextLabel(
            index === verificationQuestions.length - 1
                ? "Continue"
                : "Next Question"
        );

        updateProgress(index, verificationQuestions.length);
        updateCharacterCount();
        updateNextButton();
        answerInput.focus();
    }

    function showFirstInterviewQuestion() {
        const nextIndex = findFirstUnansweredQuestion();

        if (nextIndex < 0) {
            void finalizeInterview();
            return;
        }

        showScreen(interviewScreen);
        showQuestion(nextIndex);
    }

    // Keeps typed text if the candidate is taken back to an earlier question.
    function saveCurrentDraft() {
        if (interviewScreen.classList.contains("hidden")) return;

        const isVerification = interviewPhase === "verification";
        const list = isVerification ? verificationQuestions : questions;
        const index = isVerification ? verificationIndex : currentQuestionIndex;
        const question = list[index];

        if (question && answerInput.value.trim()) {
            drafts[getQuestionId(question)] = answerInput.value;
        }
    }

    // ========================================================
    // BACKGROUND SAVING (ONE ANSWER AT A TIME, IN ORDER)
    // ========================================================

    async function saveAnswer(question, answer) {
        const questionId = getQuestionId(question);

        if (!questionId) {
            throw new Error("This question has an invalid ID.");
        }

        return api(
            `/api/applications/${encodeURIComponent(applicationToken)}/interview/answer`,
            "POST",
            {
                question_id: questionId,
                question_type: question.type || "interview",
                question: question.question || question.text || "",
                answer
            }
        );
    }

    function flushWaiters() {
        if (queueRunning) return;
        if (saveQueue.length && !failedSave) return;

        const ok = !failedSave && saveQueue.length === 0;

        drainWaiters.splice(0).forEach(resolve => resolve(ok));
    }

    // Resolves true when everything is saved, false if a save is stuck.
    function waitForSaves() {
        return new Promise(resolve => {
            if (failedSave) {
                resolve(false);
                return;
            }

            if (!queueRunning && !saveQueue.length) {
                resolve(true);
                return;
            }

            drainWaiters.push(resolve);
        });
    }

    async function runQueue() {
        if (queueRunning || failedSave) return;

        queueRunning = true;
        updateSaveHint();

        while (saveQueue.length && !failedSave) {
            const item = saveQueue[0];

            try {
                await saveAnswer(item.question, item.answer);
                saveQueue.shift();

            } catch (error) {
                // Already stored on the server (for example a lost response).
                if (
                    error.status === 409 &&
                    /already (has a saved answer|complete)/i.test(error.message || "")
                ) {
                    saveQueue.shift();
                    continue;
                }

                console.error("Answer save error:", error);

                failedSave = {
                    item,
                    message:
                        error.message ||
                        "Your answer could not be saved. Please try again."
                };

                queueRunning = false;
                handleSaveFailure();
                return;
            }
        }

        queueRunning = false;
        updateSaveHint();
        flushWaiters();
    }

    // Takes the candidate back to the answer that could not be saved.
    function handleSaveFailure() {
        const { item, message } = failedSave;
        const failedId = getQuestionId(item.question);

        saveCurrentDraft();

        delete answers[failedId];
        drafts[failedId] = item.answer;

        const verificationPosition = verificationQuestions.findIndex(
            question => getQuestionId(question) === failedId
        );

        showScreen(interviewScreen);

        if (verificationPosition >= 0) {
            showVerificationQuestion(verificationPosition);
        } else {
            showQuestion(
                questions.findIndex(
                    question => getQuestionId(question) === failedId
                )
            );
        }

        answerError.textContent = message;
        updateSaveHint();
        flushWaiters();
    }

    // ========================================================
    // START OR RESTORE THE INTERVIEW
    // ========================================================

    async function startInterview() {
        if (interviewStarted) return;

        interviewStarted = true;
        startInterviewButton.disabled = true;
        startError.textContent = "";

        try {
            const data = await api(
                `/api/applications/${encodeURIComponent(applicationToken)}/interview/start`,
                "POST"
            );

            // All answered: make sure the interview has actually been submitted.
            if (data.interview_completed) {
                interviewPhase = "completed";
                await completeInterview();
                return;
            }

            questions = Array.isArray(data.questions) ? data.questions : [];

            verificationQuestions =
                Array.isArray(data.verification_questions)
                    ? data.verification_questions
                    : [];

            answers =
                data.answers && typeof data.answers === "object"
                    ? data.answers
                    : {};

            if (!questions.length) {
                throw new Error(
                    "No interview questions are available. Please contact HR."
                );
            }

            // Verification questions (when the role needs them) come first.
            if (data.phase === "verification" && verificationQuestions.length) {
                verificationIndex = findFirstUnansweredVerificationQuestion();

                if (verificationIndex >= 0) {
                    showScreen(interviewScreen);
                    showVerificationQuestion(verificationIndex);
                    return;
                }
            }

            showFirstInterviewQuestion();

        } catch (error) {
            console.error("Interview start error:", error);

            interviewStarted = false;
            startInterviewButton.disabled = false;

            startError.textContent =
                error.message ||
                "We could not start the interview. Please try again.";
        }
    }

    // ========================================================
    // NEXT QUESTION (moves on immediately; saving happens behind it)
    // ========================================================

    function handleNext() {
        const answer = answerInput.value.trim();

        if (!answer) return;

        const isVerification = interviewPhase === "verification";
        const list = isVerification ? verificationQuestions : questions;
        const index = isVerification ? verificationIndex : currentQuestionIndex;

        const question = list[index];
        const questionId = getQuestionId(question);

        if (!question || !questionId) {
            answerError.textContent =
                "The current question could not be found. Please reload the page.";
            return;
        }

        answers[questionId] = answer;
        delete drafts[questionId];
        answerError.textContent = "";

        if (failedSave && getQuestionId(failedSave.item.question) === questionId) {
            // Retry the answer that could not be saved (text may have been edited).
            failedSave.item.answer = answer;
            failedSave = null;
        } else {
            saveQueue.push({ question, answer });
        }

        void runQueue();

        if (isVerification) {
            const nextIndex = findFirstUnansweredVerificationQuestion();

            if (nextIndex < 0) {
                showFirstInterviewQuestion();
            } else {
                showVerificationQuestion(nextIndex);
            }
        } else {
            const nextIndex = findFirstUnansweredQuestion();

            if (nextIndex < 0) {
                void finalizeInterview();
            } else {
                showQuestion(nextIndex);
            }
        }
    }

    // ========================================================
    // FINISH: WAIT FOR ANY SAVES STILL RUNNING, THEN SUBMIT
    // ========================================================

    async function finalizeInterview() {
        if (saveQueue.length || queueRunning) {
            showWaiting(
                "Saving your last answers",
                "Just a moment. Please keep this page open."
            );
        }

        const allSaved = await waitForSaves();

        // If a save failed, the candidate was already taken back to it.
        if (!allSaved) return;

        await completeInterview();
    }

    async function completeInterview() {
        if (interviewCompleted) {
            showScreen(completionScreen);
            return;
        }

        showWaiting(
            "Submitting your interview",
            "This can take a moment. Please keep this page open.",
            "SUBMITTING"
        );

        try {
            await api(
                `/api/applications/${encodeURIComponent(applicationToken)}/interview/complete`,
                "POST"
            );

            interviewCompleted = true;
            interviewPhase = "completed";
            showScreen(completionScreen);

        } catch (error) {
            console.error("Interview completion error:", error);

            showWaitingError(
                "We couldn't submit your interview",
                error.message || "Your answers are saved. Please try again.",
                completeInterview
            );
        }
    }

    // ========================================================
    // BUTTONS AND INPUT EVENTS
    // ========================================================

    startInterviewButton.addEventListener("click", startInterview);

    nextButton.addEventListener("click", handleNext);

    answerInput.addEventListener("input", () => {
        answerError.textContent = "";
        updateCharacterCount();
        updateNextButton();
    });

    answerInput.addEventListener("keydown", event => {
        if (
            (event.ctrlKey || event.metaKey) &&
            event.key === "Enter" &&
            !nextButton.disabled
        ) {
            event.preventDefault();
            nextButton.click();
        }
    });

    // Warn before leaving while answers are still being saved.
    window.addEventListener("beforeunload", event => {
        if (saveQueue.length || queueRunning) {
            event.preventDefault();
            event.returnValue = "";
        }
    });

    updateCharacterCount();
    updateNextButton();
    updateSaveHint();
});