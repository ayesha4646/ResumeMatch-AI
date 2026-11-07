document.addEventListener("DOMContentLoaded", function () {

    const currentPath =
        window.location.pathname.replace(/\/+$/, "") || "/";

    document.querySelectorAll(".sidebar .nav-item").forEach(function (item) {

        const href = item.getAttribute("href");

        if (!href || href === "/logout") {
            return;
        }

        const linkPath =
            new URL(href, window.location.origin)
                .pathname
                .replace(/\/+$/, "") || "/";

        item.classList.toggle(
            "active",
            linkPath === currentPath
        );
    });


    const greeting = document.getElementById("greetingText");

    if (greeting) {

        const name =
            greeting.dataset.userName || "Ayesha";

        const hour = new Date().getHours();

        let greetingText;

        if (hour >= 5 && hour < 12) {
            greetingText = "Good morning";
        } else if (hour >= 12 && hour < 18) {
            greetingText = "Good afternoon";
        } else if (hour >= 18 && hour < 22) {
            greetingText = "Good evening";
        } else {
            greetingText = "Good night";
        }

        greeting.textContent =
            `${greetingText}, ${name}`;
    }

});
document.addEventListener("DOMContentLoaded", function () {

    const currentPath =
        window.location.pathname.replace(/\/+$/, "") || "/";

    document.querySelectorAll(".sidebar .nav-item").forEach(function (item) {

        const href = item.getAttribute("href");

        if (!href || href === "/logout") {
            return;
        }

        const linkPath =
            new URL(href, window.location.origin)
                .pathname
                .replace(/\/+$/, "") || "/";

        item.classList.toggle(
            "active",
            linkPath === currentPath
        );
    });


    const greeting = document.getElementById("greetingText");

    if (greeting) {

        const name =
            greeting.dataset.userName || "Ayesha";

        const hour = new Date().getHours();

        let greetingText;

        if (hour >= 5 && hour < 12) {
            greetingText = "Good morning";
        } else if (hour >= 12 && hour < 18) {
            greetingText = "Good afternoon";
        } else if (hour >= 18 && hour < 22) {
            greetingText = "Good evening";
        } else {
            greetingText = "Good night";
        }

        greeting.textContent = `${greetingText}, ${name}`;
    }

});