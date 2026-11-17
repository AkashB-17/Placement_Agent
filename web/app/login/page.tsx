"use client";

import { CheckCircle2, FileSearch, Scale, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { ErrorBox, Spinner } from "@/components/ui";
import { homeFor, useAuth } from "@/lib/auth";
import { supabaseConfigured } from "@/lib/supabase";

const POINTS = [
  { icon: Scale, title: "Rule-based eligibility", text: "CGPA, backlogs, branch and batch are checked by fixed rules, never guessed." },
  { icon: FileSearch, title: "Evidence for every match", text: "Each matched skill is backed by a quote verified against the resume." },
  { icon: CheckCircle2, title: "Cited reasons", text: "Every rejection points to the policy or JD clause behind it." },
];

export default function LoginPage() {
  const { signIn, profile, error: profileError } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // False until React has hydrated: before that, clicking "Sign in" can't run any code.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);

  useEffect(() => {
    if (profile) router.replace(homeFor(profile.role));
  }, [profile, router]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const message = await signIn(email.trim(), password);
    setError(message);
    if (message) setBusy(false); // on success the redirect above takes over
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <section className="relative hidden overflow-hidden bg-brand-900 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -top-24 -right-24 size-96 rounded-full bg-brand-600/40 blur-3xl" aria-hidden />
        <div className="absolute -bottom-32 -left-16 size-96 rounded-full bg-violet-500/20 blur-3xl" aria-hidden />
        <div className="relative flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/20">
            <Sparkles className="size-5" aria-hidden />
          </span>
          <span className="text-lg font-semibold">Placement Portal</span>
        </div>
        <div className="relative max-w-md">
          <h1 className="text-3xl leading-tight font-semibold">Shortlist candidates you can explain.</h1>
          <p className="mt-3 text-brand-100/80">
            Upload a job description and see who is eligible, how well each resume matches, and why.
          </p>
          <ul className="mt-10 space-y-6">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/15">
                  <Icon className="size-4" aria-hidden />
                </span>
                <span>
                  <span className="block font-medium">{title}</span>
                  <span className="block text-sm text-brand-100/70">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-brand-100/50">Campus placement cell</p>
      </section>

      <section className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="flex size-9 items-center justify-center rounded-lg bg-brand-600 text-white">
              <Sparkles className="size-5" aria-hidden />
            </span>
            <span className="text-lg font-semibold">Placement Portal</span>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 mb-8 text-sm text-slate-500">Officers, recruiters and admins are added by invitation.</p>

          {!supabaseConfigured && (
            <div className="mb-4">
              <ErrorBox message="Supabase isn't configured. Copy web/.env.local.example to web/.env.local." />
            </div>
          )}

          {/* method=post: if a submit ever happens before hydration, nothing lands in the URL. */}
          <form onSubmit={onSubmit} method="post" className="space-y-5">
            <div>
              <label className="label" htmlFor="email">Email</label>
              <input id="email" type="email" className="input" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="password">Password</label>
              <input id="password" type="password" className="input" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            <ErrorBox message={error ?? profileError} />
            <button className="btn w-full py-2.5" disabled={!ready || busy}>
              {(!ready || busy) && <Spinner />}
              {!ready ? "Loading…" : busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </div>
      </section>
    </div>
  );
}
