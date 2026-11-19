import { Sparkles } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

/** Centered card used by the sign-up, password and email-link pages. */
export function AuthCard({ title, subtitle, children, footer }: { title: string; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
      <div className="w-full max-w-sm">
        <Link href="/login" className="mb-8 flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-brand-600 text-white">
            <Sparkles className="size-5" aria-hidden />
          </span>
          <span className="text-lg font-semibold text-slate-900">Placement Portal</span>
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <div className="mt-1 mb-8 text-sm text-slate-500">{subtitle}</div>}
        {!subtitle && <div className="mb-8" />}
        {children}
        {footer && <div className="mt-8 text-center text-sm text-slate-500">{footer}</div>}
      </div>
    </div>
  );
}

/** Same password rules on every page that sets one. Supabase enforces its own minimum too. */
export const MIN_PASSWORD_LENGTH = 8;

export function passwordProblem(password: string, confirm: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) return `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  if (password !== confirm) return "The two passwords don't match.";
  return null;
}
