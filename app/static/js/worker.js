

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

        document.getElementById("uuid").textContent = message.uuid;
        
        document.getElementById("status").textContent = "Connected • Idle";

        heartbeatTimer = setInterval(sendHeartbeat, HEARTBEAT_INTERVAL);

    }

};

socket.onclose = () => {
    
    clearInterval(heartbeatTimer);
    document.getElementById("status").textContent = "Disconnected";

};

socket.onerror = () => {

    document.getElementById("status").textContent = "Connection Error";

};