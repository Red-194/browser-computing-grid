const jobForm = document.getElementById("jobForm");

const submitBtn = document.getElementById("submitBtn");

const jobStatus = document.getElementById("jobStatus");

const workerStatus = document.getElementById("workerStatus");

const emptyMonitor = document.getElementById("emptyMonitor");

const jobMonitor = document.getElementById("jobMonitor");

const jobIdElement = document.getElementById("jobId");

const taskCountElement = document.getElementById("taskCount");

const jobStateElement = document.getElementById("jobState");

const progressText = document.getElementById("progressText");

const progressFill = document.getElementById("progressFill");

const assignmentTable = document.getElementById("assignmentTable");

const resultArea = document.getElementById("resultArea");

const resultImage = document.getElementById("resultImage");


let currentJobId = null;

let totalTasks = 0;

let completed = false;

let resultPollTimer = null;


/*
 * ---------------------------------------------------------
 * Worker monitoring
 *
 * The existing /events SSE endpoint sends the complete
 * worker list as JSON.
 * ---------------------------------------------------------
 */

const workerSource = new EventSource("/events");


workerSource.onmessage = (event) => {

    try {

        const workers = JSON.parse(event.data);

        const onlineWorkers = workers.filter(
            worker =>
                worker.state === "Connected" ||
                worker.state === "Idle"
        );


        if (onlineWorkers.length === 0) {

            workerStatus.textContent =
                "No available workers";

            workerStatus.parentElement.style.color =
                "var(--red, #ff6678)";

        } else {

            workerStatus.textContent =
                `${onlineWorkers.length} worker${
                    onlineWorkers.length === 1 ? "" : "s"
                } available`;

            workerStatus.parentElement.style.color =
                "var(--green, #39d98a)";

        }


    } catch (error) {

        console.error(
            "Failed to read worker event:",
            error
        );

    }

};


workerSource.onerror = () => {

    workerStatus.textContent =
        "Worker monitor disconnected";

};


/*
 * ---------------------------------------------------------
 * Submit job
 * ---------------------------------------------------------
 */

jobForm.addEventListener("submit", async (event) => {

    event.preventDefault();

    clearJobStatus();

    stopResultPolling();

    completed = false;


    const payload = {

        workload: "mandelbrot",

        config: {

            width: Number(
                document.getElementById("width").value
            ),

            height: Number(
                document.getElementById("height").value
            ),

            x_min: Number(
                document.getElementById("xMin").value
            ),

            x_max: Number(
                document.getElementById("xMax").value
            ),

            y_min: Number(
                document.getElementById("yMin").value
            ),

            y_max: Number(
                document.getElementById("yMax").value
            ),

            max_iterations: Number(
                document.getElementById("maxIterations").value
            ),

            tile_size: Number(
                document.getElementById("tileSize").value
            )

        }

    };


    if (!validatePayload(payload)) {

        return;

    }


    submitBtn.disabled = true;

    submitBtn.textContent = "Submitting...";


    try {

        const response = await fetch("/jobs", {

            method: "POST",

            headers: {

                "Content-Type": "application/json"

            },

            body: JSON.stringify(payload)

        });


        const data = await response.json();


        if (!response.ok) {

            throw new Error(
                data.detail ||
                data.message ||
                "Job submission failed."
            );

        }


        currentJobId = data.job.job_id;

        totalTasks = data.task_count;


        showJobMonitor();

        renderJobSummary(data);

        renderAssignments(data.assignments || []);


        /*
         * No worker available:
         * This is a normal waiting state,
         * not an error.
         */

        if ((data.assignments || []).length === 0) {

            setJobStatus(
                "Job created · Waiting for an available worker.",
                "info"
            );

            setJobState("Waiting");

            updateProgress(0);

        } else {

            setJobStatus(
                `Job submitted successfully. ${data.task_count} task(s) were assigned.`,
                "success"
            );

            setJobState("Running");

            updateProgress(0);

            startResultPolling();

        }


    } catch (error) {

        console.error(
            "Job submission error:",
            error
        );

        setJobStatus(
            error.message ||
            "Unable to submit job.",
            "error"
        );

    } finally {

        submitBtn.disabled = false;

        submitBtn.textContent = "Submit Job";

    }

});


/*
 * ---------------------------------------------------------
 * Validation
 * ---------------------------------------------------------
 */

function validatePayload(payload) {

    const config = payload.config;


    if (config.width <= 0 || config.height <= 0) {

        setJobStatus(
            "Width and height must be greater than zero.",
            "error"
        );

        return false;

    }


    if (config.tile_size <= 0) {

        setJobStatus(
            "Tile size must be greater than zero.",
            "error"
        );

        return false;

    }


    if (config.max_iterations <= 0) {

        setJobStatus(
            "Maximum iterations must be greater than zero.",
            "error"
        );

        return false;

    }


    if (config.x_min >= config.x_max) {

        setJobStatus(
            "X Min must be smaller than X Max.",
            "error"
        );

        return false;

    }


    if (config.y_min >= config.y_max) {

        setJobStatus(
            "Y Min must be smaller than Y Max.",
            "error"
        );

        return false;

    }


    return true;

}


