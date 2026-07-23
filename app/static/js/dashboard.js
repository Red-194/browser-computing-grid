const table = document.getElementById("workerTable");

const source = new EventSource("/events");

source.onmessage = (event) => {

    const workers = JSON.parse(event.data);

    table.innerHTML = "";

    if (workers.length === 0) {

        table.innerHTML = `
            <tr>
                <td colspan="6">No workers connected.</td>
            </tr>
        `;

        return;

    }

    workers.forEach(worker => {

        table.innerHTML += `
            <tr>
                <td>${worker.uuid}</td>
                <td>${worker.ip}</td>
                <td>${worker.status}</td>
                <td>${worker.cores}</td>
                <td>${worker.memory}</td>
                <td>${worker.latency} ms</td>
                <td>
                    <button onclick="disconnectWorker('${worker.uuid}')">
                        Disconnect
                    </button>
                </td>
            </tr>
        `;

    });

};

source.onerror = () => {

    console.log("Lost connection to controller.");

};

async function disconnectWorker(uuid) {

    const response = await fetch(`/disconnect/${uuid}`, {
        method: "POST"
    });

    if (!response.ok) {
        console.log("Disconnect failed");
    }

}