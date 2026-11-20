import type { NextConfig } from "next";

// NEXT_PUBLIC_ values are baked into the browser bundle at build time, so a wrong value is
// only discovered by users. Fail the build instead, with a message naming the setting.
function checkPublicUrl(name: string): void {
  const value = process.env[name];
  if (value === undefined || value === "") return; // unset: the code's local default applies
  if (!/^https?:\/\/[^\s/]+/i.test(value.trim())) {
    throw new Error(
      `${name} must be a full URL starting with http:// or https:// (got "${value}"). ` +
        "Set it in your hosting provider's environment variables and redeploy.",
    );
  }
}
checkPublicUrl("NEXT_PUBLIC_API_URL");
checkPublicUrl("NEXT_PUBLIC_SUPABASE_URL");

const nextConfig: NextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
