/* =========================================================
   PASSWORD SHOW / HIDE
========================================================= */

const passwordInput =
    document.getElementById("password");

const togglePassword =
    document.getElementById("togglePassword");

const eyeIcon =
    document.getElementById("eyeIcon");

if (
    passwordInput &&
    togglePassword &&
    eyeIcon
) {

    togglePassword.addEventListener(
        "click",
        function () {

            const isPassword =
                passwordInput.type === "password";

            if (isPassword) {

                passwordInput.type = "text";

                togglePassword.setAttribute(
                    "aria-label",
                    "Hide password"
                );

                eyeIcon.innerHTML = `
                    <path d="M3 3l18 18" />
                    <path
                        d="M10.6 10.6a2 2 0 0 0 2.8 2.8"
                    />
                    <path
                        d="M9.9 5.2A10.6 10.6 0 0 1 12 5
                           c6.5 0 10 7 10 7
                           a17.6 17.6 0 0 1-3.2 4.1"
                    />
                    <path
                        d="M6.6 6.6
                           C3.7 8.5 2 12 2 12
                           s3.5 7 10 7
                           c1.2 0 2.3-.2 3.3-.6"
                    />
                `;

            } else {

                passwordInput.type = "password";

                togglePassword.setAttribute(
                    "aria-label",
                    "Show password"
                );

                eyeIcon.innerHTML = `
                    <path
                        d="M2 12s3.5-6 10-6
                           10 6 10 6
                           -3.5 6-10 6
                           S2 12 2 12Z"
                    />
                    <circle
                        cx="12"
                        cy="12"
                        r="2.5"
                    />
                `;
            }
        }
    );
}


/* =========================================================
   LOGIN MESSAGE
========================================================= */

const loginMessage =
    document.getElementById("loginMessage");


function showLoginMessage(message) {

    if (!loginMessage) {
        return;
    }

    loginMessage.classList.remove("is-success");
    loginMessage.textContent = message;
    loginMessage.style.display = "block";
}


function hideLoginMessage() {

    if (!loginMessage) {
        return;
    }

    loginMessage.classList.remove("is-success");
    loginMessage.textContent = "";
    loginMessage.style.display = "none";
}


/* =========================================================
   LOGIN FORM
========================================================= */

const loginForm =
    document.getElementById("loginForm");


if (loginForm) {

    loginForm.addEventListener(
        "submit",
        async function (event) {

            event.preventDefault();

            hideLoginMessage();


            /* -------------------------------------------------
               GET FORM VALUES
            ------------------------------------------------- */

            const email =
                document
                    .getElementById("email")
                    .value
                    .trim();

            const password =
                document
                    .getElementById("password")
                    .value;

            const remember =
                document
                    .getElementById("remember")
                    .checked;


            /* -------------------------------------------------
               FRONTEND VALIDATION
            ------------------------------------------------- */

            if (!email) {

                showLoginMessage(
                    "Please enter your email."
                );

                return;
            }


            if (!password) {

                showLoginMessage(
                    "Please enter your password."
                );

                return;
            }


            /* -------------------------------------------------
               EMAIL FORMAT
            ------------------------------------------------- */

            const emailPattern =
                /^[^\s@]+@[^\s@]+\.[^\s@]+$/;


            if (!emailPattern.test(email)) {

                showLoginMessage(
                    "Please enter a valid email address."
                );

                return;
            }


            /* -------------------------------------------------
               SIGN IN BUTTON
            ------------------------------------------------- */

            const button =
                loginForm.querySelector(
                    ".signin-button"
                );

            const buttonText =
                button.querySelector("span");

            const originalText =
                buttonText.textContent;


            button.disabled = true;

            buttonText.textContent =
                "Signing in...";


            /* -------------------------------------------------
               SEND REQUEST
            ------------------------------------------------- */

            try {

                const response =
                    await fetch(
                        "/login",
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body:
                                JSON.stringify({
                                    email: email,
                                    password: password,
                                    remember: remember
                                })
                        }
                    );


                const result =
                    await response.json();


                /* -------------------------------------------------
                   LOGIN SUCCESS
                ------------------------------------------------- */

                if (
                    response.ok &&
                    result.success
                ) {

                    window.location.href =
                        result.redirect;

                    return;
                }


                /* -------------------------------------------------
                   LOGIN ERROR
                ------------------------------------------------- */

                showLoginMessage(
                    result.message ||
                    "Invalid email or password."
                );

            }


            /* -------------------------------------------------
               CONNECTION ERROR
            ------------------------------------------------- */

            catch (error) {

                console.error(
                    "Login error:",
                    error
                );

                showLoginMessage(
                    "Unable to connect to the server. Please try again."
                );

            }


            /* -------------------------------------------------
               ENABLE BUTTON
            ------------------------------------------------- */

            finally {

                button.disabled = false;

                buttonText.textContent =
                    originalText;
            }
        }
    );
}


