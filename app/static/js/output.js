"use strict";

const params = new URLSearchParams(window.location.search);
const jobId = params.get("job_id");
const workload = params.get("workload");
const names = { mandelbrot: "Mandelbrot", raytracing: "3D Ray Tracing" };
const title = document.getElementById("title");
const status = document.getElementById("status");
const progress = document.getElementById("progress");
const placeholder = document.getElementById("placeholder");
const image = document.getElementById("renderedImage");

let activeImageUrl = null;
let stopped = false;

if (!jobId) {
    status.textContent = "Waiting for the job to be submitted…";
    progress.textContent = "Preparing";
} else if (!names[workload]) {
    status.textContent = "This output type is not supported in the live viewer.";
    progress.textContent = "Unavailable";
} else {
    title.textContent = `${names[workload]} · Live output`;
    status.textContent = "Waiting for the first rendered tiles…";
    pollOutput();
}

async function pollOutput() {
    if (stopped || !jobId || !names[workload]) return;

    try {
        const jobResponse = await fetch(`/jobs/${encodeURIComponent(jobId)}`, {
            cache: "no-store"
        });
        if (jobResponse.status === 404) {
            stopped = true;
            status.textContent = "Job not found. The controller may have restarted.";
            progress.textContent = "Unavailable";
            return;
        }
        if (!jobResponse.ok) throw new Error("Could not read job status.");

        const job = await jobResponse.json();
        const counts = job.progress || {};
        const total = Number(counts.total || 0);
        const done = Number(counts.done || 0);
        const percent = total ? Math.round((done / total) * 100) : 0;
        progress.textContent = `${done.toLocaleString()} / ${total.toLocaleString()} tiles · ${percent}%`;

        const previewResponse = await fetch(
            `/jobs/${encodeURIComponent(jobId)}/preview`,
            { cache: "no-store" }
        );
        if (previewResponse.ok && previewResponse.headers.get("content-type")?.includes("image/")) {
            const blob = await previewResponse.blob();
            if (!stopped) {
                if (activeImageUrl) URL.revokeObjectURL(activeImageUrl);
                activeImageUrl = URL.createObjectURL(blob);
                image.src = activeImageUrl;
                image.classList.add("visible");
                placeholder.hidden = true;
            }
        }

        if (job.status === "done") {
            stopped = true;
            status.textContent = "Render complete.";
            progress.textContent = `${total.toLocaleString()} / ${total.toLocaleString()} tiles · 100%`;
            return;
        }
        if (job.status === "failed") {
            stopped = true;
            status.textContent = "Render failed. See the Jobs page for details.";
            return;
        }
        status.textContent = image.classList.contains("visible")
            ? "Live render updating as workers finish tiles."
            : "Waiting for the first rendered tiles…";
    } catch (error) {
        console.error("Live output refresh failed:", error);
        status.textContent = "Connection interrupted. Retrying…";
    }

    if (!stopped) window.setTimeout(pollOutput, 1000);
}

window.addEventListener("beforeunload", () => {
    stopped = true;
    if (activeImageUrl) URL.revokeObjectURL(activeImageUrl);
});
