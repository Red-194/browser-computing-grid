const cores = navigator.hardwareConcurrency;
const memory = navigator.deviceMemory ?? 0;
const browser = navigator.userAgent;
const os = navigator.platform;

const HEARTBEAT_INTERVAL = 5000;

const workerUUID = getWorkerUUID();

let heartbeatTimer = null;
let socket = null;
let allowReconnect = true; // the controller can turn this off (POST /disconnect/{uuid})

// Tasks this tab holds right now (queued or running). More than 0 = Busy, 0 = Idle.
let runningTasks = 0;
let idleTimer = null;

/*
 * Compute worker pool
 *
 * One compute worker is one WASM thread, so a tab with several cores needs
 * several of them to use those cores. Tasks wait in `taskQueue` here and go to
 * whichever compute worker is free. The size defaults to cores - 1 (the main
 * thread keeps the WebSocket and heartbeat alive), at most MAX_THREADS, and can
 * be set with ?threads=N in the page address.
 */
const MAX_THREADS = 8;
const requestedThreads = parseInt(
    new URLSearchParams(window.location.search).get("threads"), 10
);
const poolSize = Math.max(1, Math.min(
    requestedThreads > 0 ? requestedThreads : (cores || 1) - 1,
    MAX_THREADS
));

const pool = [];
const taskQueue = [];

/*
 * Results are sent in batches: finished results wait up to RESULT_FLUSH_MS and
 * go out in one message. For tiny tasks this replaces thousands of messages with
 * a few hundred; for long tasks the delay is not noticeable.
 */
const RESULT_FLUSH_MS = 10;
const resultBuffer = [];
let flushTimer = null;

function flushResults() {

    flushTimer = null;

    if (resultBuffer.length === 0) {
        return;
    }

    // Pixel results are large JSON arrays. Batching several finished image
    // tiles can exceed Uvicorn's default 16 MiB WebSocket frame limit.
    // Flush image tiles individually; keep batching compact workload results.
    const imageIndex = resultBuffer.findIndex(
        item => item.workload === "raytracing" || item.workload === "mandelbrot"
    );
    const results = imageIndex >= 0
        ? resultBuffer.splice(imageIndex, 1)
        : resultBuffer.splice(0, resultBuffer.length);

    if (socket?.readyState === WebSocket.OPEN) {

        socket.send(JSON.stringify({
            type: "task_results",
            results
        }));

    }

    if (resultBuffer.length > 0 && flushTimer === null) {
        flushTimer = setTimeout(flushResults, RESULT_FLUSH_MS);
    }

}

document.getElementById("cores").textContent =
    `${cores} (${poolSize} compute thread${poolSize === 1 ? "" : "s"})`;
document.getElementById("memory").textContent = memory + " GB";
document.getElementById("uuid").textContent = workerUUID;


function startComputeWorker() {

    const entry = {
        worker: new Worker(
            "/static/js/compute-worker.js?v=raytracing-20261027-3",
            { type: "module" }
        ),
        ready: false,
        busy: false
    };

    /*
     * Compute worker → main thread
     *
     * The compute worker performs the synchronous WASM execution.
     * This thread remains responsible for WebSocket communication
     * and heartbeat handling.
     */
    entry.worker.onmessage = (event) => {

        const message = event.data;

        if (message.type === "ready") {

            entry.ready = true;
            pump();
            return;
        }

        if (message.type === "result") {

            const task = message.task;

            entry.busy = false;
            taskFinished();

            resultBuffer.push({
                workload: task.workload,
                job_id: task.job_id,
                task_id: task.task_id,
                attempt: task.attempt,
                result: message.result,
                execution_time_ms: message.execution_time_ms
            });

            if (flushTimer === null) {
                flushTimer = setTimeout(flushResults, RESULT_FLUSH_MS);
            }

            pump();
            return;
        }

        if (message.type === "error") {

            console.error(
                `Task ${message.task_id} failed:`,
                message.error
            );

            entry.busy = false;
            taskFinished();

            // Tell the controller, or it waits for a timeout to notice.
            if (message.task && socket?.readyState === WebSocket.OPEN) {

                socket.send(JSON.stringify({
                    type: "task_error",
                    job_id: message.task.job_id,
                    task_id: message.task.task_id,
                    attempt: message.task.attempt,
                    error: message.error
                }));

            }

            pump();
            return;
        }

        if (message.type === "init_error") {

            console.error(
                "WASM runtime initialization failed:",
                message.error
            );

        }

    };

    pool.push(entry);
}


