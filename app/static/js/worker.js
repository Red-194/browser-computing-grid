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

const socket = new WebSocket(
    `ws://${window.location.host}/ws`
);

function getWorkerUUID() {

    let uuid = localStorage.getItem("worker-id");
    if (!uuid) {
        uuid = crypto.randomUUID();
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

};

socket.onerror = () => {

    document.getElementById("state").textContent = "Connection Error";

};