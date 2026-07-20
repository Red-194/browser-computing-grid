async function updateWorkers() {

    try {

        const response = await fetch("/workers");

        const workers = await response.json();

        const table = document.getElementById("workerTable");

        table.innerHTML = "";

        if (workers.length === 0) {

            table.innerHTML = `
                <tr>
                    <td colspan="5">
                        No workers connected.
                    </td>
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

    }

    catch (error) {

        console.error("Failed to fetch workers:", error);

    }

}

updateWorkers();

setInterval(updateWorkers, 1000);