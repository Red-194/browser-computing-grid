"use strict";

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
const workloadSelect = document.getElementById("workload");
const nQueensOptions = document.getElementById("nQueensOptions");
const resultPreviewLabel = document.getElementById("resultPreviewLabel");
const nQueensResult = document.getElementById("nQueensResult");
const nQueensStats = document.getElementById("nQueensStats");
const nQueensRawResult = document.getElementById("nQueensRawResult");

let currentJobId = null;
let currentWorkload = "mandelbrot";
let currentPayload = null;
let totalTasks = 0;
let completed = false;
let resultPollTimer = null;
let activeResultUrl = null;

// Listen for live worker updates from the backend.
const workerSource = new EventSource("/events");

workerSource.onmessage = (event) => {
    try {
        const workers = JSON.parse(event.data);

        const onlineWorkers = workers.filter(worker =>
            worker.state === "Connected" ||
            worker.state === "Idle"
        );

        if (onlineWorkers.length === 0) {
            workerStatus.textContent = "No available workers";
            workerStatus.parentElement.style.color =
                "var(--red, #ff6678)";
        } else {
            workerStatus.textContent =
                `${onlineWorkers.length} worker` +
                `${onlineWorkers.length === 1 ? "" : "s"} available`;

            workerStatus.parentElement.style.color =
                "var(--green, #39d98a)";
        }
    } catch (error) {
        console.error("Failed to read worker event:", error);
    }
};

workerSource.onerror = () => {
    workerStatus.textContent = "Worker monitor disconnected";
};

// Show only the fields for the selected workload.
//
// Every workload section in jobs.html has:
//   class="workload-option" data-workload="<name>"
// Sections for other workloads are hidden, and their inputs
// are disabled so the browser does not check them on submit.
function updateWorkloadFields() {
    const workload = workloadSelect.value;

    document.querySelectorAll(".workload-option").forEach(section => {
        const show = section.dataset.workload === workload;

        section.hidden = !show;

        section.querySelectorAll("input, select, textarea").forEach(field => {
            field.disabled = !show;
        });
    });

    updateSourceFields();
}

// Some workloads have a "source" dropdown, for example
// "Random 3-SAT" or "My own instances". Show only the
// part that matches the chosen source.
//
// In jobs.html the parts look like:
//   <div data-source-of="satBatchSource" data-source="random">
function updateSourceFields() {
    document.querySelectorAll(".source-select").forEach(select => {
        const parts = document.querySelectorAll(
            `[data-source-of="${select.id}"]`
        );

        parts.forEach(part => {
            part.hidden = part.dataset.source !== select.value;
        });
    });
}

workloadSelect.addEventListener("change", updateWorkloadFields);

document.querySelectorAll(".source-select").forEach(select => {
    select.addEventListener("change", updateSourceFields);
});

updateWorkloadFields();


// Display names used in messages and the result title.
const WORKLOAD_NAMES = {
    mandelbrot: "Mandelbrot",
    nqueens: "N-Queens",
    sat: "SAT",
    sat_batch: "SAT Batch",
    compression: "Compression",
    regex: "Regex"
};

// Submit a real job to the backend.
jobForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    clearJobStatus();
    stopResultPolling();

    completed = false;
    currentJobId = null;
    totalTasks = 0;
    currentWorkload = workloadSelect.value;

    const payload = buildPayload(currentWorkload);

    if (!validatePayload(payload)) {
        return;
    }

    currentPayload = payload;

    submitBtn.disabled = true;
    submitBtn.textContent = "Submitting...";

    try {
        const response = await sendJob(payload);

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                errorText(data.detail) ||
                data.message ||
                "Job submission failed."
            );
        }

        if (!data.job || !data.job.job_id) {
            throw new Error(
                "The server response did not include a job ID."
            );
        }

        currentJobId = data.job.job_id;
        totalTasks = Number(data.task_count || 0);

        showJobMonitor();
        renderJobSummary(data);
        renderAssignments(data.assignments || []);
        updateProgress(0);

        if ((data.assignments || []).length === 0) {
            setJobStatus(
                "Job created. Waiting for an available worker.",
                "info"
            );
            setJobState("Waiting");
        } else {
            setJobStatus(
                `Job submitted successfully. ${totalTasks} task(s) created.`,
                "success"
            );
            setJobState("Running");
        }

        startResultPolling();

    } catch (error) {
        console.error("Job submission error:", error);

        setJobStatus(
            error.message || "Unable to submit job.",
            "error"
        );

    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Submit Job";
    }
});

