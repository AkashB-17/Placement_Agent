import { createClient } from "@supabase/supabase-js";

// The browser uses Supabase only to log in and hold the session. All data goes through
// the FastAPI backend, which verifies the token and checks the role on every request.
const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? "";

export const supabaseConfigured = Boolean(url && publishableKey);

export const supabase = createClient(url || "http://invalid.localhost", publishableKey || "missing", {
  auth: { persistSession: true, autoRefreshToken: true },
});
