"use client";

import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

import { AuthCard } from "@/components/AuthCard";
import { ErrorBox, Spinner } from "@/components/ui";
import { authCallbackUrl, friendlyAuthError, supabase } from "@/lib/supabase";

/** Request a password-reset link. The link lands on /auth/callback, then /set-password. */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const address = email.trim().toLowerCase();
    const { error: resetError } = await supabase.auth.resetPasswordForEmail(address, {
      redirectTo: authCallbackUrl("set-password"),
    });
    setBusy(false);
    if (resetError) setError(friendlyAuthError(resetError.message));
    // Same message whether or not an account exists, so this can't reveal who is registered.
    else setSentTo(address);
  }

  if (sentTo) {
    return (
      <AuthCard
        title="Check your email"
        subtitle={<>If an account exists for <span className="font-medium text-slate-800">{sentTo}</span>, we&apos;ve sent a link to set a new password.</>}
        footer={<Link href="/login" className="font-medium text-brand-700 hover:underline">Back to sign in</Link>}
      >
        <div className="flex gap-3 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">
          <MailCheck className="mt-0.5 size-5 shrink-0 text-brand-600" aria-hidden />
          <span>The link works once and expires after a while. Didn&apos;t get it? Check spam, then request another.</span>
        </div>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Reset your password"
      subtitle="Enter your account email and we'll send you a link to choose a new password."
      footer={<>Remembered it? <Link href="/login" className="font-medium text-brand-700 hover:underline">Sign in</Link></>}
    >
      <form onSubmit={onSubmit} method="post" className="space-y-5">
        <div>
          <label className="label" htmlFor="email">Email</label>
          <input id="email" type="email" className="input" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <ErrorBox message={error} />
        <button className="btn w-full py-2.5" disabled={!ready || busy}>
          {(!ready || busy) && <Spinner />}
          {!ready ? "Loading…" : busy ? "Sending…" : "Send reset link"}
        </button>
      </form>
    </AuthCard>
  );
}