// Send the job to the backend.
// Compression with an uploaded file uses the upload endpoint,
// everything else is sent as JSON to /jobs.
function sendJob(payload) {
    if (payload.file) {
        const form = new FormData();

        form.append("file", payload.file);
        form.append("variants", payload.config.variants.join(","));
        form.append("chunk_size", payload.config.chunk_size);

        return fetch("/jobs/compression/upload", {
            method: "POST",
            body: form
        });
    }

    return fetch("/jobs", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    });
}

// Turn a backend error into readable text.
// Validation errors come back as a list of {msg: ...}.
function errorText(detail) {
    if (Array.isArray(detail)) {
        return detail.map(item => item.msg || String(item)).join(" ");
    }

    return detail;
}

// Small helpers for reading form fields.
function numberValue(id) {
    return Number(document.getElementById(id).value);
}

function textValue(id) {
    return document.getElementById(id).value;
}

// Non-empty lines of a textarea.
// Lines are kept as typed (spaces can matter in a regex).
function lineList(id) {
    return textValue(id)
        .split("\n")
        .map(line => line.replace(/\r$/, ""))
        .filter(line => line.trim() !== "");
}

// "1 -2 3" -> [1, -2, 3]
// A trailing 0 (DIMACS style) is ignored.
// Bad numbers become NaN so validation can catch them.
function parseClause(line) {
    const literals = line
        .split(/[\s,]+/)
        .filter(part => part !== "")
        .map(Number);

    if (literals.length > 1 && literals[literals.length - 1] === 0) {
        literals.pop();
    }

    return literals;
}

// One clause per line.
function parseClauses(text) {
    return text
        .split("\n")
        .map(line => line.trim())
        .filter(line => line !== "")
        .map(parseClause);
}

// Instances are separated by an empty line.
function parseInstances(text) {
    return text
        .split(/\n\s*\n/)
        .map(block => parseClauses(block))
        .filter(clauses => clauses.length > 0)
        .map(clauses => ({
            // Biggest variable used = number of variables.
            num_variables: Math.max(
                1,
                ...clauses.flat().map(literal => Math.abs(literal) || 0)
            ),
            clauses
        }));
}

// True when every literal is a whole number, not 0,
// and not bigger than numVariables.
function clausesAreValid(clauses, numVariables) {
    return clauses.every(clause =>
        clause.length > 0 &&
        clause.every(literal =>
            Number.isInteger(literal) &&
            literal !== 0 &&
            Math.abs(literal) <= numVariables
        )
    );
}