/* Hand waiting tasks to every compute worker that is free. */
function pump() {

    for (const entry of pool) {

        if (taskQueue.length === 0) {
            return;
        }

        if (entry.ready && !entry.busy) {

            entry.busy = true;
            entry.worker.postMessage({
                type: "execute",
                task: taskQueue.shift()
            });

        }

    }

}


for (let i = 0; i < poolSize; i++) {
    startComputeWorker();
}


/*
 * Controller WebSocket
 */

function connect() {

    socket = new WebSocket(
        `ws://${window.location.host}/ws`
    );

    socket.onopen = () => {

        setState("Registering...", false);

        socket.send(JSON.stringify({

            type: "register",
            uuid: workerUUID,
            cores: poolSize, // what this tab can run at once (see the pool above)
            memory,
            os,
            browser

        }));

    };


    socket.onmessage = (event) => {

        const message = JSON.parse(event.data);

        if (message.type === "register_ack") {

            runningTasks = 0;

            setState(`Connected • ${message.state}`, false);

            clearInterval(heartbeatTimer);

            heartbeatTimer = setInterval(
                sendHeartbeat,
                HEARTBEAT_INTERVAL
            );

        }

        else if (message.type === "disconnect") {

            allowReconnect = message.reconnect !== false;

        }

        else if (message.type === "ping") {

            sendPong(message.timestamp);

        }

        else if (message.type === "task") {

            /*
             * Do NOT execute WASM here.
             *
             * Queue the task for the compute worker pool.
             */
            taskStarted();
            taskQueue.push(message.task);
            pump();

        }

        else if (message.type === "tasks") {

            for (const task of message.tasks) {
                taskStarted();
                taskQueue.push(task);
            }
            pump();

        }

    };


    socket.onclose = () => {

        clearInterval(heartbeatTimer);

        // Tasks still waiting here belonged to the old session; the controller
        // has already taken them back.
        taskQueue.length = 0;
        resultBuffer.length = 0;

        clearTimeout(idleTimer);
        runningTasks = 0;

        if (!allowReconnect) {

            setState("Disconnected by controller (reload to reconnect)", true);
            return;

        }

        setState("Disconnected", true);

        setTimeout(() => {
            connect();
        }, 3000);

    };


    socket.onerror = () => {

        setState("Connection Error", true);

    };

}


/*
 * Show the worker state.
 * isError = true -> red badge, false -> green badge, yellow while busy.
 */

function setState(text, isError) {

    const state = document.getElementById("state");

    state.textContent = text;

    state.parentElement.classList.toggle("disconnected", isError);

    state.parentElement.classList.toggle(
        "busy",
        !isError && text.includes("Busy")
    );

}


/*
 * Busy / Idle
 *
 *   task arrives   -> Busy
 *   all tasks done -> Idle, after a short pause so a very fast task
 *                     is still visible as Busy
 */

function taskStarted() {

    runningTasks++;

    clearTimeout(idleTimer);

    setState("Connected • Busy", false);

}


function taskFinished() {

    runningTasks = Math.max(0, runningTasks - 1);

    if (runningTasks > 0) {
        return;
    }

    clearTimeout(idleTimer);

    idleTimer = setTimeout(() => {

        if (
            runningTasks === 0 &&
            socket?.readyState === WebSocket.OPEN
        ) {
            setState("Connected • Idle", false);
        }

    }, 1000);

}


/*
 * Persistent worker UUID
 */

function getWorkerUUID() {

    let uuid = localStorage.getItem("worker-id");

    if (!uuid) {

        if (crypto.randomUUID) {

            uuid = crypto.randomUUID();

        } else {

            // Fallback for non-secure contexts
            // where randomUUID is unavailable.

            uuid =
                "xxxx-xxxx-xxxx-xxxx".replace(
                    /[x]/g,
                    function(c) {
                        const r =
                            Math.random() * 16 | 0;

                        return r.toString(16);
                    }
                );
        }

        localStorage.setItem(
            "worker-id",
            uuid
        );

    }

    return uuid;

}


/*
 * Heartbeat
 */

function sendHeartbeat() {

    if (
        socket &&
        socket.readyState === WebSocket.OPEN
    ) {

        socket.send(JSON.stringify({
            type: "heartbeat"
        }));

    }

}


/*
 * Pong
 */

function sendPong(timestamp) {

    if (
        socket &&
        socket.readyState === WebSocket.OPEN
    ) {

        socket.send(JSON.stringify({
            type: "pong",
            timestamp
        }));

    }

}


connect();
