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
    // Only count workers that have a real measured latency
    // (offline workers and not-yet-measured workers have 0).
    const latencies = workers
        .map(worker => Number(worker.latency))
        .filter(latency => !isNaN(latency) && latency > 0);


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


    // OLD VIEW (one card per worker with all details).
    // To use it again: uncomment the line below, uncomment
    // renderWorkerCards() further down, and comment renderWorkerTree().
    // renderWorkerCards(workers);

    renderWorkerTree(workers);

    renderWorkerTable(workers);

}


// ==========================================
// SMALL HELPERS
// ==========================================

// Latency text. 0 means "not measured yet" or "offline".
function formatLatency(worker) {

    const latency = Number(worker.latency);

    if (worker.state === "Offline" || !latency) {
        return "--";
    }

    return latency + " ms";

}


// Memory text. Some browsers (Firefox, Safari) do not share
// device memory, so the worker sends 0.
function formatMemory(worker) {

    if (!worker.memory) {
        return "--";
    }

    return worker.memory + " GB";

}


// Cores text.
function formatCores(worker) {

    if (!worker.cores) {
        return "--";
    }

    return worker.cores + " cores";

}


// ==========================================
// WORKER TREE (NEW VIEW)
// ==========================================
//
// Controller is the root. Workers are split into
// a few branches (columns). Each branch is a vertical
// line with workers hanging off it like leaves:
//
//              [ Controller ]
//                    |
//       +------------+------------+
//       |            |            |
//       +- Worker 1  +- Worker 2  +- Worker 3
//       +- Worker 4  +- Worker 5  +- Worker 6
//
// Each box only shows "Worker N". Click a box to see
// its details in a popup. The lines are drawn by
// drawWorkerTree() in dashboard.html.

// Width given to one branch column (px).
const BRANCH_WIDTH = 170;

// Number of branches used in the last render.
let lastBranchCount = 0;


function getBranchCount(workerCount) {

    const width =
        workersContainer.clientWidth || 800;

    const fit =
        Math.max(1, Math.floor(width / BRANCH_WIDTH));

    return Math.min(fit, workerCount);

}


function renderWorkerTree(workers) {

    if (!workersContainer) {
        return;
    }


    // No workers
    if (workers.length === 0) {

        workersContainer.className =
            "workers-container";

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

        lastBranchCount = 0;

        return;
    }


    const branchCount =
        getBranchCount(workers.length);

    lastBranchCount = branchCount;


    workersContainer.className =
        "workers-container worker-tree";

    workersContainer.innerHTML = "";


    // Make the empty branches
    const branches = [];

    for (let i = 0; i < branchCount; i++) {

        const branch =
            document.createElement("div");

        branch.className = "worker-branch";

        workersContainer.appendChild(branch);

        branches.push(branch);

    }


    // Put the workers into branches one by one
    // (Worker 1 -> branch 1, Worker 2 -> branch 2, ...)
    workers.forEach((worker, index) => {

        const state =
            worker.state || "Offline";

        const leaf =
            document.createElement("div");

        leaf.className =
            "worker-leaf " + state.toLowerCase();

        leaf.title = state;

        leaf.innerHTML = `
            <span class="status-dot"></span>
            Worker ${index + 1}
        `;

        leaf.addEventListener(
            "click",
            () => {

                showWorkerDetails(worker, index + 1);

            }
        );

        branches[index % branchCount].appendChild(leaf);

    });

}


// Re-draw the tree when the window size changes
// enough to fit a different number of branches.
window.addEventListener(
    "resize",
    () => {

        if (
            currentWorkers.length > 0 &&
            getBranchCount(currentWorkers.length) !== lastBranchCount
        ) {

            renderWorkerTree(currentWorkers);

        }

    }
);


// ==========================================
// WORKER CARDS (OLD VIEW - COMMENTED OUT)
// ==========================================
//
// To use the old card view again, remove the "/*" below
// and the "*/" at the end of this function.

/*
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


    // Remove the tree style added by renderWorkerTree()
    workersContainer.className =
        "workers-container";

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
*/
// ===== END OF OLD CARD VIEW =====


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
                    colspan="6"
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
                ${formatCores(worker)}
            </td>


            <td>
                ${formatMemory(worker)}
            </td>


            <td>
                ${worker.ip || "--"}
            </td>


            <td>
                ${formatLatency(worker)}
            </td>

        `;


        // OLD COLUMNS (commented out)
        //
        // These were shown in the wrong columns: latency appeared
        // under "IP Address" and heartbeat under "Latency".
        // The backend does not send last_heartbeat, so it was
        // always "--".
        //
        // <td>
        //     ${worker.last_heartbeat ?? "--"}
        // </td>
        //
        // DISCONNECT BUTTON (commented out)
        // The worker page reconnects by itself after 3 seconds,
        // so this button has no lasting effect. To use it again,
        // add this cell back to row.innerHTML above, and add an
        // "Action" <th> in dashboard.html:
        //
        // <td>
        //     <button
        //         class="worker-action-btn"
        //         onclick="disconnectWorker('${worker.uuid}')"
        //     >
        //         ${state === "Offline" ? "Remove" : "Disconnect"}
        //     </button>
        // </td>


        workerTableBody.appendChild(row);

    });

}


// ==========================================
// WORKER DETAILS MODAL
// ==========================================

// number = the worker's number in the tree (Worker 1, Worker 2, ...)
function showWorkerDetails(worker, number) {

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

                            Worker ${number ?? ""}

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

                            ${worker.ip || "--"}

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

                            ${formatCores(worker)}

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

                            ${formatMemory(worker)}

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

                            ${formatLatency(worker)}

                        </div>

                    </div>



                    <!-- LAST HEARTBEAT (commented out: the backend
                         does not send it, so it was always "--")

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

                    END OF LAST HEARTBEAT -->


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


                    <!-- DISCONNECT BUTTON (commented out: the worker
                         reconnects by itself, so it has no lasting effect)

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

                    END OF DISCONNECT BUTTON -->


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
    // DISCONNECT BUTTON (commented out)
    // Uncomment together with the button above.
    // ======================================

    // document
    //     .getElementById("modalDisconnectButton")
    //     .addEventListener(
    //         "click",
    //         async () => {
    //
    //             await disconnectWorker(
    //                 worker.uuid
    //             );
    //
    //             modal.remove();
    //
    //         }
    //     );


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
                // The worker stays disconnected until its page is reloaded.
                // (?reconnect=true would make the tab reconnect after a few seconds.)
                `/disconnect/${uuid}?reconnect=false`,
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