// Build the payload sent to the actual backend.
function buildPayload(workload) {
    if (workload === "sat") {
        return {
            workload: "sat",
            config: {
                num_variables: numberValue("satNumVariables"),
                clauses: parseClauses(textValue("satClauses")),
                split_depth: numberValue("satSplitDepth")
            }
        };
    }

    if (workload === "sat_batch") {
        if (textValue("satBatchSource") === "custom") {
            return {
                workload: "sat_batch",
                config: {
                    instances: parseInstances(textValue("satBatchInstances"))
                }
            };
        }

        return {
            workload: "sat_batch",
            config: {
                random_3sat: {
                    count: numberValue("satBatchCount"),
                    num_variables: numberValue("satBatchVariables"),
                    num_clauses: numberValue("satBatchClauses"),
                    seed: numberValue("satBatchSeed")
                }
            }
        };
    }

    if (workload === "compression") {
        const config = {
            variants: textValue("compressionVariants").split(","),
            chunk_size: numberValue("compressionChunkSize") * 1024
        };

        if (textValue("compressionSource") === "upload") {
            // Sent as a file by sendJob(), not as JSON.
            return {
                workload: "compression",
                config,
                file: document.getElementById("compressionFile").files[0]
            };
        }

        config.synthetic_size = numberValue("compressionSize") * 1024;
        config.seed = numberValue("compressionSeed");

        return {
            workload: "compression",
            config
        };
    }

    if (workload === "regex") {
        const config = {
            patterns: lineList("regexPatterns"),
            mode: textValue("regexMode"),
            texts_per_task: numberValue("regexTextsPerTask")
        };

        if (textValue("regexSource") === "custom") {
            config.texts = lineList("regexTexts");
        } else {
            config.synthetic_texts = {
                count: numberValue("regexCount"),
                min_length: numberValue("regexMinLength"),
                max_length: numberValue("regexMaxLength"),
                seed: numberValue("regexSeed")
            };
        }

        return {
            workload: "regex",
            config
        };
    }

    if (workload === "nqueens") {
        return {
            workload: "nqueens",
            config: {
                n: Number(
                    document.getElementById("queensN").value
                ),
                split_depth: Number(
                    document.getElementById("splitDepth").value
                )
            }
        };
    }

    return {
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
}

// Show an error and return false (keeps validation short).
function fail(message) {
    setJobStatus(message, "error");
    return false;
}

function isWhole(value, min, max = Infinity) {
    return Number.isInteger(value) && value >= min && value <= max;
}

// Validate user inputs before submitting.
function validatePayload(payload) {
    const config = payload.config;

    if (payload.workload === "sat") {
        if (!isWhole(config.num_variables, 1)) {
            return fail("Number of variables must be a whole number of at least 1.");
        }

        if (config.clauses.length === 0) {
            return fail("Enter at least one clause.");
        }

        if (!clausesAreValid(config.clauses, config.num_variables)) {
            return fail(
                "Each clause must use whole numbers (not 0) between " +
                `-${config.num_variables} and ${config.num_variables}.`
            );
        }

        // 2^split_depth tasks are created, so keep it reasonable.
        if (!isWhole(config.split_depth, 0, Math.min(16, config.num_variables))) {
            return fail(
                "Split depth must be between 0 and " +
                `${Math.min(16, config.num_variables)} (and not more than the number of variables).`
            );
        }

        return true;
    }

    if (payload.workload === "sat_batch") {
        if (config.instances) {
            if (config.instances.length === 0) {
                return fail("Enter at least one instance.");
            }

            const allValid = config.instances.every(instance =>
                clausesAreValid(instance.clauses, instance.num_variables)
            );

            if (!allValid) {
                return fail("Clauses must only contain whole numbers, and not 0.");
            }

            return true;
        }

        const random = config.random_3sat;

        if (!isWhole(random.count, 1, 10000)) {
            return fail("Number of instances must be between 1 and 10000.");
        }

        if (!isWhole(random.num_variables, 3)) {
            return fail("Variables per instance must be at least 3.");
        }

        if (!isWhole(random.num_clauses, 1)) {
            return fail("Clauses per instance must be at least 1.");
        }

        if (!Number.isInteger(random.seed)) {
            return fail("Seed must be a whole number.");
        }

        return true;
    }

    if (payload.workload === "compression") {
        if (!isWhole(config.chunk_size, 1024)) {
            return fail("Chunk size must be a whole number of at least 1 KB.");
        }

        if (textValue("compressionSource") === "upload") {
            if (!payload.file) {
                return fail("Choose a file to compress.");
            }

            if (payload.file.size === 0) {
                return fail("The chosen file is empty.");
            }

            if (payload.file.size > 64 * 1024 * 1024) {
                return fail("The file must be 64 MB or smaller.");
            }

            return true;
        }

        if (!isWhole(config.synthetic_size, 1024, 64 * 1024 * 1024)) {
            return fail("Data size must be between 1 and 65536 KB.");
        }

        if (!Number.isInteger(config.seed)) {
            return fail("Seed must be a whole number.");
        }

        return true;
    }

    if (payload.workload === "regex") {
        if (config.patterns.length === 0) {
            return fail("Enter at least one pattern.");
        }

        if (!isWhole(config.texts_per_task, 1)) {
            return fail("Texts per task must be at least 1.");
        }

        if (config.texts) {
            if (config.texts.length === 0) {
                return fail("Enter at least one text.");
            }

            return true;
        }

        const random = config.synthetic_texts;

        if (!isWhole(random.count, 1, 1000000)) {
            return fail("Number of texts must be between 1 and 1000000.");
        }

        if (!isWhole(random.min_length, 0) || !isWhole(random.max_length, 0)) {
            return fail("Lengths must be whole numbers of 0 or more.");
        }

        if (random.min_length > random.max_length) {
            return fail("Min length cannot be bigger than max length.");
        }

        if (!Number.isInteger(random.seed)) {
            return fail("Seed must be a whole number.");
        }

        return true;
    }

    if (payload.workload === "nqueens") {
        if (
            !Number.isInteger(config.n) ||
            config.n < 4 ||
            config.n > 14
        ) {
            setJobStatus(
                "Board size N must be a whole number between 4 and 14.",
                "error"
            );
            return false;
        }

        if (
            !Number.isInteger(config.split_depth) ||
            config.split_depth < 1 ||
            config.split_depth > 6
        ) {
            setJobStatus(
                "Split depth must be a whole number between 1 and 6.",
                "error"
            );
            return false;
        }

        if (config.split_depth > config.n) {
            setJobStatus(
                "Split depth cannot be greater than board size N.",
                "error"
            );
            return false;
        }

        return true;
    }

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

// Prepare the monitor for the newly submitted job.
function showJobMonitor() {
    emptyMonitor.style.display = "none";
    jobMonitor.style.display = "block";

    resultArea.classList.remove("visible");

    resultImage.hidden = false;
    resultImage.removeAttribute("src");

    nQueensResult.hidden = true;
nQueensStats.hidden = true;
nQueensStats.innerHTML = "";

nQueensRawResult.hidden = true;
nQueensRawResult.textContent = "";

    resultPreviewLabel.textContent =
        currentWorkload === "mandelbrot"
            ? "Mandelbrot Output"
            : `${WORKLOAD_NAMES[currentWorkload]} Results`;

    if (activeResultUrl) {
        URL.revokeObjectURL(activeResultUrl);
        activeResultUrl = null;
    }
}

function renderJobSummary(data) {
    jobIdElement.textContent = data.job.job_id;
    taskCountElement.textContent = data.task_count ?? "-";
}

function setJobState(state) {
    jobStateElement.textContent = state;

    jobStateElement.classList.remove(
        "state-running",
        "state-waiting",
        "state-completed"
    );

    if (state === "Running") {
        jobStateElement.classList.add("state-running");
        jobStateElement.style.color = "var(--accent, #6c7cff)";
    } else if (state === "Waiting") {
        jobStateElement.classList.add("state-waiting");
        jobStateElement.style.color = "var(--yellow, #f5c451)";
    } else if (state === "Completed") {
        jobStateElement.classList.add("state-completed");
        jobStateElement.style.color = "var(--green, #39d98a)";
    } else if (state === "Failed") {
        jobStateElement.style.color = "var(--red, #ff6678)";
    } else {
        jobStateElement.style.color = "";
    }
}

// Update the progress bar.
function updateProgress(value) {
    const safeValue = Math.max(0, Math.min(100, value));

    progressFill.style.width = `${safeValue}%`;
    progressText.textContent = `${Math.round(safeValue)}%`;
}

// Render actual task assignments returned by the backend.
function renderAssignments(assignments) {
    assignmentTable.innerHTML = "";

    if (assignments.length === 0) {
        assignmentTable.innerHTML =
            '<tr><td colspan="3">No task assignments available yet.</td></tr>';
        return;
    }

    assignments.forEach(assignment => {
        const row = document.createElement("tr");

        const taskCell = document.createElement("td");
        taskCell.textContent = `Task ${assignment.task_id}`;

        const workerCell = document.createElement("td");
        workerCell.textContent =
            assignment.worker_id || "Pending";

        const statusCell = document.createElement("td");
        statusCell.textContent =
            assignment.status || "Assigned";

        row.append(taskCell, workerCell, statusCell);
        assignmentTable.appendChild(row);
    });
}

function clearJobStatus() {
    jobStatus.textContent = "";
    jobStatus.className = "";
}

function setJobStatus(message, type) {
    jobStatus.textContent = message;
    jobStatus.className = `status-message ${type}`;
}

// Start polling for task updates and the final result.
function startResultPolling() {
    stopResultPolling();

    if (!currentJobId) {
        return;
    }

    refreshTaskAssignments(currentJobId);
    checkJobResult();

    resultPollTimer = setInterval(() => {
        if (!completed && currentJobId) {
            refreshTaskAssignments(currentJobId);
            checkJobResult();
        }
    }, 1500);
}

function stopResultPolling() {
    if (resultPollTimer) {
        clearInterval(resultPollTimer);
        resultPollTimer = null;
    }
}

// Fetch the latest task assignments and calculate real progress.
async function refreshTaskAssignments(jobId) {
    // Do not update the monitor after a job is completed
    // or when this response belongs to an older job.
    if (completed || jobId !== currentJobId) {
        return;
    }

    try {
        const response = await fetch(
            `/jobs/${encodeURIComponent(jobId)}/tasks`,
            { cache: "no-store" }
        );

        if (!response.ok) {
            return;
        }

        const data = await response.json();

        // Check again because the job may have completed
        // while this request was waiting for a response.
        if (completed || jobId !== currentJobId) {
            return;
        }

        const tasks = data.tasks || [];

        renderAssignments(tasks);

        if (tasks.length === 0) {
            return;
        }

        totalTasks = tasks.length;

        const completedTasks = tasks.filter(task =>
            String(task.status || "").toLowerCase() === "completed"
        ).length;

        const progress = (completedTasks / totalTasks) * 100;
        updateProgress(progress);

        if (completedTasks === totalTasks && totalTasks > 0) {
            // Tasks are finished, but wait for checkJobResult()
            // to confirm that the final result is ready.
            if (!completed) {
                setJobState("Running");
            }
        } else {
            const pendingTasks = tasks.some(task =>
                String(task.status || "").toLowerCase() === "pending"
            );

            if (!completed) {
                setJobState(pendingTasks ? "Waiting" : "Running");
            }
        }

    } catch (error) {
        console.error("Failed to refresh task assignments:", error);
    }
}

// Check whether the backend has produced the final result.
async function checkJobResult() {
    if (!currentJobId || completed) {
        return;
    }

    const jobId = currentJobId;

    // Refresh task status separately; do not add stray text after this call.
    refreshTaskAssignments(jobId);

    try {
        const response = await fetch(
            `/jobs/${encodeURIComponent(jobId)}/result`,
            { cache: "no-store" }
        );

        if (jobId !== currentJobId) {
            return;
        }

        const contentType =
            response.headers.get("content-type") || "";

        // The backend may return an image directly for Mandelbrot.
        if (contentType.includes("image/png")) {
            if (!response.ok) {
                throw new Error("Could not retrieve the image result.");
            }

            const blob = await response.blob();

            if (jobId !== currentJobId) {
                return;
            }

            if (activeResultUrl) {
                URL.revokeObjectURL(activeResultUrl);
            }

            activeResultUrl = URL.createObjectURL(blob);
            resultImage.src = activeResultUrl;
            resultImage.hidden = false;

            nQueensResult.hidden = true;
            resultArea.classList.add("visible");

            finishJob();
            setJobStatus("Mandelbrot job completed.", "success");
            return;
        }

        // Other responses are expected to be JSON.
        const data = await response.json();

        if (jobId !== currentJobId) {
            return;
        }

        // A missing in-memory job can happen after a server restart.
        if (response.status === 404) {
            console.warn("Job result endpoint returned 404:", data);
            return;
        }

        // A task ran out of retries, so the job can never complete. Stop
        // polling and say so instead of showing "Running" forever.
        if (data.status === "failed" || data.message === "Job failed.") {
            failJob(data);
            return;
        }

        if (!response.ok && response.status !== 202) {
            throw new Error(
                data.detail ||
                data.message ||
                "Failed to retrieve the job result."
            );
        }

        // The backend uses HTTP 200 for this message while processing.
        if (
            response.status === 202 ||
            data.message === "Job is still processing." ||
            data.status === "processing" ||
            data.status === "running" ||
            data.status === "pending"
        ) {
            if (!completed) {
                setJobState("Running");
            }
            return;
        }

        const result = data.result || data;

        // Display N-Queens results when the expected fields are present.
        if (
            currentWorkload === "nqueens" &&
            (
                result.solutions !== undefined ||
                result.nodes !== undefined
            )
        ) {
            renderNQueensResult(result);
            finishJob();
            setJobStatus("N-Queens job completed.", "success");
            return;
        }

        // SAT, SAT Batch, Compression and Regex:
        // HTTP 200 means the final result is ready.
        if (
            response.ok &&
            ["sat", "sat_batch", "compression", "regex"].includes(currentWorkload)
        ) {
            renderJsonResult(currentWorkload, result);
            finishJob();
            setJobStatus(
                `${WORKLOAD_NAMES[currentWorkload]} job completed.`,
                "success"
            );
            return;
        }

        // Handle other explicitly completed JSON results.
        if (
            data.status === "completed" ||
            data.completed === true
        ) {
            nQueensRawResult.textContent =
                JSON.stringify(result, null, 2);

            nQueensRawResult.hidden = false;
            resultImage.hidden = true;
            resultArea.classList.add("visible");

            finishJob();
            setJobStatus("Job completed.", "success");
            return;
        }

        // Keep waiting if the response does not identify a final result.
        console.log("Job result response:", data);

    } catch (error) {
        console.error("Error checking job result:", error);

        if (!completed && jobId === currentJobId) {
            setJobStatus(
                "Waiting for the backend result. Check the server logs if this persists.",
                "info"
            );
        }
    }
}

// Render the N-Queens statistics and raw result.

function renderNQueensResult(result) {
    resultImage.hidden = true;
    resultImage.removeAttribute("src");
    resultPreviewLabel.textContent = "N-Queens Results";

    nQueensResult.hidden = false;
    nQueensStats.hidden = false;
    nQueensRawResult.hidden = false;
    resultArea.classList.add("visible");

    const stats = [
        ["Board Size", result.n ?? "-"],
        ["Solutions", result.solutions ?? "-"],
        ["Nodes Explored", result.nodes ?? "-"],
        ["Tasks", result.tasks ?? totalTasks],
        ["Smallest Task Nodes", result.min_task_nodes ?? "-"],
        ["Largest Task Nodes", result.max_task_nodes ?? "-"],
        [
            "Max Task Time (ms)",
            result.max_task_time_ms !== undefined
                ? Number(result.max_task_time_ms).toFixed(2)
                : "-"
        ]
    ];

    nQueensStats.innerHTML = "";
    nQueensStats.classList.add("nqueens-stats");

    stats.forEach(([label, value]) => {
        const card = document.createElement("div");
        card.className = "nqueens-stat";

        const heading = document.createElement("span");
        heading.className = "nqueens-stat-label";
        heading.textContent = label;

        const number = document.createElement("strong");
        number.className = "nqueens-stat-value";
        number.textContent = String(value);

        card.append(heading, number);
        nQueensStats.appendChild(card);
    });

    const arrangement =
        result.queen_positions ??
        result.positions ??
        result.solution ??
        result.board;

    nQueensResult.innerHTML = "";

    const n = Number(result.n);
    let queenColumns = null;

    if (
        Number.isInteger(n) &&
        n >= 1 &&
        n <= 14 &&
        Array.isArray(arrangement)
    ) {
        if (
            arrangement.length === n &&
            arrangement.every(
                col => Number.isInteger(col) && col >= 0 && col < n
            )
        ) {
            queenColumns = arrangement;
        } else if (
            arrangement.length === n &&
            arrangement.every(
                item =>
                    item &&
                    Number.isInteger(item.row) &&
                    Number.isInteger(item.col)
            )
        ) {
            const columns = Array(n).fill(-1);

            arrangement.forEach(({ row, col }) => {
                if (row >= 0 && row < n && col >= 0 && col < n) {
                    columns[row] = col;
                }
            });

            if (columns.every(col => col >= 0)) {
                queenColumns = columns;
            }
        }
    }

    // The backend only sends counts, not a queen layout.
    // So we find one example layout here and draw that.
    let isExample = false;

    if (!queenColumns && Number.isInteger(n) && n >= 1 && n <= 14) {
        queenColumns = findOneSolution(n);
        isExample = queenColumns !== null;
    }

    if (queenColumns) {
        if (isExample) {
            const caption = document.createElement("p");
            caption.className = "nqueens-board-message";
            caption.textContent =
                `One example of the ${result.solutions ?? ""} solutions ` +
                `for a ${n} x ${n} board:`;
            nQueensResult.appendChild(caption);
        }

        const board = document.createElement("div");
        board.className = "nqueens-board";
        board.style.setProperty("--board-size", n);
        board.setAttribute("role", "img");
        board.setAttribute(
            "aria-label",
            `${n} by ${n} chessboard showing a queen arrangement`
        );

        for (let row = 0; row < n; row++) {
            for (let col = 0; col < n; col++) {
                const square = document.createElement("div");
                square.className =
                    "nqueens-square " +
                    ((row + col) % 2 === 0 ? "light" : "dark");

                if (queenColumns[row] === col) {
                    const queen = document.createElement("span");
                    queen.className = "nqueens-queen";
                    queen.textContent = "♛";
                    square.appendChild(queen);
                }

                board.appendChild(square);
            }
        }

        nQueensResult.appendChild(board);
    } else {
        const message = document.createElement("p");
        message.className = "nqueens-board-message";
        message.textContent =
            `A ${result.n} x ${result.n} board has no solution, ` +
            "so there is no board to show.";

        nQueensResult.appendChild(message);
    }

    nQueensRawResult.classList.add("nqueens-raw-result");
    nQueensRawResult.textContent = JSON.stringify(result, null, 2);
}

// Pick the numbers worth showing for each workload.
// Returns a list of [label, value] pairs.
function resultStats(workload, result) {
    if (workload === "sat") {
        return [
            ["Result", result.satisfiable ? "Satisfiable" : "Unsatisfiable"],
            ["Tasks", totalTasks]
            // The full model (variable values) is in the JSON below.
        ];
    }

    if (workload === "sat_batch") {
        return [
            ["Instances", result.instances ?? "-"],
            ["Satisfiable", result.satisfiable ?? "-"],
            ["Unsatisfiable", result.unsatisfiable ?? "-"],
            ["Fastest (ms)", formatMs(result.min_time_ms)],
            ["Slowest (ms)", formatMs(result.max_time_ms)]
        ];
    }

    if (workload === "compression") {
        const stats = [];

        Object.entries(result).forEach(([variant, info]) => {
            stats.push([`${variant} Ratio`, info.ratio ?? "-"]);
            stats.push([`${variant} Speed (MB/s)`, info.mb_per_second ?? "-"]);
        });

        return stats;
    }

    if (workload === "regex") {
        const patterns = result.patterns || [];
        const isScan = currentPayload?.config.mode === "scan";

        return patterns.map(item => [
            item.compile_error
                ? `${item.pattern} (error)`
                : `${item.pattern} ${isScan ? "matches" : "matched texts"}`,
            isScan ? item.total_matches : item.matched_texts
        ]);
    }

    return [];
}

function formatMs(value) {
    return value === null || value === undefined
        ? "-"
        : Number(value).toFixed(2);
}

// Show SAT / SAT Batch / Compression / Regex results:
// a few stat cards plus the full JSON below them.
// Uses the same boxes and styles as the N-Queens result.
function renderJsonResult(workload, result) {
    resultImage.hidden = true;
    resultImage.removeAttribute("src");
    resultPreviewLabel.textContent = `${WORKLOAD_NAMES[workload]} Results`;

    nQueensResult.hidden = true;
    nQueensStats.hidden = false;
    nQueensRawResult.hidden = false;
    resultArea.classList.add("visible");

    nQueensStats.innerHTML = "";
    nQueensStats.classList.add("nqueens-stats");

    resultStats(workload, result).forEach(([label, value]) => {
        const card = document.createElement("div");
        card.className = "nqueens-stat";

        const heading = document.createElement("span");
        heading.className = "nqueens-stat-label";
        heading.textContent = label;

        const number = document.createElement("strong");
        number.className = "nqueens-stat-value";
        number.textContent = String(value);

        card.append(heading, number);
        nQueensStats.appendChild(card);
    });

    nQueensRawResult.classList.add("nqueens-raw-result");
    nQueensRawResult.textContent = JSON.stringify(result, null, 2);
}

// Find one N-Queens layout by simple backtracking.
// Returns a list: columns[row] = column of the queen in that row.
// Returns null when there is no solution (n = 2 or 3).
// Fast for n up to 14.
function findOneSolution(n) {
    const columns = [];

    function isSafe(row, col) {
        for (let r = 0; r < row; r++) {
            const c = columns[r];

            // Same column or same diagonal
            if (c === col || Math.abs(c - col) === row - r) {
                return false;
            }
        }
        return true;
    }

    function place(row) {
        if (row === n) {
            return true;
        }

        for (let col = 0; col < n; col++) {
            if (isSafe(row, col)) {
                columns[row] = col;

                if (place(row + 1)) {
                    return true;
                }
            }
        }

        return false;
    }

    return place(0) ? columns : null;
}

// Mark the job as finished and stop polling.
function finishJob() {
    completed = true;
    stopResultPolling();

    updateProgress(100);
    setJobState("Completed");
}

// Mark the job as failed and stop polling.
function failJob(data) {
    completed = true;
    stopResultPolling();

    const firstError = (data.failed_tasks || [])[0];
    const reason = firstError && firstError.error
        ? ` Task ${firstError.task_id}: ${firstError.error}`
        : "";

    setJobState("Failed");
    setJobStatus(`Job failed.${reason}`, "error");
}

// Clean up when leaving the page.
window.addEventListener("beforeunload", () => {
    stopResultPolling();
    workerSource.close();

    if (activeResultUrl) {
        URL.revokeObjectURL(activeResultUrl);
    }
});