// ==========================================
// BROWSER COMPUTING GRID - DASHBOARD
// ==========================================


// ==========================================
// LIVE CONNECTION
// ==========================================

const source = new EventSource("/events");

let currentWorkers = [];


// ==========================================
// GET HTML ELEMENTS
// ==========================================

const totalWorkers =
    document.getElementById("totalWorkers");

const activeWorkers =
    document.getElementById("activeWorkers");

const idleWorkers =
    document.getElementById("idleWorkers");

const averageLatency =
    document.getElementById("averageLatency");

const workerCountLabel =
    document.getElementById("workerCountLabel");

const workersContainer =
    document.getElementById("workersContainer");

const workerTableBody =
    document.getElementById("workerTableBody");

const refreshButton =
    document.getElementById("refreshBtn");


// ==========================================
// RECEIVE LIVE WORKER DATA
// ==========================================

source.onmessage = (event) => {

    const workers = JSON.parse(event.data);

    console.log("Workers received:", workers);

    currentWorkers = workers;

    updateDashboard(workers);

};


// ==========================================
// UPDATE DASHBOARD
// ==========================================

function updateDashboard(workers) {

    // Total workers
    if (totalWorkers) {

        totalWorkers.textContent =
            workers.length;

    }


    // Active workers
    const busyCount =
        workers.filter(
            worker => worker.state === "Busy"
        ).length;


    if (activeWorkers) {

        activeWorkers.textContent =
            busyCount;

    }


    // Idle workers
    const idleCount =
        workers.filter(
            worker => worker.state === "Idle"
        ).length;


    if (idleWorkers) {

        idleWorkers.textContent =
            idleCount;

    }


    // Average latency
    const latencies = workers
        .map(worker => Number(worker.latency))
        .filter(latency => !isNaN(latency));


    if (
        averageLatency &&
        latencies.length > 0
    ) {

        const total =
            latencies.reduce(
                (sum, latency) =>
                    sum + latency,
                0
            );


        const average =
            total / latencies.length;


        averageLatency.textContent =
            Math.round(average) + " ms";

    }

    else if (averageLatency) {

        averageLatency.textContent =
            "--";

    }


    // Worker count
    if (workerCountLabel) {

        workerCountLabel.textContent =
            `${workers.length} workers`;

    }


    renderWorkerCards(workers);

    renderWorkerTable(workers);

}


// ==========================================
// WORKER CARDS
// ==========================================

