"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthCard, MIN_PASSWORD_LENGTH, passwordProblem } from "@/components/AuthCard";
import { ErrorBox, Spinner, SuccessBox } from "@/components/ui";
import { FullPageSpinner, homeFor, useAuth } from "@/lib/auth";
import { friendlyAuthError, supabase } from "@/lib/supabase";

/**
 * Choose a password. Reached from a password-reset link or a staff invite link (both sign
 * the user in first), or by a signed-in user who wants to change their password.
 */
export default function SetPasswordPage() {
  const { loading, session, profile } = useAuth();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const problem = passwordProblem(password, confirm);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    const { error: updateError } = await supabase.auth.updateUser({ password });
    setBusy(false);
    if (updateError) setError(friendlyAuthError(updateError.message));
    else setDone(true);
  }

  if (loading) return <FullPageSpinner />;

  if (!session) {
    return (
      <AuthCard
        title="Link needed"
        subtitle="To set a password, open the link from your password-reset or invitation email."
        footer={<Link href="/login" className="font-medium text-brand-700 hover:underline">Back to sign in</Link>}
      >
        <Link href="/forgot-password" className="btn w-full">Send me a password link</Link>
      </AuthCard>
    );
  }

  if (done) {
    return (
      <AuthCard title="Password saved" subtitle="Use it the next time you sign in.">
        <SuccessBox>Your password has been updated.</SuccessBox>
        <button className="btn mt-4 w-full" onClick={() => router.replace(profile ? homeFor(profile.role) : "/")}>
          Continue
        </button>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Choose a password"
      subtitle={<>For <span className="font-medium text-slate-800">{session.user.email}</span>. You&apos;ll use it to sign in from now on.</>}
    >
      <form onSubmit={onSubmit} method="post" className="space-y-5">
        <div>
          <label className="label" htmlFor="password">New password</label>
          <input id="password" type="password" className="input" autoComplete="new-password" required minLength={MIN_PASSWORD_LENGTH} value={password} onChange={(e) => setPassword(e.target.value)} />
          <p className="mt-1 text-xs text-slate-400">At least {MIN_PASSWORD_LENGTH} characters.</p>
        </div>
        <div>
          <label className="label" htmlFor="confirm">Confirm password</label>
          <input id="confirm" type="password" className="input" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </div>
        <ErrorBox message={error} />
        <button className="btn w-full py-2.5" disabled={busy}>
          {busy && <Spinner />}
          {busy ? "Saving…" : "Save password"}
        </button>
      </form>
    </AuthCard>
  );
}
