"use client";

import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { AuthCard, MIN_PASSWORD_LENGTH, passwordProblem } from "@/components/AuthCard";
import { ErrorBox, Spinner, SuccessBox } from "@/components/ui";
import { homeFor, useAuth } from "@/lib/auth";
import { authCallbackUrl, friendlyAuthError, supabase, supabaseConfigured } from "@/lib/supabase";

/**
 * Student self sign-up. Every new account is a student (a database trigger sets the role);
 * officers, recruiters and admins are invited instead. The account is linked to the
 * student's placement record by email, so the email must be confirmed before it works.
 */
export default function SignUpPage() {
  const { profile } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [resent, setResent] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);

  useEffect(() => {
    if (profile) router.replace(homeFor(profile.role));
  }, [profile, router]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const problem = passwordProblem(password, confirm);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    const address = email.trim().toLowerCase();
    const { data, error: signUpError } = await supabase.auth.signUp({
      email: address,
      password,
      options: { emailRedirectTo: authCallbackUrl("confirmed") },
    });
    setBusy(false);
    if (signUpError) {
      setError(friendlyAuthError(signUpError.message));
      return;
    }
    if (data.session) return; // email confirmation is off: already signed in; the effect above redirects
    // Shown whether or not the email was already registered, so this page can't be used
    // to find out who has an account.
    setSentTo(address);
  }

  async function resend() {
    if (!sentTo) return;
    setBusy(true);
    setError(null);
    const { error: resendError } = await supabase.auth.resend({
      type: "signup",
      email: sentTo,
      options: { emailRedirectTo: authCallbackUrl("confirmed") },
    });
    setBusy(false);
    if (resendError) setError(friendlyAuthError(resendError.message));
    else setResent(true);
  }

  if (sentTo) {
    return (
      <AuthCard
        title="Check your email"
        subtitle={<>We sent a confirmation link to <span className="font-medium text-slate-800">{sentTo}</span>. Open it to activate your account.</>}
        footer={<>Confirmed already? <Link href="/login" className="font-medium text-brand-700 hover:underline">Sign in</Link></>}
      >
        <div className="space-y-4">
          <div className="flex gap-3 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">
            <MailCheck className="mt-0.5 size-5 shrink-0 text-brand-600" aria-hidden />
            <span>
              The link works once. If it isn&apos;t in your inbox within a few minutes, check spam, or send it again.
              If you already had an account with this email, sign in or reset your password instead.
            </span>
          </div>
          <ErrorBox message={error} />
          {resent && <SuccessBox>Sent again.</SuccessBox>}
          <button className="btn-secondary w-full" onClick={resend} disabled={busy}>
            {busy && <Spinner />} Resend the email
          </button>
        </div>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Create your student account"
      subtitle="Use the email your placement office has on record, so your account links to your profile. Officers and recruiters are added by invitation."
      footer={<>Already have an account? <Link href="/login" className="font-medium text-brand-700 hover:underline">Sign in</Link></>}
    >
      {!supabaseConfigured && (
        <div className="mb-4">
          <ErrorBox message="Supabase isn't configured. Copy web/.env.local.example to web/.env.local." />
        </div>
      )}
      <form onSubmit={onSubmit} method="post" className="space-y-5">
        <div>
          <label className="label" htmlFor="email">College email</label>
          <input id="email" type="email" className="input" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="password">Password</label>
          <input id="password" type="password" className="input" autoComplete="new-password" required minLength={MIN_PASSWORD_LENGTH} value={password} onChange={(e) => setPassword(e.target.value)} />
          <p className="mt-1 text-xs text-slate-400">At least {MIN_PASSWORD_LENGTH} characters.</p>
        </div>
        <div>
          <label className="label" htmlFor="confirm">Confirm password</label>
          <input id="confirm" type="password" className="input" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </div>
        <ErrorBox message={error} />
        <button className="btn w-full py-2.5" disabled={!ready || busy}>
          {(!ready || busy) && <Spinner />}
          {!ready ? "Loading…" : busy ? "Creating account…" : "Create account"}
        </button>
      </form>
    </AuthCard>
  );
}
