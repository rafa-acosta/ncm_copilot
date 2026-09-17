// Hash-based router - no build step, no history-API server fallback needed
// (see webapp/backend/app.py's note on why). Each page module exports a
// single `render(container)` function; the router owns swapping it in and
// keeping the sidebar's active-link state in sync.

const routes = new Map();
let mainContainer = null;
let navLinks = null;
let currentCleanup = null;

export function registerRoute(hash, pageModule) {
  routes.set(hash, pageModule);
}

export function initRouter(container, sidebarNavEl) {
  mainContainer = container;
  navLinks = sidebarNavEl.querySelectorAll(".nav-link");
  window.addEventListener("hashchange", renderCurrentRoute);
  renderCurrentRoute();
}

function currentHash() {
  return window.location.hash.replace(/^#/, "") || "/overview";
}

async function renderCurrentRoute() {
  const hash = currentHash();
  const page = routes.get(hash) || routes.get("/overview");

  navLinks.forEach((link) => {
    link.classList.toggle("is-active", link.getAttribute("href") === `#${hash}`);
  });

  if (typeof currentCleanup === "function") {
    try {
      currentCleanup();
    } catch {
      /* a page's own cleanup failing must not block navigating away from it */
    }
    currentCleanup = null;
  }

  mainContainer.setAttribute("aria-busy", "true");
  try {
    currentCleanup = await page.render(mainContainer);
  } finally {
    mainContainer.setAttribute("aria-busy", "false");
  }
}

export function navigateTo(hash) {
  window.location.hash = hash;
}
