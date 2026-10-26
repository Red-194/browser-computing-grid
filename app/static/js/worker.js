const cores = navigator.hardwareConcurrency;
const memory = navigator.deviceMemory ?? 0;
const browser = navigator.userAgent;
const os = navigator.platform;

const HEARTBEAT_INTERVAL = 5000;

const workerUUID = getWorkerUUID();

let heartbeatTimer = null;
let socket = null;

// How many tasks this worker is running right now.
// More than 0 = Busy, 0 = Idle.
let runningTasks = 0;
let idleTimer = null;

const computeWorker = new Worker(
    "/static/js/compute-worker.js",
    { type: "module" }
);

document.getElementById("cores").textContent = cores;
document.getElementById("memory").textContent = memory + " GB";
document.getElementById("uuid").textContent = workerUUID;


/*
 * Compute worker → main worker
 *
 * The compute worker performs the synchronous WASM execution.
 * This thread remains responsible for WebSocket communication
 * and heartbeat handling.
 */
computeWorker.onmessage = (event) => {

    const message = event.data;

    if (message.type === "ready") {

        console.log("Compute worker ready.");
        return;
    }

    if (message.type === "result") {

        const task = message.task;
        const result = message.result;

        console.log("Task result:", result);

        if (socket?.readyState === WebSocket.OPEN) {

            socket.send(JSON.stringify({
                type: "task_result",
                job_id: task.job_id,
                task_id: task.task_id,
                result,
                execution_time_ms: message.execution_time_ms
            }));

        }

        taskFinished();

        return;
    }

    if (message.type === "error") {

        console.error(
            `Task ${message.task_id} failed:`,
            message.error
        );

        taskFinished();

        return;
    }

    if (message.type === "init_error") {

        console.error(
            "WASM runtime initialization failed:",
            message.error
        );

    }

};


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
            cores,
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

        else if (message.type === "ping") {

            sendPong(message.timestamp);

        }

        else if (message.type === "task") {

            console.log(
                "Task received:",
                message.task
            );

            taskStarted();

            /*
             * Do NOT execute WASM here.
             *
             * Send the task to the dedicated compute worker.
             */
            computeWorker.postMessage({

                type: "execute",
                task: message.task

            });

        }

    };


    socket.onclose = () => {

        clearInterval(heartbeatTimer);

        clearTimeout(idleTimer);

        runningTasks = 0;

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
 * isError = true -> red badge, false -> green badge.
 */

function setState(text, isError) {

    const state = document.getElementById("state");

    state.textContent = text;

    state.parentElement.classList.toggle("disconnected", isError);

    // Yellow badge while busy
    state.parentElement.classList.toggle(
        "busy",
        !isError && text.includes("Busy")
    );

}


/*
 * Busy / Idle
 *
 * The page counts its own tasks:
 *   task arrives  -> Busy
 *   all tasks done -> Idle (after a short pause, so a very
 *                     fast task is still visible as Busy)
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