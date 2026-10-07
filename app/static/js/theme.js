/* =========================================================
   COMPUTEGRID THEME SWITCHER
   ========================================================= */

(function () {

    const STORAGE_KEY = "computegrid-theme";

    /* ---------------------------------------------------------
       THEME COLORS
       --------------------------------------------------------- */

    const themeStyle = document.createElement("style");

    themeStyle.textContent = `

        /* =========================
           LIGHT THEME
           ========================= */

        :root[data-theme="light"] {

            --bg: #f4f6fb;
            --sidebar: #ffffff;
            --panel: #ffffff;
            --panel-light: #eef1f8;
            --border: #d9deea;

            --text: #172033;
            --muted: #68738a;

            --accent: #5867e8;

            --green: #1fa968;
            --yellow: #d49b16;
            --red: #e05263;
        }


        /* =========================
           THEME TRANSITION
           ========================= */

        body,
        .sidebar,
        .panel,
        .stat-card,
        .worker-node,
        .controller-node,
        .job-panel,
        .summary-card,
        .card,
        .worker-card,
        .connection-status,
        input,
        select,
        button,
        .back-btn,
        .refresh-btn,
        .worker-url-btn {

            transition:
                background-color 0.2s ease,
                border-color 0.2s ease,
                color 0.2s ease,
                box-shadow 0.2s ease;
        }


        /* =========================
           THEME BUTTON
           ========================= */

        .theme-toggle {

            width: 38px;
            height: 38px;

            display: inline-flex;
            align-items: center;
            justify-content: center;

            border: 1px solid var(--border);
            border-radius: 9px;

            background: var(--panel);
            color: var(--text);

            cursor: pointer;

            font-size: 17px;

            transition:
                background-color 0.2s ease,
                border-color 0.2s ease,
                transform 0.15s ease;
        }


        .theme-toggle:hover {

            background: var(--panel-light);
            border-color: var(--accent);

            transform: translateY(-1px);
        }


        .theme-toggle:active {

            transform: translateY(0);
        }


        /* =========================
           WORKER PAGE BUTTON
           ========================= */

        .worker-theme-toggle {

            position: fixed;

            top: 20px;
            right: 20px;

            z-index: 10000;
        }


        /* =========================
           JOB PAGE BUTTON
           ========================= */

        .jobs-theme-toggle {

            margin-left: 8px;
        }


        /* =========================
           DASHBOARD BUTTON
           ========================= */

        .dashboard-theme-toggle {

            margin-left: 0;
        }


        /* =========================
           LIGHT MODE JOB PROGRESS
           ========================= */

        :root[data-theme="light"] .progress-bar {

            background: #e4e8f1;
        }


        :root[data-theme="light"] .worker-url-modal {

            background: rgba(20, 27, 45, 0.35);
        }


        :root[data-theme="light"] .result-preview {

            background: #f4f6fb;
        }


        :root[data-theme="light"] input::placeholder {

            color: #8a94a8;
        }

    `;

    document.head.appendChild(themeStyle);


    /* ---------------------------------------------------------
       LOAD SAVED THEME
       --------------------------------------------------------- */

    const savedTheme = localStorage.getItem(STORAGE_KEY);

    if (savedTheme === "light") {

        document.documentElement.setAttribute(
            "data-theme",
            "light"
        );

    } else {

        document.documentElement.removeAttribute(
            "data-theme"
        );
    }


    /* ---------------------------------------------------------
       CREATE TOGGLE
       --------------------------------------------------------- */

    function createToggle() {

        const button = document.createElement("button");

        button.type = "button";

        button.className = "theme-toggle";

        button.setAttribute(
            "aria-label",
            "Switch theme"
        );

        button.setAttribute(
            "title",
            "Switch theme"
        );


        const isLight =
            document.documentElement.getAttribute("data-theme")
            === "light";


        button.textContent = isLight ? "☀" : "☾";


        /* -----------------------------------------------------
           CLICK
           ----------------------------------------------------- */

        button.addEventListener("click", function () {

            const currentlyLight =
                document.documentElement.getAttribute("data-theme")
                === "light";


            if (currentlyLight) {

                document.documentElement.removeAttribute(
                    "data-theme"
                );

                localStorage.setItem(
                    STORAGE_KEY,
                    "dark"
                );

                button.textContent = "☾";

            } else {

                document.documentElement.setAttribute(
                    "data-theme",
                    "light"
                );

                localStorage.setItem(
                    STORAGE_KEY,
                    "light"
                );

                button.textContent = "☀";
            }

        });


        return button;
    }


    /* ---------------------------------------------------------
       PLACE TOGGLE
       --------------------------------------------------------- */

    function addToggle() {

        const button = createToggle();


        /* Dashboard */

        if (document.querySelector(".sidebar")) {

            button.classList.add(
                "dashboard-theme-toggle"
            );

            const topbarRight =
                document.querySelector(".topbar-right");


            if (topbarRight) {

                const refreshButton =
                    topbarRight.querySelector(".refresh-btn");


                if (refreshButton) {

                    topbarRight.insertBefore(
                        button,
                        refreshButton
                    );

                } else {

                    topbarRight.appendChild(button);

                }

            }

            return;
        }


        /* Jobs page */

        if (document.querySelector(".jobs-page")) {

            button.classList.add(
                "jobs-theme-toggle"
            );


            const header =
                document.querySelector(".jobs-header");


            if (header) {

                const backButton =
                    header.querySelector(".back-btn");


                if (backButton) {

                    header.insertBefore(
                        button,
                        backButton
                    );

                } else {

                    header.appendChild(button);

                }

            }

            return;
        }


        /* Worker page */

        if (document.querySelector(".worker-page")) {

            button.classList.add(
                "worker-theme-toggle"
            );

            document.body.appendChild(button);

        }

    }


    /* ---------------------------------------------------------
       INITIALIZE
       --------------------------------------------------------- */

    if (document.readyState === "loading") {

        document.addEventListener(
            "DOMContentLoaded",
            addToggle
        );

    } else {

        addToggle();

    }

})();