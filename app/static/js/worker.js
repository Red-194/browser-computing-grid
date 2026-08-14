const cores = navigator.hardwareConcurrency;
const memory = navigator.deviceMemory ?? 0;
const browser = navigator.userAgent;
const os = navigator.platform;

const HEARTBEAT_INTERVAL = 5000;

const workerUUID = getWorkerUUID();

let heartbeatTimer = null;

document.getElementById("cores").textContent = cores;
document.getElementById("memory").textContent = memory + " GB";
document.getElementById("uuid").textContent = workerUUID;

let socket = null;

function connect() {
    socket = new WebSocket(
        `ws://${window.location.host}/ws`
    );

    socket.onopen = () => {

        document.getElementById("state").textContent = "Registering...";

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

            document.getElementById("state").textContent =  `Connected • ${message.state}`;

            heartbeatTimer = setInterval(
                sendHeartbeat,
                HEARTBEAT_INTERVAL
            );

        }

        else if (message.type === "ping") {

            sendPong(message.timestamp);

        }

    };

    socket.onclose = () => {

        clearInterval(heartbeatTimer);
        document.getElementById("state").textContent = "Disconnected";

        setTimeout(() => {
            connect();
        }, 3000);

    };

    socket.onerror = () => {

        document.getElementById("state").textContent = "Connection Error";

    };

}

function getWorkerUUID() {

    let uuid = localStorage.getItem("worker-id");
    if (!uuid) {
        if (crypto.randomUUID) {
            uuid = crypto.randomUUID();
        } else {
            // Fallback for non-secure contexts (HTTP) where randomUUID is undefined
            uuid = 'xxxx-xxxx-xxxx-xxxx'.replace(/[x]/g, function(c) {
                const r = Math.random() * 16 | 0;
                return r.toString(16);
            });
        }
        localStorage.setItem("worker-id", uuid);

    }

    return uuid;

}

function sendHeartbeat() {

    if (socket.readyState === WebSocket.OPEN) {

        socket.send(JSON.stringify({
            type: "heartbeat"
        }));

    }

}

function sendPong(timestamp) {

    if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
            type: "pong",
            timestamp
        }));

    }

}

connect();