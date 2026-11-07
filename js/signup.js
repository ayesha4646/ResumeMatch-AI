document.addEventListener(
    "DOMContentLoaded",
    () => {


        // ============================================================
        // PASSWORD SHOW / HIDE
        // ============================================================

        const passwordInput =
            document.getElementById("password");

        const togglePassword =
            document.getElementById("togglePassword");


        if (
            passwordInput &&
            togglePassword
        ) {

            togglePassword.addEventListener(
                "click",
                () => {

                    const isHidden =
                        passwordInput.type === "password";

                    passwordInput.type =
                        isHidden
                            ? "text"
                            : "password";

                    togglePassword.setAttribute(
                        "aria-label",
                        isHidden
                            ? "Hide password"
                            : "Show password"
                    );
                }
            );
        }


        // ============================================================
        // CONFIRM PASSWORD SHOW / HIDE
        // ============================================================

        const confirmPasswordInput =
            document.getElementById(
                "confirmPassword"
            );

        const toggleConfirmPassword =
            document.getElementById(
                "toggleConfirmPassword"
            );


        if (
            confirmPasswordInput &&
            toggleConfirmPassword
        ) {

            toggleConfirmPassword.addEventListener(
                "click",
                () => {

                    const isHidden =
                        confirmPasswordInput.type ===
                        "password";

                    confirmPasswordInput.type =
                        isHidden
                            ? "text"
                            : "password";

                    toggleConfirmPassword.setAttribute(
                        "aria-label",
                        isHidden
                            ? "Hide password"
                            : "Show password"
                    );
                }
            );
        }


        // ============================================================
        // SIGNUP MESSAGE
        // ============================================================

        const signupMessage =
            document.getElementById(
                "signupMessage"
            );


        function showSignupMessage(message) {

            if (!signupMessage) {
                return;
            }

            signupMessage.textContent =
                message;

            signupMessage.style.display =
                "block";
        }


        function hideSignupMessage() {

            if (!signupMessage) {
                return;
            }

            signupMessage.textContent =
                "";

            signupMessage.style.display =
                "none";
        }


        // ============================================================
        // SIGNUP FORM
        // ============================================================

        const signupForm =
            document.getElementById(
                "signupForm"
            );


        if (signupForm) {

            signupForm.addEventListener(
                "submit",
                async (event) => {

                    event.preventDefault();

                    hideSignupMessage();


                    // ------------------------------------------------
                    // GET VALUES
                    // ------------------------------------------------

                    const name =
                        document
                            .getElementById("name")
                            .value
                            .trim();

                    const email =
                        document
                            .getElementById("email")
                            .value
                            .trim();

                    const password =
                        document
                            .getElementById("password")
                            .value;

                    const confirmPassword =
                        document
                            .getElementById(
                                "confirmPassword"
                            )
                            .value;


                    // ------------------------------------------------
                    // NAME
                    // ------------------------------------------------

                    if (!name) {

                        showSignupMessage(
                            "Please enter your full name."
                        );

                        return;
                    }


                    // ------------------------------------------------
                    // EMAIL
                    // ------------------------------------------------

                    if (!email) {

                        showSignupMessage(
                            "Please enter your email."
                        );

                        return;
                    }


                    const emailPattern =
                        /^[^\s@]+@[^\s@]+\.[^\s@]+$/;


                    if (
                        !emailPattern.test(email)
                    ) {

                        showSignupMessage(
                            "Please enter a valid email address."
                        );

                        return;
                    }


                    // ------------------------------------------------
                    // PASSWORD
                    // ------------------------------------------------

                    if (!password) {

                        showSignupMessage(
                            "Please enter a password."
                        );

                        return;
                    }


                    if (password.length < 8) {

                        showSignupMessage(
                            "Password must be at least 8 characters."
                        );

                        return;
                    }


                    // ------------------------------------------------
                    // CONFIRM PASSWORD
                    // ------------------------------------------------

                    if (!confirmPassword) {

                        showSignupMessage(
                            "Please confirm your password."
                        );

                        return;
                    }


                    if (
                        password !==
                        confirmPassword
                    ) {

                        showSignupMessage(
                            "Passwords do not match."
                        );

                        return;
                    }


                    // ------------------------------------------------
                    // BUTTON
                    // ------------------------------------------------

                    const signupButton =
                        signupForm.querySelector(
                            ".signup-button"
                        );

                    const originalText =
                        signupButton.innerHTML;


                    signupButton.disabled =
                        true;

                    signupButton.innerHTML = `
                        <span>
                            Creating account...
                        </span>
                    `;


                    // ------------------------------------------------
                    // SEND TO FLASK
                    // ------------------------------------------------

                    try {

                        const response =
                            await fetch(
                                "/signup",
                                {
                                    method: "POST",

                                    headers: {
                                        "Content-Type":
                                            "application/json"
                                    },

                                    body:
                                        JSON.stringify({
                                            name:
                                                name,

                                            email:
                                                email,

                                            password:
                                                password,

                                            confirm_password:
                                                confirmPassword
                                        })
                                }
                            );


                        const result =
                            await response.json();


                        // ------------------------------------------------
                        // SUCCESS
                        // ------------------------------------------------

                        if (
                            response.ok &&
                            result.success
                        ) {

                            window.location.href =
                                "/";

                            return;
                        }


                        // ------------------------------------------------
                        // SERVER ERROR
                        // ------------------------------------------------

                        showSignupMessage(
                            result.message ||
                            "Unable to create account."
                        );

                    }


                    // ------------------------------------------------
                    // CONNECTION ERROR
                    // ------------------------------------------------

                    catch (error) {

                        console.error(
                            "Signup error:",
                            error
                        );

                        showSignupMessage(
                            "Unable to connect to the server. Please try again."
                        );

                    }


                    // ------------------------------------------------
                    // ENABLE BUTTON
                    // ------------------------------------------------

                    finally {

                        signupButton.disabled =
                            false;

                        signupButton.innerHTML =
                            originalText;
                    }
                }
            );
        }


        // ============================================================
        // CLEAR SIGNUP ERROR WHEN TYPING
        // ============================================================

        const nameInput =
            document.getElementById("name");

        const emailInput =
            document.getElementById("email");


        if (nameInput) {

            nameInput.addEventListener(
                "input",
                hideSignupMessage
            );
        }


        if (emailInput) {

            emailInput.addEventListener(
                "input",
                hideSignupMessage
            );
        }


        if (passwordInput) {

            passwordInput.addEventListener(
                "input",
                hideSignupMessage
            );
        }


        if (confirmPasswordInput) {

            confirmPasswordInput.addEventListener(
                "input",
                hideSignupMessage
            );
        }


        // ============================================================
        // BACK TO LOGIN
        // ============================================================

        const backToLogin =
            document.getElementById(
                "backToLogin"
            );


        if (backToLogin) {

            backToLogin.addEventListener(
                "click",
                () => {

                    window.location.href =
                        "/";
                }
            );
        }


        // ============================================================
        // 92% MATCH SCORE ANIMATION
        // ============================================================

        const matchScore =
            document.getElementById(
                "matchScore"
            );

        const scoreProgress =
            document.querySelector(
                ".score-ring-progress"
            );


        if (
            matchScore &&
            scoreProgress
        ) {

            const radius = 42;

            const circumference =
                2 * Math.PI * radius;

            const targetScore = 92;


            scoreProgress.style.strokeDasharray =
                circumference;

            scoreProgress.style.strokeDashoffset =
                circumference;


            setTimeout(
                () => {

                    scoreProgress.style.transition =
                        "stroke-dashoffset 1.5s ease";

                    const finalOffset =
                        circumference -
                        (
                            targetScore / 100
                        ) * circumference;

                    scoreProgress.style.strokeDashoffset =
                        finalOffset;

                },
                300
            );


            let currentScore = 0;


            const numberAnimation =
                setInterval(
                    () => {

                        currentScore++;

                        matchScore.textContent =
                            `${currentScore}%`;


                        if (
                            currentScore >=
                            targetScore
                        ) {

                            clearInterval(
                                numberAnimation
                            );

                            matchScore.textContent =
                                `${targetScore}%`;
                        }

                    },
                    1500 / targetScore
                );
        }

    }
);