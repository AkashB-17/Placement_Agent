import { createClient } from "@supabase/supabase-js";

// The browser uses Supabase only to log in and hold the session. All data goes through
// the FastAPI backend, which verifies the token and checks the role on every request.
const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? "";

export const supabaseConfigured = Boolean(url && publishableKey);

export const supabase = createClient(url || "http://invalid.localhost", publishableKey || "missing", {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    // Email links (confirm sign-up, reset password, invite) return the session in the URL
    // fragment, which the client reads on load. "implicit" (not PKCE) so a link opened in
    // a different browser or device than the one that requested it still works.
    detectSessionInUrl: true,
    flowType: "implicit",
  },
});

/** Where Supabase email links send the user back to. `next` survives in the query string. */
export type AuthNext = "confirmed" | "set-password";

export function authCallbackUrl(next: AuthNext): string {
  return `${window.location.origin}/auth/callback?next=${next}`;
}

/** Supabase auth error → message a student can act on. */
export function friendlyAuthError(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("rate limit")) return "Too many emails were sent recently. Please wait a few minutes and try again.";
  if (m.includes("invalid login credentials")) return "Email or password is incorrect.";
  if (m.includes("email not confirmed")) return "Please confirm your email first: open the link we sent you.";
  if (m.includes("password should be")) return message;
  if (m.includes("same password")) return "Choose a password different from your current one.";
  if (m.includes("weak")) return "That password is too weak. Use a longer one with letters and numbers.";
  return message;
}
