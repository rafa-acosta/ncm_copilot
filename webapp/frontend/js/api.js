// Thin fetch wrapper for the backend API. Every non-2xx response is turned
// into an ApiError carrying both the friendly `detail` message and the
// `technical` string the backend's exception handlers attach (see
// webapp/backend/app.py) - callers show `detail` by default and put
// `technical` behind an expandable "Technical details" section.

export class ApiError extends Error {
  constructor(status, detail, technical) {
    super(detail);
    this.status = status;
    this.detail = detail;
    this.technical = technical;
  }
}

async function request(method, path, { json, formData } = {}) {
  const init = { method, headers: {} };
  if (json !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(json);
  } else if (formData !== undefined) {
    init.body = formData; // browser sets multipart boundary itself
  }

  let response;
  try {
    response = await fetch(path, init);
  } catch (networkErr) {
    throw new ApiError(0, "Backend unavailable - unable to reach the server.", String(networkErr));
  }

  const isJson = (response.headers.get("content-type") || "").includes("application/json");
  const body = isJson ? await response.json().catch(() => null) : null;

  if (!response.ok) {
    const detail = (body && body.detail) || `Request failed (${response.status}).`;
    const technical = (body && body.technical) || `${method} ${path} -> HTTP ${response.status}`;
    throw new ApiError(response.status, detail, technical);
  }
  return body;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, json) => request("POST", path, { json }),
  put: (path, json) => request("PUT", path, { json }),
  del: (path, json) => request("DELETE", path, { json }),
  upload: (path, files) => {
    const formData = new FormData();
    for (const file of files) formData.append("files", file, file.name);
    return request("POST", path, { formData });
  },
};
