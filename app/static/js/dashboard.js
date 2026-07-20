const table = document.getElementById("workerTable");

const source = new EventSource("/events");

source.onmessage = (event) => {

    const workers = JSON.parse(event.data);

    table.innerHTML = "";

    if (workers.length === 0) {

        table.innerHTML = `
            <tr>
                <td colspan="5">No workers connected.</td>
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
            </tr>
        `;

    });

};

source.onerror = () => {

    console.log("Lost connection to controller.");

};