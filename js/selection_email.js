(() => {
    "use strict";

    const ALLOWED_PLACEHOLDERS = ["candidate_name", "job_title"];

    // application id -> ISO time of a send made in this browser session.
    // applicants.js reads this so the "Sent" badge survives re-renders.
    const sentLocal = new Map();
    const busy = new Set();

    const $ = id => document.getElementById(id);

    const tplDialog = $("tpl-dialog");
    const editDialog = $("edit-dialog");
    const confirmDlg = $("confirm-dialog");
    const toastEl = $("se-toast");

    if (!tplDialog || !editDialog || !confirmDlg || !toastEl) return;

    /* ---------------------------------------------------------
       Helpers
       --------------------------------------------------------- */

    function formatSent(iso) {
        if (!iso) return "";
        const date = new Date(iso);
        if (Number.isNaN(date.getTime())) return String(iso);
        return date.toLocaleString([], {
            day: "numeric",
            month: "short",
            hour: "2-digit",
            minute: "2-digit"
        });
    }

    window.selectionEmail = {
        sent: sentLocal,
        label: iso => (iso ? `Sent ${formatSent(iso)}` : "")
    };

    async function api(url, options = {}) {
        const init = {
            method: options.method || "GET",
            credentials: "same-origin",
            cache: "no-store",
            headers: { Accept: "application/json" }
        };

        if (options.body !== undefined) {
            init.headers["Content-Type"] = "application/json";
            init.body = JSON.stringify(options.body);
        }

        let response;

        try {
            response = await fetch(url, init);
        } catch (error) {
            return {
                ok: false,
                status: 0,
                data: {
                    success: false,
                    message: "Network error. Please check your connection and try again."
                }
            };
        }

        let data = {};

        try {
            data = await response.json();
        } catch (error) {
            data = {};
        }

        if (response.status === 401) {
            data.message = "Session expired. Please log in again.";
        }

        return {
            ok: response.ok && data.success === true,
            status: response.status,
            data
        };
    }

    let toastTimer = null;

    function toast(message, kind) {
        toastEl.textContent = message;
        toastEl.dataset.kind = kind;
        toastEl.hidden = false;

        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => {
            toastEl.hidden = true;
        }, kind === "error" ? 8000 : 5000);
    }

    function showError(node, message) {
        node.textContent = message;
        node.hidden = false;
    }

    function clearError(node) {
        node.textContent = "";
        node.hidden = true;
    }

    function unknownPlaceholders(text) {
        const bad = [];

        for (const match of String(text).matchAll(/\{\{\s*([^{}]*?)\s*\}\}/g)) {
            if (!ALLOWED_PLACEHOLDERS.includes(match[1].trim())) {
                bad.push(match[0]);
            }
        }

        return bad;
    }

    function confirmDialog(message, confirmLabel) {
        return new Promise(resolve => {
            const okButton = $("confirm-ok");
            const cancelButton = $("confirm-cancel");
            let result = false;

            $("confirm-message").textContent = message;
            okButton.textContent = confirmLabel || "Confirm";

            const onOk = () => { result = true; confirmDlg.close(); };
            const onCancel = () => confirmDlg.close();

            const onClose = () => {
                okButton.removeEventListener("click", onOk);
                cancelButton.removeEventListener("click", onCancel);
                resolve(result);
            };

            okButton.addEventListener("click", onOk);
            cancelButton.addEventListener("click", onCancel);
            confirmDlg.addEventListener("close", onClose, { once: true });

            confirmDlg.showModal();
            cancelButton.focus();
        });
    }

    /* ---------------------------------------------------------
       Sent badge + row buttons
       --------------------------------------------------------- */

    function markSent(applicationId, sentAt) {
        const when = sentAt || new Date().toISOString();
        sentLocal.set(String(applicationId), when);

        document
            .querySelectorAll(`.email-sent-badge[data-application-id="${applicationId}"]`)
            .forEach(badge => {
                badge.textContent = window.selectionEmail.label(when);
                badge.hidden = false;
            });
    }

    function setRowButtonsBusy(applicationId, isBusy) {
        document
            .querySelectorAll(`[data-se-action][data-application-id="${applicationId}"]`)
            .forEach(button => {
                button.disabled = isBusy;
            });
    }

    /* ---------------------------------------------------------
       Template dialog
       --------------------------------------------------------- */

    const tplSubject = $("tpl-subject");
    const tplBody = $("tpl-body");
    const tplError = $("tpl-error");
    const tplSave = $("tpl-save");
    let tplLastField = tplBody;

    tplSubject.addEventListener("focus", () => { tplLastField = tplSubject; });
    tplBody.addEventListener("focus", () => { tplLastField = tplBody; });

    tplDialog.querySelectorAll(".se-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const token = `{{${chip.dataset.placeholder}}}`;
            const field = tplLastField;
            const start = field.selectionStart ?? field.value.length;
            const end = field.selectionEnd ?? start;

            field.setRangeText(token, start, end, "end");
            field.focus();
        });
    });

        async function openTemplateDialog() {
        clearError(tplError);
        tplSubject.disabled = false;
        tplBody.disabled = false;
        tplSave.disabled = false;
        tplSubject.value = "";
        tplBody.value = "";
        tplLastField = tplBody;

        tplDialog.showModal();
        tplBody.placeholder = "Loading…";

        const result = await api("/api/selection-email/template");

        tplBody.placeholder = "";

        if (!result.ok) {
            showError(
                tplError,
                (result.data.message || "Unable to load the saved template.")
                + " You can still type a new template here."
            );
            tplSubject.focus();
            return;
        }

        tplSubject.value = result.data.subject || "";
        tplBody.value = result.data.body || "";
        tplBody.focus();
    }
    async function saveTemplate() {
        clearError(tplError);

        const subject = tplSubject.value.trim();
        const body = tplBody.value.trim();

        if (!subject) return showError(tplError, "Please enter a subject.");
        if (!body) return showError(tplError, "Please enter the email message.");

        const bad = unknownPlaceholders(subject + "\n" + body);

        if (bad.length) {
            return showError(
                tplError,
                `Unknown placeholder: ${bad[0]}. Use {{candidate_name}} or {{job_title}}.`
            );
        }

        tplSave.disabled = true;
        tplSave.textContent = "Saving…";

        const result = await api("/api/selection-email/template", {
            method: "PUT",
            body: { subject, body }
        });

        tplSave.disabled = false;
        tplSave.textContent = "Save template";

        if (!result.ok) {
            return showError(tplError, result.data.message || "Unable to save the template.");
        }

        tplDialog.close();
        toast("Email template saved.", "success");
    }

    $("open-template-button").addEventListener("click", openTemplateDialog);
    $("tpl-cancel").addEventListener("click", () => tplDialog.close());
    tplSave.addEventListener("click", saveTemplate);

    /* ---------------------------------------------------------
       Send Email (saved template, straight to the candidate)
       --------------------------------------------------------- */

    async function sendSaved(applicationId) {
        if (busy.has(applicationId)) return;

        busy.add(applicationId);
        setRowButtonsBusy(applicationId, true);

        const url = `/api/applications/${encodeURIComponent(applicationId)}/selection-email/send`;

        try {
            let result = await api(url, { method: "POST", body: {} });

            if (result.status === 409 && result.data.already_sent) {
                const again = await confirmDialog(
                    `A selection email was already sent on ${formatSent(result.data.sent_at)}. Send it again?`,
                    "Send again"
                );

                if (!again) return;

                result = await api(url, { method: "POST", body: { confirm_resend: true } });
            }

            if (result.ok) {
                markSent(applicationId, result.data.sent_at);
                toast(result.data.message || "Email sent.", "success");
            } else {
                toast(result.data.message || "The email could not be sent.", "error");
            }
        } finally {
            busy.delete(applicationId);
            setRowButtonsBusy(applicationId, false);
        }
    }

    /* ---------------------------------------------------------
       Edit & Send
       --------------------------------------------------------- */

    const editTo = $("edit-to");
    const editVacancy = $("edit-vacancy");
    const editNotice = $("edit-notice");
    const editSubject = $("edit-subject");
    const editBody = $("edit-body");
    const editError = $("edit-error");
    const editSend = $("edit-send");
    const editCancel = $("edit-cancel");
    let editingId = null;

    async function openEditDialog(applicationId) {
        editingId = applicationId;

        clearError(editError);
        editNotice.hidden = true;
        editTo.textContent = "Loading…";
        editVacancy.textContent = "—";
        editSubject.value = "";
        editBody.value = "";
        editSubject.disabled = true;
        editBody.disabled = true;
        editSend.disabled = true;

        editDialog.showModal();

        const result = await api(
            `/api/applications/${encodeURIComponent(applicationId)}/selection-email/preview`
        );

        if (editingId !== applicationId) return;

        if (!result.ok) {
            editTo.textContent = "—";
            return showError(editError, result.data.message || "Unable to prepare the email.");
        }

        const data = result.data;

        editTo.textContent = data.to_email
            ? `${data.to_name || "Candidate"} <${data.to_email}>`
            : (data.to_name || "No email address");
        editVacancy.textContent = data.job_title || "—";
        editSubject.value = data.subject || "";
        editBody.value = data.body || "";

        if (data.sent_at) {
            editNotice.textContent =
                `A selection email was already sent to this candidate on ${formatSent(data.sent_at)}.`;
            editNotice.hidden = false;
        }

        if (!data.can_send) {
            return showError(
                editError,
                data.problem || "This candidate does not have a usable email address."
            );
        }

        editSubject.disabled = false;
        editBody.disabled = false;
        editSend.disabled = false;
        editBody.focus();
    }

    async function sendEdited() {
        const applicationId = editingId;

        if (!applicationId || busy.has(applicationId)) return;

        clearError(editError);

        const subject = editSubject.value.trim();
        const body = editBody.value.trim();

        if (!subject) return showError(editError, "Please enter a subject.");
        if (!body) return showError(editError, "Please enter the email message.");

        busy.add(applicationId);
        setRowButtonsBusy(applicationId, true);
        editSend.disabled = true;
        editCancel.disabled = true;
        editSend.textContent = "Sending…";

        const url = `/api/applications/${encodeURIComponent(applicationId)}/selection-email/send`;

        try {
            let result = await api(url, { method: "POST", body: { subject, body } });

            if (result.status === 409 && result.data.already_sent) {
                const again = await confirmDialog(
                    `A selection email was already sent on ${formatSent(result.data.sent_at)}. Send another one?`,
                    "Send again"
                );

                if (!again) return;

                result = await api(url, {
                    method: "POST",
                    body: { subject, body, confirm_resend: true }
                });
            }

            if (result.ok) {
                markSent(applicationId, result.data.sent_at);
                editDialog.close();
                toast(result.data.message || "Email sent.", "success");
            } else {
                showError(editError, result.data.message || "The email could not be sent.");
            }
        } finally {
            busy.delete(applicationId);
            setRowButtonsBusy(applicationId, false);
            editSend.disabled = false;
            editCancel.disabled = false;
            editSend.textContent = "Send";
        }
    }

    editSend.addEventListener("click", sendEdited);
    editCancel.addEventListener("click", () => editDialog.close());
    editDialog.addEventListener("close", () => { editingId = null; });

    /* ---------------------------------------------------------
       Row buttons (event delegation: the buttons are re-created
       by applicants.js, so we listen on the document)
       --------------------------------------------------------- */

    document.addEventListener("click", event => {
        const button = event.target.closest("[data-se-action]");
        if (!button || button.disabled) return;

        const applicationId = button.dataset.applicationId;
        if (!applicationId) return;

        if (button.dataset.seAction === "send-email") sendSaved(applicationId);
        if (button.dataset.seAction === "edit-send-email") openEditDialog(applicationId);
    });
})();