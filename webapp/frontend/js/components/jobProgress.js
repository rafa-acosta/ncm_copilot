import { el, formatDuration } from "../dom.js";
import { api } from "../api.js";

// Polls a background job (webapp/backend/jobs.py) and renders live progress,
// including an elapsed-time indicator ticking every second. `statusEndpoint(jobId)`
// lets each screen point at its own /jobs/{id} route (analysis vs briefings)
// without duplicating this component per screen - see runStatus.js for the
// completed-duration formatting this shares once the job is done.
//
// Elapsed time is derived from the job's own `started_at` timestamp (set
// server-side when the background thread actually begins, see jobs.py) via
// a plain 1s setInterval tick - not from counting polls or frontend state,
// so it survives the polling interval changing and can't drift from when
// work genuinely began.
export function renderJobProgress(container, jobId, statusEndpointBuilder, { onDone, onError } = {}) {
  const track = el("div", { class: "progress-track" }, [el("div", { class: "progress-fill" })]);
  const fill = track.querySelector(".progress-fill");
  const label = el("div", { class: "progress-label" }, [
    el("span", { class: "current-label", text: "Preparing..." }),
    el("span", { class: "count-label", text: "" }),
  ]);
  const elapsedLabel = el("div", { class: "muted", style: "font-size: var(--font-size-xs); margin-top: var(--space-1);" }, [
    el("span", { class: "elapsed-label", text: "" }),
  ]);
  container.appendChild(track);
  container.appendChild(label);
  container.appendChild(elapsedLabel);

  const currentLabelEl = label.querySelector(".current-label");
  const countLabelEl = label.querySelector(".count-label");
  const elapsedEl = elapsedLabel.querySelector(".elapsed-label");

  let cancelled = false;
  let startedAtMs = null;
  let tickHandle = null;

  function tickElapsed() {
    if (startedAtMs === null) return;
    elapsedEl.textContent = `Elapsed: ${formatDuration((Date.now() - startedAtMs) / 1000)}`;
  }

  function stopTicking() {
    if (tickHandle !== null) {
      clearInterval(tickHandle);
      tickHandle = null;
    }
  }

  async function poll() {
    if (cancelled) return;
    let job;
    try {
      job = await api.get(statusEndpointBuilder(jobId));
    } catch (err) {
      stopTicking();
      if (onError) onError(err);
      return;
    }
    const pct = job.total ? Math.round((job.processed / job.total) * 100) : 0;
    fill.style.width = `${pct}%`;
    currentLabelEl.textContent = job.current_label || job.status;
    countLabelEl.textContent = job.total ? `${job.processed} of ${job.total}` : "";

    if (startedAtMs === null && job.started_at) {
      startedAtMs = new Date(job.started_at).getTime();
      tickElapsed();
      tickHandle = setInterval(tickElapsed, 1000);
    }

    if (job.status === "done") {
      stopTicking();
      fill.classList.add("progress-fill--success");
      if (job.started_at && job.finished_at) {
        const durationSeconds = (new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()) / 1000;
        elapsedEl.textContent = `Completed in ${formatDuration(durationSeconds)}`;
      }
      if (onDone) onDone(job.result);
      return;
    }
    if (job.status === "error") {
      stopTicking();
      fill.classList.add("progress-fill--danger");
      if (onError) onError({ detail: job.error, technical: job.error });
      return;
    }
    setTimeout(poll, 800);
  }
  poll();

  return () => {
    cancelled = true;
    stopTicking();
  };
}

// For operations that run synchronously within one request (Dashboard build,
// Compliance Report generation - see dashboard_service.py/reports_service.py,
// both fast enough that this project deliberately doesn't background them
// into jobs.py) - a lightweight elapsed-time ticker around the request itself,
// without the polling machinery renderJobProgress needs for a real background
// job. Timing is authoritative here too (Date.now() at the actual fetch call),
// just not persisted separately - the run manifest's own recorded duration
// (see Overview/Analysis's Recent Runs tables) is still the source of truth
// once the operation completes.
export function renderElapsedIndicator(container, label) {
  const wrap = el("div", { class: "muted", style: "font-size: var(--font-size-sm); margin-top: var(--space-2);" }, [
    el("span", { class: "elapsed-text" }),
  ]);
  container.appendChild(wrap);
  const textEl = wrap.querySelector(".elapsed-text");
  const start = Date.now();
  const tick = () => { textEl.textContent = `${label} Elapsed: ${formatDuration((Date.now() - start) / 1000)}`; };
  tick();
  const handle = setInterval(tick, 1000);
  return {
    stop() {
      clearInterval(handle);
      wrap.remove();
    },
  };
}
