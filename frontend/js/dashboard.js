// ===============================
// COMPUTE GRID DASHBOARD
// ===============================

let workers = {};


// ===============================
// UPDATE DASHBOARD
// ===============================

function updateDashboard() {

    const workerList = Object.values(workers);

    // -------------------------------
    // Total workers
    // -------------------------------

    document.getElementById("totalWorkers").textContent =
        workerList.length;


    // -------------------------------
    // Active workers
    // -------------------------------

    const activeWorkers = workerList.filter(
        worker =>
            String(worker.state || "").toLowerCase() === "busy"
    );

    document.getElementById("activeWorkers").textContent =
        activeWorkers.length;


    // -------------------------------
    // Idle workers
    // -------------------------------

    const idleWorkers = workerList.filter(
        worker =>
            String(worker.state || "").toLowerCase() === "idle"
    );

    document.getElementById("idleWorkers").textContent =
        idleWorkers.length;


    // -------------------------------
    // Average latency
    // -------------------------------

    const latencies = workerList
        .map(worker => Number(worker.latency))
        .filter(latency => !isNaN(latency));


    if (latencies.length > 0) {

        const totalLatency =
            latencies.reduce(
                (sum, latency) => sum + latency,
                0
            );

        const averageLatency =
            totalLatency / latencies.length;

        document.getElementById("averageLatency").textContent =
            Math.round(averageLatency) + " ms";

    } else {

        document.getElementById("averageLatency").textContent =
            "--";
    }


    // -------------------------------
    // Worker count
    // -------------------------------

    document.getElementById("workerCountLabel").textContent =
        `${workerList.length} workers`;


    // -------------------------------
    // Render UI
    // -------------------------------

    renderWorkers();

    renderTable();
}


// ===============================
// RENDER WORKER CARDS
// ===============================

function renderWorkers() {

    const container =
        document.getElementById("workersContainer");

    const workerList =
        Object.values(workers);


    // -------------------------------
    // No workers
    // -------------------------------

    if (workerList.length === 0) {

        container.innerHTML = `
            <div class="empty-state">

                <div>◌</div>

                <h3>No workers connected</h3>

                <p>
                    Waiting for browser workers to connect...
                </p>

            </div>
        `;

        return;
    }


    // Clear old cards

    container.innerHTML = "";


    // -------------------------------
    // Create worker cards
    // -------------------------------

    workerList.forEach((worker, index) => {

        const state =
            String(worker.state || "Offline")
                .toLowerCase();


        const card =
            document.createElement("div");

        card.className = "worker-node";


        card.innerHTML = `

            <div class="worker-node-header">

                <span class="worker-name">
                    Worker ${index + 1}
                </span>

                <span class="worker-status ${state}">

                    <span class="status-dot"></span>

                    ${worker.state || "Offline"}

                </span>

            </div>


            <div class="worker-details">

                <div class="worker-detail">

                    <span>CPU</span>

                    <strong>
                        ${worker.cores ?? "--"} cores
                    </strong>

                </div>


                <div class="worker-detail">

                    <span>Memory</span>

                    <strong>
                        ${worker.memory ?? "--"}
                    </strong>

                </div>


                <div class="worker-detail">

                    <span>Latency</span>

                    <strong>
                        ${worker.latency ?? "--"} ms
                    </strong>

                </div>


                <div class="worker-detail">

                    <span>IP</span>

                    <strong>
                        ${worker.ip ?? "--"}
                    </strong>

                </div>

            </div>
        `;


        container.appendChild(card);

    });
}


// ===============================
// RENDER WORKER TABLE
// ===============================

function renderTable() {

    const tableBody =
        document.getElementById("workerTableBody");

    const workerList =
        Object.values(workers);


    // -------------------------------
    // No workers
    // -------------------------------

    if (workerList.length === 0) {

        tableBody.innerHTML = `
            <tr>

                <td
                    colspan="6"
                    class="empty-table"
                >
                    No worker data available
                </td>

            </tr>
        `;

        return;
    }


    // Clear old rows

    tableBody.innerHTML = "";


    // -------------------------------
    // Create table rows
    // -------------------------------

    workerList.forEach((worker, index) => {

        const state =
            String(worker.state || "Offline")
                .toLowerCase();


        const row =
            document.createElement("tr");


        row.innerHTML = `

            <td>
                Worker ${index + 1}
            </td>


            <td>

                <span class="worker-status ${state}">

                    <span class="status-dot"></span>

                    ${worker.state || "Offline"}

                </span>

            </td>


            <td>
                ${worker.cores ?? "--"} cores
            </td>


            <td>
                ${worker.memory ?? "--"}
            </td>


            <td>
                ${worker.latency ?? "--"} ms
            </td>


            <td>
                ${worker.last_heartbeat ?? "--"}
            </td>

        `;


        tableBody.appendChild(row);

    });
}


// ===============================
// SERVER-SENT EVENTS
// ===============================

function connectToEvents() {

    const eventSource =
        new EventSource("/events");


    // -------------------------------
    // Receive worker updates
    // -------------------------------

    eventSource.onmessage =
        function(event) {

            try {

                const data =
                    JSON.parse(event.data);


                console.log(
                    "Worker update:",
                    data
                );


                /*
                 * IMPORTANT:
                 *
                 * The existing backend sends
                 * the COMPLETE worker list.
                 *
                 * Example:
                 *
                 * [
                 *   {
                 *      uuid: "...",
                 *      ip: "...",
                 *      state: "Idle",
                 *      cores: 8,
                 *      memory: 16,
                 *      latency: 42
                 *   }
                 * ]
                 *
                 */


                if (Array.isArray(data)) {

                    // Clear old worker data

                    workers = {};


                    // Add current workers

                    data.forEach(worker => {

                        if (worker.uuid) {

                            workers[worker.uuid] =
                                worker;

                        }

                    });

                }


                // Update UI

                updateDashboard();

            }

            catch (error) {

                console.error(
                    "Could not process worker update:",
                    error
                );

            }

        };


    // -------------------------------
    // SSE connection error
    // -------------------------------

    eventSource.onerror =
        function(error) {

            console.error(
                "SSE connection error:",
                error
            );

        };

}


// ===============================
// REFRESH BUTTON
// ===============================

document
    .getElementById("refreshBtn")
    .addEventListener(
        "click",
        function() {

            updateDashboard();

        }
    );


// ===============================
// INITIALIZE DASHBOARD
// ===============================

updateDashboard();

connectToEvents();