"use client";

import { CircleCheck, LinkIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthCard } from "@/components/AuthCard";
import { ErrorBox, Spinner } from "@/components/ui";
import { homeFor, useAuth } from "@/lib/auth";

/**
 * Landing page for every Supabase email link: sign-up confirmation, password reset and
 * staff invites. The session arrives in the URL fragment and the Supabase client picks it
 * up on load; `?next=` (which survives in the query string) says where to go afterwards.
 */
function readLink(): { next: string | null; error: string | null } {
  if (typeof window === "undefined") return { next: null, error: null };
  const query = new URLSearchParams(window.location.search);
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const error = query.get("error_description") ?? hash.get("error_description") ?? query.get("error") ?? hash.get("error");
  return { next: query.get("next"), error: error ? error.replace(/\+/g, " ") : null };
}

export default function AuthCallbackPage() {
  const { loading, session, profile, error: profileError } = useAuth();
  const router = useRouter();
  const [link] = useState(readLink);
  const [waitedLongEnough, setWaitedLongEnough] = useState(false);

  useEffect(() => {
    const id = window.setTimeout(() => setWaitedLongEnough(true), 4000);
    return () => window.clearTimeout(id);
  }, []);

  useEffect(() => {
    if (loading || !session) return;
    if (link.next === "set-password") {
      router.replace("/set-password");
    } else if (profile) {
      const id = window.setTimeout(() => router.replace(homeFor(profile.role)), 1200);
      return () => window.clearTimeout(id);
    }
  }, [loading, session, profile, link.next, router]);

  const failed = !loading && !session && (link.error || waitedLongEnough);
  if (failed) {
    return (
      <AuthCard
        title="This link didn't work"
        subtitle={link.error ?? "It may have expired or already been used. Links work once, for a limited time."}
        footer={<Link href="/login" className="font-medium text-brand-700 hover:underline">Back to sign in</Link>}
      >
        <div className="space-y-3">
          <Link href="/forgot-password" className="btn w-full">
            <LinkIcon className="size-4" aria-hidden /> Send me a new password link
          </Link>
          <Link href="/signup" className="btn-secondary w-full">
            Create an account again
          </Link>
        </div>
      </AuthCard>
    );
  }

  if (session && link.next !== "set-password" && profileError) {
    return (
      <AuthCard title="Email confirmed" subtitle="Your account is ready, but we couldn't load it just now.">
        <ErrorBox message={profileError} />
        <Link href="/" className="btn mt-4 w-full">Try again</Link>
      </AuthCard>
    );
  }

  if (session && link.next !== "set-password") {
    return (
      <AuthCard title="Email confirmed" subtitle="Your account is ready. Taking you in…">
        <p className="flex items-center gap-2 text-sm text-emerald-700">
          <CircleCheck className="size-4" aria-hidden /> Signed in as {session.user.email}
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Checking your link…">
      <p className="flex items-center gap-2 text-sm text-slate-500">
        <Spinner /> One moment.
      </p>
    </AuthCard>
  );
}
