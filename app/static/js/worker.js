

const cores = navigator.hardwareConcurrency;
const memory = navigator.deviceMemory ?? 0;
const HEARTBEAT_INTERVAL = 5000;

let heartbeatTimer = null;

document.getElementById("cores").textContent = cores;
document.getElementById("memory").textContent = memory + " GB";

const socket = new WebSocket(
    `ws://${window.location.host}/ws`
);

function sendHeartbeat() {

    if (socket.readyState === WebSocket.OPEN) {

        socket.send(JSON.stringify({
            type: "heartbeat"
        }));

    }

}

function sendPong(timestamp) {

    socket.send(JSON.stringify({

        type: "pong",

        timestamp

    }));

}

socket.onopen = () => {

    document.getElementById("status").textContent = "Registering...";

    socket.send(JSON.stringify({

        type: "register",
        cores,
        memory

    }));

};

socket.onmessage = (event) => {

    const message = JSON.parse(event.data);

    if (message.type === "register_ack") {

        document.getElementById("status").textContent = "Connected • Idle";

        setInterval(sendHeartbeat, HEARTBEAT_INTERVAL);

    }

    else if (message.type === "ping") {

        sendPong(message.timestamp);

    }

};

socket.onclose = () => {
    
    clearInterval(heartbeatTimer);
    document.getElementById("status").textContent = "Disconnected";

};

socket.onerror = () => {

    document.getElementById("status").textContent = "Connection Error";

};