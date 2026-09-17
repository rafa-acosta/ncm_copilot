import { el } from "../dom.js";
import { api } from "../api.js";

// Polls a background job (webapp/backend/jobs.py) and renders live progress.
// `statusEndpoint(jobId)` lets each screen point at its own /jobs/{id} route
// (analysis vs briefings) without duplicating this component per screen.
export function renderJobProgress(container, jobId, statusEndpointBuilder, { onDone, onError } = {}) {
  const track = el("div", { class: "progress-track" }, [el("div", { class: "progress-fill" })]);
  const fill = track.querySelector(".progress-fill");
  const label = el("div", { class: "progress-label" }, [
    el("span", { class: "current-label", text: "Preparing..." }),
    el("span", { class: "count-label", text: "" }),
  ]);
  container.appendChild(track);
  container.appendChild(label);

  const currentLabelEl = label.querySelector(".current-label");
  const countLabelEl = label.querySelector(".count-label");

  let cancelled = false;
  async function poll() {
    if (cancelled) return;
    let job;
    try {
      job = await api.get(statusEndpointBuilder(jobId));
    } catch (err) {
      if (onError) onError(err);
      return;
    }
    const pct = job.total ? Math.round((job.processed / job.total) * 100) : 0;
    fill.style.width = `${pct}%`;
    currentLabelEl.textContent = job.current_label || job.status;
    countLabelEl.textContent = job.total ? `${job.processed} of ${job.total}` : "";

    if (job.status === "done") {
      fill.classList.add("progress-fill--success");
      if (onDone) onDone(job.result);
      return;
    }
    if (job.status === "error") {
      fill.classList.add("progress-fill--danger");
      if (onError) onError({ detail: job.error, technical: job.error });
      return;
    }
    setTimeout(poll, 800);
  }
  poll();

  return () => {
    cancelled = true;
  };
}