/*
 * ---------------------------------------------------------
 * Job monitor
 * ---------------------------------------------------------
 */

function showJobMonitor() {

    emptyMonitor.style.display = "none";

    jobMonitor.style.display = "block";

    resultArea.classList.remove("visible");

    resultImage.removeAttribute("src");

}


function renderJobSummary(data) {

    jobIdElement.textContent =
        data.job.job_id;

    taskCountElement.textContent =
        data.task_count;

}


/*
 * ---------------------------------------------------------
 * Job state
 *
 * Adds a visual state class so the UI can distinguish:
 *
 * Running    -> blue/purple
 * Waiting    -> yellow
 * Completed  -> green
 * ---------------------------------------------------------
 */

function setJobState(state) {

    jobStateElement.textContent = state;

    jobStateElement.classList.remove(
        "state-running",
        "state-waiting",
        "state-completed"
    );


    if (state === "Running") {

        jobStateElement.classList.add(
            "state-running"
        );

        jobStateElement.style.color =
            "var(--accent, #6c7cff)";


    } else if (state === "Waiting") {

        jobStateElement.classList.add(
            "state-waiting"
        );

        jobStateElement.style.color =
            "var(--yellow, #f5c451)";


    } else if (state === "Completed") {

        jobStateElement.classList.add(
            "state-completed"
        );

        jobStateElement.style.color =
            "var(--green, #39d98a)";


    } else {

        jobStateElement.style.color = "";

    }

}


/*
 * ---------------------------------------------------------
 * Progress
 * ---------------------------------------------------------
 */

function updateProgress(value) {

    const safeValue = Math.max(
        0,
        Math.min(100, value)
    );


    progressFill.style.width =
        `${safeValue}%`;

    progressText.textContent =
        `${Math.round(safeValue)}%`;

}


/*
 * ---------------------------------------------------------
 * Task assignments
 * ---------------------------------------------------------
 */

function renderAssignments(assignments) {

    assignmentTable.innerHTML = "";


    if (assignments.length === 0) {

        assignmentTable.innerHTML = `
            <tr>
                <td colspan="3">
                    No task assignments available.
                </td>
            </tr>
        `;

        return;

    }


    assignments.forEach((assignment) => {

        const row = document.createElement("tr");


        row.innerHTML = `
            <td>
                Task ${assignment.task_id}
            </td>

            <td class="worker-id">
                ${assignment.worker}
            </td>

            <td>
                <span class="status-badge">
                    Assigned
                </span>
            </td>
        `;


        assignmentTable.appendChild(row);

    });

}


/*
 * ---------------------------------------------------------
 * Result polling
 *
 * The existing backend exposes:
 *
 * GET /jobs/{job_id}/result
 *
 * Before completion it returns JSON.
 * After completion it returns image/png.
 * ---------------------------------------------------------
 */

function startResultPolling() {

    stopResultPolling();


    resultPollTimer = setInterval(
        checkJobResult,
        1500
    );


    checkJobResult();

}


async function checkJobResult() {

    if (!currentJobId || completed) {

        return;

    }


    try {

        const response = await fetch(
            `/jobs/${currentJobId}/result`,
            {
                cache: "no-store"
            }
        );


        const contentType =
            response.headers.get("content-type") || "";


        if (contentType.includes("image/png")) {

            const blob = await response.blob();

            const imageUrl =
                URL.createObjectURL(blob);


            resultImage.src = imageUrl;

            resultArea.classList.add("visible");

            completed = true;

            setJobState("Completed");

            updateProgress(100);

            progressText.textContent =
                "Completed";


            setJobStatus(
                "Job completed successfully. Final result received.",
                "success"
            );


            stopResultPolling();

            return;

        }


        const data = await response.json();


        if (
            data.message ===
            "Job is still processing."
        ) {

            setJobState("Running");

            return;

        }


        if (
            data.message ===
            "Job not found."
        ) {

            setJobState("Unknown");

            setJobStatus(
                "The backend no longer has this job.",
                "error"
            );

            stopResultPolling();

        }


    } catch (error) {

        console.error(
            "Result polling error:",
            error
        );

    }

}


/*
 * ---------------------------------------------------------
 * Helpers
 * ---------------------------------------------------------
 */

function stopResultPolling() {

    if (resultPollTimer !== null) {

        clearInterval(resultPollTimer);

        resultPollTimer = null;

    }

}


function setJobStatus(message, type) {

    jobStatus.textContent = message;

    jobStatus.className =
        `job-status ${type}`;

}


function clearJobStatus() {

    jobStatus.textContent = "";

    jobStatus.className =
        "job-status";

}