/* =========================================================
   CLEAR ERROR WHEN USER TYPES
========================================================= */

const emailInput =
    document.getElementById("email");


if (emailInput) {

    emailInput.addEventListener(
        "input",
        hideLoginMessage
    );
}


if (passwordInput) {

    passwordInput.addEventListener(
        "input",
        hideLoginMessage
    );
}


/* =========================================================
   FORGOT PASSWORD
========================================================= */

/* =========================================================
   FORGOT PASSWORD (email -> code -> new password)
========================================================= */

(function () {
    "use strict";

    if (!document.getElementById("view-login")) {
        return;
    }

    const VIEWS = ["login", "email", "code", "password", "done"];
    const RESEND_SECONDS = 60;
    const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    const EYE_ON =
        '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />' +
        '<circle cx="12" cy="12" r="2.5" />';

    const EYE_OFF =
        '<path d="M3 3l18 18" />' +
        '<path d="M10.6 10.6a2 2 0 0 0 2.8 2.8" />' +
        '<path d="M9.9 5.2A10.6 10.6 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.1" />' +
        '<path d="M6.6 6.6C3.7 8.5 2 12 2 12s3.5 7 10 7c1.2 0 2.3-.2 3.3-.6" />';

    const $ = id => document.getElementById(id);

    const emailForm = $("fpEmailForm");
    const codeForm = $("fpCodeForm");
    const passwordForm = $("fpPasswordForm");

    const emailMessage = $("fpEmailMessage");
    const codeMessage = $("fpCodeMessage");
    const passwordMessage = $("fpPasswordMessage");
    const loginMsg = $("loginMessage");

    const emailButton = $("fpEmailButton");
    const codeButton = $("fpCodeButton");
    const passwordButton = $("fpPasswordButton");
    const resendButton = $("fpResend");

    const otpInputs = Array.from(document.querySelectorAll(".otp-input"));

    let resetEmail = "";
    let resetToken = "";
    let resendTimer = null;

    /* ---------------------------------------------------------
       Helpers
       --------------------------------------------------------- */

    function showView(name) {
        VIEWS.forEach(view => {
            $("view-" + view).hidden = view !== name;
        });
    }

    function setMessage(node, text, type) {
        if (!node) return;

        if (!text) {
            node.textContent = "";
            node.classList.remove("is-success");
            node.style.display = "none";
            return;
        }

        node.textContent = text;
        node.classList.toggle("is-success", type === "success");
        node.style.display = "block";
    }

    function setBusy(button, busy, busyText) {
        const label = button.querySelector("span");

        if (busy) {
            button.dataset.label = label.textContent;
            label.textContent = busyText;
            button.disabled = true;
        } else {
            if (button.dataset.label) label.textContent = button.dataset.label;
            button.disabled = false;
        }
    }

    async function postJson(url, body) {
        try {
            const response = await fetch(url, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    Accept: "application/json"
                },
                body: JSON.stringify(body)
            });

            let data = {};

            try {
                data = await response.json();
            } catch (error) {
                data = {};
            }

            return {
                ok: response.ok && data.success === true,
                status: response.status,
                data: data
            };

        } catch (error) {
            return {
                ok: false,
                status: 0,
                data: {
                    message: "Unable to connect to the server. Please try again."
                }
            };
        }
    }

    function stopResendTimer() {
        window.clearInterval(resendTimer);
        resendTimer = null;
    }

    function startResendTimer(seconds) {
        stopResendTimer();

        let left = seconds;
        resendButton.disabled = true;

        const tick = function () {
            if (left <= 0) {
                stopResendTimer();
                resendButton.disabled = false;
                resendButton.textContent = "Resend code";
                return;
            }

            resendButton.textContent = "Resend code in " + left + "s";
            left -= 1;
        };

        tick();
        resendTimer = window.setInterval(tick, 1000);
    }

    function resetPasswordFields() {
        ["fpNewPassword", "fpConfirmPassword"].forEach(id => {
            const input = $(id);
            input.value = "";
            input.type = "password";
        });

        document.querySelectorAll("[data-toggle]").forEach(button => {
            button.setAttribute("aria-label", "Show password");
            button.querySelector("svg").innerHTML = EYE_ON;
        });
    }

    function clearOtp() {
        otpInputs.forEach(input => { input.value = ""; });
    }

    function otpValue() {
        return otpInputs.map(input => input.value).join("");
    }

    function backToSignIn(options) {
        const opts = options || {};
        const email = resetEmail;

        stopResendTimer();
        resetEmail = "";
        resetToken = "";

        clearOtp();
        resetPasswordFields();
        setMessage(emailMessage);
        setMessage(codeMessage);
        setMessage(passwordMessage);

        showView("login");

        if (opts.success) {
            $("email").value = email;
            $("password").value = "";

            setMessage(
                loginMsg,
                "Password updated. Please sign in with your new password.",
                "success"
            );

            $("password").focus();
        } else {
            setMessage(loginMsg);
            $("email").focus();
        }
    }

    /* ---------------------------------------------------------
       Show / hide password (new password fields)
       --------------------------------------------------------- */

    document.querySelectorAll("[data-toggle]").forEach(button => {
        button.addEventListener("click", function () {
            const input = $(button.dataset.toggle);
            const show = input.type === "password";

            input.type = show ? "text" : "password";
            button.setAttribute("aria-label", show ? "Hide password" : "Show password");
            button.querySelector("svg").innerHTML = show ? EYE_OFF : EYE_ON;
        });
    });

    /* ---------------------------------------------------------
       Step 1: email
       --------------------------------------------------------- */

    $("forgotPassword").addEventListener("click", function () {
        const typed = $("email").value.trim();

        setMessage(emailMessage);
        $("fpEmail").value = EMAIL_PATTERN.test(typed) ? typed : "";

        showView("email");
        $("fpEmail").focus();
    });

    document.querySelectorAll("[data-fp-back]").forEach(button => {
        button.addEventListener("click", function () {
            backToSignIn();
        });
    });

    emailForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        setMessage(emailMessage);

        const email = $("fpEmail").value.trim().toLowerCase();

        if (!email) {
            return setMessage(emailMessage, "Please enter your email.");
        }

        if (!EMAIL_PATTERN.test(email)) {
            return setMessage(emailMessage, "Please enter a valid email address.");
        }

        setBusy(emailButton, true, "Sending code...");
        const result = await postJson("/api/password-reset/request", { email: email });
        setBusy(emailButton, false);

        if (!result.ok) {
            return setMessage(
                emailMessage,
                result.data.message || "Unable to send the code. Please try again."
            );
        }

        resetEmail = email;
        goToCodeStep(result.data.retry_after || RESEND_SECONDS);
    });

    $("fpEmail").addEventListener("input", function () {
        setMessage(emailMessage);
    });

    /* ---------------------------------------------------------
       Step 2: code
       --------------------------------------------------------- */

    function goToCodeStep(cooldown) {
        $("fpSentTo").textContent = resetEmail;

        clearOtp();
        setMessage(codeMessage);
        showView("code");
        startResendTimer(cooldown);

        otpInputs[0].focus();
    }

    function fillFrom(start, digits) {
        let index = start;

        for (const digit of digits) {
            if (index > 5) break;
            otpInputs[index].value = digit;
            index += 1;
        }

        otpInputs[Math.min(index, 5)].focus();
    }

    otpInputs.forEach(function (input, index) {

        input.addEventListener("focus", function () {
            input.select();
        });

        input.addEventListener("input", function () {
            setMessage(codeMessage);

            const digits = input.value.replace(/\D/g, "");

            if (digits.length > 1) {
                fillFrom(index, digits);
                return;
            }

            input.value = digits;

            if (digits && index < 5) {
                otpInputs[index + 1].focus();
            }
        });

        input.addEventListener("keydown", function (event) {
            if (event.key === "Backspace" && !input.value && index > 0) {
                event.preventDefault();
                otpInputs[index - 1].value = "";
                otpInputs[index - 1].focus();
            }

            if (event.key === "ArrowLeft" && index > 0) {
                event.preventDefault();
                otpInputs[index - 1].focus();
            }

            if (event.key === "ArrowRight" && index < 5) {
                event.preventDefault();
                otpInputs[index + 1].focus();
            }
        });

        input.addEventListener("paste", function (event) {
            event.preventDefault();

            const text = (event.clipboardData || window.clipboardData).getData("text");
            const digits = text.replace(/\D/g, "");

            if (!digits) return;

            fillFrom(digits.length >= 6 ? 0 : index, digits);
        });
    });

    codeForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        setMessage(codeMessage);

        const code = otpValue();

        if (code.length !== 6) {
            return setMessage(codeMessage, "Please enter all 6 digits of the code.");
        }

        setBusy(codeButton, true, "Verifying...");
        const result = await postJson("/api/password-reset/verify", {
            email: resetEmail,
            code: code
        });
        setBusy(codeButton, false);

        if (!result.ok) {
            clearOtp();
            otpInputs[0].focus();

            return setMessage(
                codeMessage,
                result.data.message || "That code is not correct. Please try again."
            );
        }

        resetToken = result.data.reset_token || "";

        stopResendTimer();
        resetPasswordFields();
        setMessage(passwordMessage);
        showView("password");
        $("fpNewPassword").focus();
    });

    resendButton.addEventListener("click", async function () {
        if (resendButton.disabled) return;

        setMessage(codeMessage);
        resendButton.disabled = true;
        resendButton.textContent = "Sending...";

        const result = await postJson("/api/password-reset/request", { email: resetEmail });

        if (!result.ok) {
            resendButton.disabled = false;
            resendButton.textContent = "Resend code";

            if (result.data.retry_after) {
                startResendTimer(result.data.retry_after);
            }

            return setMessage(
                codeMessage,
                result.data.message || "Unable to resend the code. Please try again."
            );
        }

        clearOtp();
        otpInputs[0].focus();
        startResendTimer(result.data.retry_after || RESEND_SECONDS);
        setMessage(codeMessage, "A new code has been sent.", "success");
    });

    $("fpChangeEmail").addEventListener("click", function () {
        stopResendTimer();
        clearOtp();
        setMessage(emailMessage);

        $("fpEmail").value = resetEmail;
        showView("email");
        $("fpEmail").focus();
    });

    /* ---------------------------------------------------------
       Step 3: new password
       --------------------------------------------------------- */

    passwordForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        setMessage(passwordMessage);

        const password = $("fpNewPassword").value;
        const confirm = $("fpConfirmPassword").value;

        if (!password) {
            return setMessage(passwordMessage, "Please enter a new password.");
        }

        if (password.length < 8) {
            return setMessage(passwordMessage, "Password must be at least 8 characters.");
        }

        if (password !== confirm) {
            return setMessage(passwordMessage, "Passwords do not match.");
        }

        setBusy(passwordButton, true, "Updating...");
        const result = await postJson("/api/password-reset/complete", {
            email: resetEmail,
            reset_token: resetToken,
            password: password,
            confirm_password: confirm
        });
        setBusy(passwordButton, false);

        if (!result.ok) {
            // The reset session expired or was already used: start over.
            if (result.data.restart) {
                resetToken = "";
                resetPasswordFields();
                $("fpEmail").value = resetEmail;
                showView("email");

                return setMessage(
                    emailMessage,
                    result.data.message || "Your reset session expired. Please request a new code."
                );
            }

            return setMessage(
                passwordMessage,
                result.data.message || "Unable to update the password. Please try again."
            );
        }

        resetToken = "";
        resetPasswordFields();
        showView("done");
    });

    $("fpNewPassword").addEventListener("input", function () {
        setMessage(passwordMessage);
    });

    $("fpConfirmPassword").addEventListener("input", function () {
        setMessage(passwordMessage);
    });

    /* ---------------------------------------------------------
       Step 4: done
       --------------------------------------------------------- */

    $("fpDoneButton").addEventListener("click", function () {
        backToSignIn({ success: true });
    });
})();