function renderWorkerCards(workers) {

    if (!workersContainer) {
        return;
    }


    // No workers
    if (workers.length === 0) {

        workersContainer.innerHTML = `

            <div class="empty-state">

                <div>◌</div>

                <h3>
                    No workers connected
                </h3>

                <p>
                    Waiting for browser workers to connect...
                </p>

            </div>

        `;

        return;
    }


    workersContainer.innerHTML = "";


    workers.forEach((worker, index) => {

        const state =
            worker.state || "Offline";


        const stateClass =
            state.toLowerCase();


        const card =
            document.createElement("div");


        card.className =
            "worker-node";


        card.innerHTML = `

            <div class="worker-node-header">

                <span class="worker-name">
                    Worker ${index + 1}
                </span>


                <span class="worker-status ${stateClass}">

                    <span class="status-dot"></span>

                    ${state}

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
                        ${worker.memory ?? "--"} GB
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


        // Click worker
        card.addEventListener(
            "click",
            () => {

                showWorkerDetails(worker);

            }
        );


        workersContainer.appendChild(card);

    });

}


// ==========================================
// WORKER TABLE
// ==========================================

function renderWorkerTable(workers) {

    if (!workerTableBody) {
        return;
    }


    if (workers.length === 0) {

        workerTableBody.innerHTML = `

            <tr>

                <td
                    colspan="7"
                    class="empty-table"
                >

                    No worker data available

                </td>

            </tr>

        `;

        return;
    }


    workerTableBody.innerHTML = "";


    workers.forEach((worker, index) => {

        const state =
            worker.state || "Offline";


        const stateClass =
            state.toLowerCase();


        const row =
            document.createElement("tr");


        row.innerHTML = `

            <td>
                Worker ${index + 1}
            </td>


            <td>

                <span class="worker-status ${stateClass}">

                    <span class="status-dot"></span>

                    ${state}

                </span>

            </td>


            <td>
                ${worker.cores ?? "--"} cores
            </td>


            <td>
                ${worker.memory ?? "--"} GB
            </td>


            <td>
                ${worker.latency ?? "--"} ms
            </td>


            <td>
                ${worker.last_heartbeat ?? "--"}
            </td>


            <td>

                <button
                    class="worker-action-btn"
                    onclick="disconnectWorker('${worker.uuid}')"
                >

                    ${
                        state === "Offline"
                            ? "Remove"
                            : "Disconnect"
                    }

                </button>

            </td>

        `;


        workerTableBody.appendChild(row);

    });

}


// ==========================================
// WORKER DETAILS MODAL
// ==========================================

function showWorkerDetails(worker) {

    // Remove existing modal if one exists
    const oldModal =
        document.getElementById("workerDetailsModal");


    if (oldModal) {
        oldModal.remove();
    }


    // Create modal
    const modal =
        document.createElement("div");


    modal.id =
        "workerDetailsModal";


    modal.style.cssText = `
        position: fixed;
        inset: 0;
        background: rgba(5, 9, 20, 0.75);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
        padding: 20px;
    `;


    const state =
        worker.state || "Offline";


    const stateColor =
        state === "Idle"
            ? "#39d98a"
            : state === "Busy"
                ? "#f5c451"
                : "#ff6678";


    // Modal content
    modal.innerHTML = `

        <div style="
            width: min(520px, 100%);
            background: #151d32;
            border: 1px solid #26314d;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 25px 70px rgba(0,0,0,0.45);
        ">


            <!-- HEADER -->

            <div style="
                padding: 22px 24px;
                border-bottom: 1px solid #26314d;
                display: flex;
                justify-content: space-between;
                align-items: center;
            ">

                <div>

                    <div style="
                        font-size: 19px;
                        font-weight: bold;
                        color: #f5f7ff;
                    ">

                        Worker Details

                    </div>


                    <div style="
                        margin-top: 5px;
                        color: #8e99b5;
                        font-size: 11px;
                    ">

                        Worker node information

                    </div>

                </div>


                <button
                    id="closeWorkerModal"
                    style="
                        width: 34px;
                        height: 34px;
                        border: 1px solid #26314d;
                        border-radius: 8px;
                        background: #1b2540;
                        color: #f5f7ff;
                        font-size: 18px;
                        cursor: pointer;
                    "
                >

                    ×

                </button>

            </div>


            <!-- BODY -->

            <div style="
                padding: 24px;
            ">


                <!-- WORKER NAME + STATUS -->

                <div style="
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 25px;
                ">


                    <div>

                        <div style="
                            color: #f5f7ff;
                            font-size: 17px;
                            font-weight: bold;
                        ">

                            Worker

                        </div>


                        <div style="
                            margin-top: 5px;
                            color: #8e99b5;
                            font-size: 10px;
                        ">

                            ${worker.uuid ?? "--"}

                        </div>

                    </div>


                    <div style="
                        display: flex;
                        align-items: center;
                        gap: 7px;
                        color: ${stateColor};
                        font-size: 11px;
                        font-weight: bold;
                    ">

                        <span style="
                            width: 8px;
                            height: 8px;
                            border-radius: 50%;
                            background: ${stateColor};
                        "></span>

                        ${state}

                    </div>

                </div>



                <!-- INFORMATION GRID -->

                <div style="
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 14px;
                ">


                    <!-- IP -->

                    <div style="
                        background: #1b2540;
                        border: 1px solid #26314d;
                        border-radius: 10px;
                        padding: 15px;
                    ">

                        <div style="
                            color: #8e99b5;
                            font-size: 10px;
                            margin-bottom: 7px;
                        ">

                            IP Address

                        </div>

                        <div style="
                            color: #f5f7ff;
                            font-size: 12px;
                            font-weight: bold;
                        ">

                            ${worker.ip ?? "--"}

                        </div>

                    </div>



                    <!-- CPU -->

                    <div style="
                        background: #1b2540;
                        border: 1px solid #26314d;
                        border-radius: 10px;
                        padding: 15px;
                    ">

                        <div style="
                            color: #8e99b5;
                            font-size: 10px;
                            margin-bottom: 7px;
                        ">

                            CPU Cores

                        </div>

                        <div style="
                            color: #f5f7ff;
                            font-size: 12px;
                            font-weight: bold;
                        ">

                            ${worker.cores ?? "--"} cores

                        </div>

                    </div>



                    <!-- MEMORY -->

                    <div style="
                        background: #1b2540;
                        border: 1px solid #26314d;
                        border-radius: 10px;
                        padding: 15px;
                    ">

                        <div style="
                            color: #8e99b5;
                            font-size: 10px;
                            margin-bottom: 7px;
                        ">

                            Memory

                        </div>

                        <div style="
                            color: #f5f7ff;
                            font-size: 12px;
                            font-weight: bold;
                        ">

                            ${worker.memory ?? "--"} GB

                        </div>

                    </div>



                    <!-- LATENCY -->

                    <div style="
                        background: #1b2540;
                        border: 1px solid #26314d;
                        border-radius: 10px;
                        padding: 15px;
                    ">

                        <div style="
                            color: #8e99b5;
                            font-size: 10px;
                            margin-bottom: 7px;
                        ">

                            Latency

                        </div>

                        <div style="
                            color: #f5f7ff;
                            font-size: 12px;
                            font-weight: bold;
                        ">

                            ${worker.latency ?? "--"} ms

                        </div>

                    </div>



                    <!-- LAST HEARTBEAT -->

                    <div style="
                        background: #1b2540;
                        border: 1px solid #26314d;
                        border-radius: 10px;
                        padding: 15px;
                        grid-column: 1 / -1;
                    ">

                        <div style="
                            color: #8e99b5;
                            font-size: 10px;
                            margin-bottom: 7px;
                        ">

                            Last Heartbeat

                        </div>

                        <div style="
                            color: #f5f7ff;
                            font-size: 12px;
                            font-weight: bold;
                        ">

                            ${worker.last_heartbeat ?? "--"}

                        </div>

                    </div>


                </div>


                <!-- ACTIONS -->

                <div style="
                    display: flex;
                    justify-content: flex-end;
                    gap: 10px;
                    margin-top: 22px;
                ">


                    <button
                        id="modalCloseButton"
                        style="
                            padding: 10px 18px;
                            border: 1px solid #26314d;
                            border-radius: 8px;
                            background: #1b2540;
                            color: #f5f7ff;
                            cursor: pointer;
                        "
                    >

                        Close

                    </button>


                    <button
                        id="modalDisconnectButton"
                        style="
                            padding: 10px 18px;
                            border: none;
                            border-radius: 8px;
                            background: #6c7cff;
                            color: white;
                            cursor: pointer;
                        "
                    >

                        ${
                            state === "Offline"
                                ? "Remove"
                                : "Disconnect"
                        }

                    </button>


                </div>


            </div>

        </div>

    `;


    document.body.appendChild(modal);


    // ======================================
    // CLOSE BUTTONS
    // ======================================

    document
        .getElementById("closeWorkerModal")
        .addEventListener(
            "click",
            () => modal.remove()
        );


    document
        .getElementById("modalCloseButton")
        .addEventListener(
            "click",
            () => modal.remove()
        );


    // ======================================
    // DISCONNECT BUTTON
    // ======================================

    document
        .getElementById("modalDisconnectButton")
        .addEventListener(
            "click",
            async () => {

                await disconnectWorker(
                    worker.uuid
                );

                modal.remove();

            }
        );


    // ======================================
    // CLICK OUTSIDE MODAL
    // ======================================

    modal.addEventListener(
        "click",
        (event) => {

            if (event.target === modal) {

                modal.remove();

            }

        }
    );

}


// ==========================================
// DISCONNECT / REMOVE WORKER
// ==========================================
//
// ORIGINAL BACKEND ENDPOINT — UNCHANGED
// ==========================================

async function disconnectWorker(uuid) {

    try {

        const response =
            await fetch(
                `/disconnect/${uuid}`,
                {
                    method: "POST"
                }
            );


        if (!response.ok) {

            console.log(
                "Disconnect failed"
            );

            return false;

        }


        console.log(
            "Worker disconnected:",
            uuid
        );


        return true;

    }

    catch (error) {

        console.error(
            "Disconnect error:",
            error
        );


        return false;

    }

}


// ==========================================
// REFRESH BUTTON
// ==========================================

if (refreshButton) {

    refreshButton.addEventListener(
        "click",
        () => {

            updateDashboard(
                currentWorkers
            );

        }
    );

}


// ==========================================
// SSE ERROR
// ==========================================

source.onerror = () => {

    console.log(
        "Lost connection to controller."
    );

};