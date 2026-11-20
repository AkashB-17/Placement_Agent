import { supabase } from "./supabase";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").trim().replace(/\/+$/, "");
// Must be an absolute URL. A bare word (e.g. the variable's own name pasted as its value)
// would be fetched relative to the web app's own domain and come back as the host's 404.
const API_URL_IS_VALID = /^https?:\/\/[^\s/]+/i.test(API_URL);

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function detailMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: [{loc, msg, ...}]
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join("; ");
    }
  }
  // Every error from our API is JSON with a "detail". Anything else came from something in
  // front of it (the hosting platform, or a wrong address), so say where we were looking.
  if (status === 404) {
    return `The server at ${API_URL} answered "not found" without an API error. NEXT_PUBLIC_API_URL may point to the wrong server.`;
  }
  return `Request failed (${status}) at ${API_URL}.`;
}

/** Calls the FastAPI backend with the current user's access token. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!API_URL_IS_VALID) {
    throw new ApiError(
      0,
      `The app's API address is misconfigured: NEXT_PUBLIC_API_URL is "${API_URL}". It must be the API's full URL, e.g. https://your-api.onrender.com. Fix it in the hosting settings and redeploy.`,
    );
  }
  const { data } = await supabase.auth.getSession();
  const headers = new Headers(init.headers);
  if (data.session) headers.set("Authorization", `Bearer ${data.session.access_token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(
      0,
      `No response from the API at ${API_URL}. Check that it's running (a sleeping free server can take a minute to wake), and look at its logs for an error.`,
    );
  }

  const text = await response.text();
  const body = text ? safeJson(text) : null;
  if (!response.ok) throw new ApiError(response.status, detailMessage(body, response.status));
  return body as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
