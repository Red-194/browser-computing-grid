import init, { execute_task } from "/runtime/runtime.js";

let wasmReady = false;

async function initializeWasm() {

    await init();
    wasmReady = true;

    self.postMessage({
        type: "ready"
    });

    console.log("WASM runtime initialized.");
}

self.onmessage = async (event) => {

    const message = event.data;

    if (message.type !== "execute") {
        return;
    }

    if (!wasmReady) {
        self.postMessage({
            type: "error",
            task_id: message.task.task_id,
            error: "WASM runtime is not ready."
        });

        return;
    }

    const task = message.task;

    try {
        const startTime = performance.now();
        const result = execute_task(
            task.workload,
            task.config
        );

        const executionTime =
            performance.now() - startTime;

        self.postMessage({
            type: "result",
            task: task,
            result: result,
            execution_time_ms: executionTime
        });

    } catch (error) {

        self.postMessage({
            type: "error",
            task_id: task.task_id,
            error: String(error)
        });

    }

};

initializeWasm().catch((error) => {

    self.postMessage({
        type: "init_error",
        error: String(error)
    });

});