/* =========================================================
   CREATE ACCOUNT
========================================================= */

const createAccount =
    document.getElementById(
        "createAccount"
    );


if (createAccount) {

    createAccount.addEventListener(
        "click",
        function () {

            window.location.href =
                "/signup";
        }
    );
}


/* =========================================================
   AI MATCH SCORE ANIMATION
========================================================= */

document.addEventListener(
    "DOMContentLoaded",
    function () {

        const scoreValue =
            document.getElementById(
                "matchScore"
            );

        const scoreRing =
            document.querySelector(
                ".score-ring-progress"
            );


        if (
            !scoreValue ||
            !scoreRing
        ) {
            return;
        }


        const radius = 42;

        const circumference =
            2 * Math.PI * radius;

        const targetScore = 92;


        scoreRing.style.strokeDasharray =
            circumference;

        scoreRing.style.strokeDashoffset =
            circumference;


        scoreValue.textContent =
            "0%";


        setTimeout(
            function () {

                scoreRing.style.transition =
                    "stroke-dashoffset 1.5s ease-out";

                const offset =
                    circumference -
                    (
                        targetScore / 100
                    ) * circumference;

                scoreRing.style.strokeDashoffset =
                    offset;

            },
            300
        );


        let currentScore = 0;


        const interval =
            setInterval(
                function () {

                    currentScore++;

                    scoreValue.textContent =
                        currentScore + "%";


                    if (
                        currentScore >=
                        targetScore
                    ) {

                        clearInterval(
                            interval
                        );

                        scoreValue.textContent =
                            targetScore + "%";
                    }

                },
                1500 / targetScore
            );
    }
);