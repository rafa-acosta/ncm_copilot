// Minimal cross-page UI state - which run/profile is "active" while you move
// between screens. The backend (not this store) remains the source of truth
// for everything else; each page re-fetches its own data on render. Persisted
// to localStorage only as a per-browser convenience (remembering your last
// selection), never as the record of truth - see artifact/browser-storage
// guidance this project already follows for the same reason.

const STORAGE_KEY = "ncm-copilot-ui-state";

function loadPersisted() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function persist(state) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* private browsing / storage disabled - fine, just an ergonomic loss */
  }
}

const state = {
  activeGoldenProfileId: null,
  activeRunId: null,
  ...loadPersisted(),
};

const listeners = new Set();

export function getState() {
  return state;
}

export function setState(patch) {
  Object.assign(state, patch);
  persist({ activeGoldenProfileId: state.activeGoldenProfileId, activeRunId: state.activeRunId });
  listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
