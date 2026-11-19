"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { FullPageSpinner, homeFor, useAuth } from "@/lib/auth";

export default function Home() {
  const { loading, session, profile } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    // Signed in with a loaded profile → that role's home page. Anything else (signed out,
    // session rejected, API unreachable) → /login, which explains what went wrong.
    router.replace(session && profile ? homeFor(profile.role) : "/login");
  }, [loading, session, profile, router]);

  return <FullPageSpinner />;
}
