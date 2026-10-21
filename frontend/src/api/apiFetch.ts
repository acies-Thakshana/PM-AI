import { authEnabled, getAccessToken } from "../auth/msal";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function send(path: string, init: RequestInit | undefined, forceRefresh: boolean): Promise<Response> {
  const url = path.startsWith("/") ? `${API_BASE_URL}${path}` : path;
  const token = await getAccessToken(forceRefresh);
  if (!token) return fetch(url, init);
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(url, { ...init, headers });
}

// --- Long steps run as background jobs --------------------------------------------------------
// A gateway or load balancer drops a request that waits ~30 seconds, but these steps (the AI
// planning, computing features, running an analysis, building a report) can take longer. They are
// started with `X-Run-As-Job: 1`: the backend answers at once with a job id, the work continues
// there, and we ask "is it done?" every couple of seconds. The finished job hands back the
// endpoint's own response (same status, headers and body), so callers cannot tell the difference.
const LONG_STEPS: { method: string; path: RegExp }[] = [
  { method: "POST", path: /^\/api\/planner\/suggest$/ },
  // One assistant turn can take several model calls (it may look things up before it answers).
  { method: "POST", path: /^\/api\/chat\/turn$/ },
  // Pulling trips from the SWP API is rate limited (a couple of seconds per call), so it can take a while.
  { method: "GET", path: /^\/api\/swp\/trips$/ },
  { method: "POST", path: /^\/api\/swp\/load$/ },
  { method: "POST", path: /^\/api\/audit\/[^/]+\/(run|features)$/ },
  { method: "POST", path: /^\/api\/(features|analysis)\/repository\/[^/]+\/(draft|suggest)$/ },
  {
    method: "POST",
    path: /^\/api\/analysis\/repository\/[^/]+\/entries\/[^/]+\/(run|drilldown|drilldown\/rank|drilldown\/refresh|drilldown\/propose|paths\/suggest)$/,
  },
  { method: "GET", path: /^\/api\/analysis\/[^/]+\/overall$/ },
  { method: "GET", path: /^\/api\/report\/[^/]+\/(summary|translations|download)$/ },
  { method: "POST", path: /^\/api\/report\/([^/]+\/export|translate)$/ },
];

const POLL_FIRST_MS = 1500;
const POLL_EVERY_MS = 3000;
const GIVE_UP_AFTER_MS = 15 * 60 * 1000;
const MAX_POLL_NETWORK_ERRORS = 5;

function isLongStep(path: string, init?: RequestInit): boolean {
  let pathname: string;
  try {
    pathname = new URL(path, API_BASE_URL).pathname;
  } catch {
    return false;
  }
  const method = (init?.method ?? "GET").toUpperCase();
  return LONG_STEPS.some((step) => step.method === method && step.path.test(pathname));
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function runAsJob(path: string, init: RequestInit | undefined, forceRefresh: boolean): Promise<Response> {
  const headers = new Headers(init?.headers);
  headers.set("X-Run-As-Job", "1");
  const started = await send(path, { ...init, headers }, forceRefresh);
  // Anything but "accepted" is already the final answer (an error, or an older backend without jobs).
  if (started.status !== 202) return started;

  const { job_id: jobId } = (await started.json()) as { job_id: string };
  const deadline = Date.now() + GIVE_UP_AFTER_MS;
  let networkErrors = 0;
  await sleep(POLL_FIRST_MS);
  while (Date.now() < deadline) {
    try {
      const status = await send(`/api/jobs/${jobId}`, undefined, false);
      networkErrors = 0;
      if (!status.ok) return status; // e.g. 404: the server restarted and the job is gone
      if (((await status.json()) as { status: string }).status === "done") {
        return send(`/api/jobs/${jobId}/result`, undefined, false);
      }
    } catch (err) {
      // A short network hiccup must not lose a job that is still running.
      if (++networkErrors >= MAX_POLL_NETWORK_ERRORS) throw err;
    }
    await sleep(POLL_EVERY_MS);
  }
  throw new Error("This step is taking too long. Please try again.");
}

/** fetch() against the backend API; adds the Entra bearer token when auth is enabled, and runs the long AI steps as background jobs. */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const long = isLongStep(path, init);
  const attempt = (forceRefresh: boolean) => (long ? runAsJob(path, init, forceRefresh) : send(path, init, forceRefresh));
  const response = await attempt(false);
  if (response.status === 401 && authEnabled) {
    return attempt(true);
  }
  return response;
}

function filenameFrom(response: Response, fallback: string): string {
  const header = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/i.exec(header);
  return match ? match[1] : fallback;
}

/** Downloads an API file through apiFetch (so the bearer header is sent) and saves it.
 *  `filename` is only a fallback: the server's Content-Disposition name wins when present. */
export async function downloadFile(path: string, filename = "download"): Promise<void> {
  const response = await apiFetch(path);
  if (!response.ok) {
    let detail = `Download failed (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filenameFrom(response, filename);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
