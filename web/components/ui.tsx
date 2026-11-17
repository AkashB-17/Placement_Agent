import { AlertCircle, AlertTriangle, CheckCircle2, Loader2, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export function ErrorBox({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
      <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}

export function SuccessBox({ children }: { children: ReactNode }) {
  return (
    <div role="status" className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
      <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{children}</span>
    </div>
  );
}

export function Warnings({ items }: { items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
      <p className="mb-1 flex items-center gap-1.5 font-medium">
        <AlertTriangle className="size-4" aria-hidden /> Rules dropped because the document doesn&apos;t state them
      </p>
      <ul className="list-disc space-y-0.5 pl-6">
        {items.map((w, i) => (
          <li key={`${w}-${i}`}>{w}</li>
        ))}
      </ul>
    </div>
  );
}

const CHIP_TONES = {
  green: "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/15",
  red: "bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-600/15",
  slate: "bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-500/10",
  brand: "bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-600/15",
  amber: "bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-600/20",
} as const;

export type Tone = keyof typeof CHIP_TONES;

export function Chip({ tone = "slate", icon: Icon, children }: { tone?: Tone; icon?: LucideIcon; children: ReactNode }) {
  return (
    <span className={`chip ${CHIP_TONES[tone]}`}>
      {Icon && <Icon className="size-3" aria-hidden />}
      {children}
    </span>
  );
}

export function Chips({ items, tone, empty = "—" }: { items: string[]; tone: Tone; empty?: string }) {
  if (!items.length) return <span className="text-sm text-slate-400">{empty}</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((s, i) => (
        <Chip key={`${s}-${i}`} tone={tone}>
          {s}
        </Chip>
      ))}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

export function StatCard({ label, value, icon: Icon, tone = "slate" }: { label: string; value: ReactNode; icon: LucideIcon; tone?: Tone }) {
  return (
    <div className="card flex items-center gap-4 p-4">
      <div className={`flex size-10 items-center justify-center rounded-lg ${CHIP_TONES[tone]}`}>
        <Icon className="size-5" aria-hidden />
      </div>
      <div>
        <p className="text-2xl font-semibold tabular-nums leading-tight">{value}</p>
        <p className="text-xs text-slate-500">{label}</p>
      </div>
    </div>
  );
}

export function EmptyState({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center px-6 py-12 text-center">
      <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-slate-100 text-slate-400">
        <Icon className="size-6" aria-hidden />
      </div>
      <p className="font-medium text-slate-800">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function Spinner({ className = "size-4" }: { className?: string }) {
  return <Loader2 className={`${className} animate-spin`} aria-hidden />;
}

export function Skeleton({ className }: { className: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function CardSkeletons({ count = 3, className = "h-32" }: { count?: number; className?: string }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="card space-y-3">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-3 w-1/2" />
          <Skeleton className={`w-full ${className === "h-32" ? "h-16" : className}`} />
        </div>
      ))}
    </>
  );
}

const AVATAR_TONES = ["bg-brand-100 text-brand-700", "bg-emerald-100 text-emerald-700", "bg-amber-100 text-amber-800", "bg-rose-100 text-rose-700", "bg-sky-100 text-sky-700", "bg-violet-100 text-violet-700"];

export function Avatar({ name, className = "size-9 text-sm" }: { name: string; className?: string }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
  const tone = AVATAR_TONES[[...name].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % AVATAR_TONES.length];
  return (
    <span className={`inline-flex shrink-0 items-center justify-center rounded-full font-semibold ${tone} ${className}`} aria-hidden>
      {initials || "?"}
    </span>
  );
}

export function display(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

export function errorText(e: unknown): string {
  if (e && typeof e === "object" && "message" in e) return String((e as { message: unknown }).message);
  return String(e);
}
