
document.addEventListener("DOMContentLoaded", async () => {
    const form = document.getElementById("interview-questions-form");
    if (!form) return;

    const vacancyId = form.dataset.vacancyId;
    const message = document.getElementById("question-message");
    const saveButton = document.getElementById("save-questions");
    const resetButton = document.getElementById("reset-questions");

    const fields = [1, 2, 3, 4, 5].map(
        number => document.getElementById(`question-${number}`)
    );

    const defaultQuestions = [
        "What are your strengths?",
        "What is one weakness you are currently working on?",
        "What is the best project you have worked on, and what did you learn from it?",
        "What interests you most about this position, and why do you think it is a good fit for you?",
        "What difficulties have you faced in your work or projects, and how did you handle them?"
    ];

    function showMessage(text, isError = false) {
        if (!message) return;
        message.textContent = text;
        message.style.color = isError ? "#fca5a5" : "#6ee7b7";
    }

    function displayQuestions(questions) {
        fields.forEach((field, index) => {
            if (field) {
                field.value = questions[index] || defaultQuestions[index];
            }
        });
    }

    async function loadQuestions() {
        try {
            const response = await fetch(
                `/api/vacancies/${vacancyId}/interview-settings`,
                { credentials: "same-origin" }
            );

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(
                    data.message || "Could not load question settings."
                );
            }

            const config = data.question_config;
            const savedQuestions = config?.custom_questions;

            if (
                Array.isArray(savedQuestions) &&
                savedQuestions.length === 5 &&
                savedQuestions.every(
                    question => typeof question === "string" && question.trim()
                )
            ) {
                displayQuestions(savedQuestions);
            } else {
                displayQuestions(defaultQuestions);
            }
        } catch (error) {
            console.error("LOAD QUESTIONS ERROR:", error);
            displayQuestions(defaultQuestions);
            showMessage(
                "Could not load saved questions. Your default questions are shown.",
                true
            );
        }
    }

    form.addEventListener("submit", async event => {
        event.preventDefault();

        const questions = fields.map(field => field?.value.trim() || "");

        if (questions.some(question => !question)) {
            showMessage("Please fill in all five questions.", true);
            return;
        }

        if (saveButton) saveButton.disabled = true;
        showMessage("Saving questions...");

        try {
            const response = await fetch(
                `/api/vacancies/${vacancyId}/interview-settings`,
                {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        selected_ids: [],
                        custom_questions: questions
                    })
                }
            );

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(
                    data.message || "Could not save questions."
                );
            }

            showMessage("Questions saved successfully.");
        } catch (error) {
            console.error("SAVE QUESTIONS ERROR:", error);
            showMessage(
                error.message || "Could not save questions.",
                true
            );
        } finally {
            if (saveButton) saveButton.disabled = false;
        }
    });

 
if (resetButton) {
    resetButton.type = "button";

    resetButton.addEventListener("click", event => {
        event.preventDefault();

        fields.forEach((field, index) => {
            if (field) {
                field.value = defaultQuestions[index];
            }
        });

        showMessage("Default questions restored. Click Save Questions to save them.");
        console.log("Restore Default clicked successfully.");
    });
} else {
    console.error("Restore Default button not found.");
}


    await loadQuestions();
});
