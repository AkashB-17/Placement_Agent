"use client";

import { CircleCheck, CircleX, Clock3, ExternalLink, Send, Undo2 } from "lucide-react";
import { useState } from "react";

import { api } from "@/lib/api";
import { formatDateTime, timeUntil, useNow } from "@/lib/time";
import type { Application, ApplicationStatus } from "@/lib/types";

import { ScoreRing } from "./MatchResultCard";
import { Avatar, Chip, ErrorBox, Spinner, errorText } from "./ui";

export function StatusChip({ status }: { status: ApplicationStatus }) {
  if (status === "pending") return <Chip tone="amber" icon={Clock3}>Pending</Chip>;
  if (status === "submitted") return <Chip tone="green" icon={Send}>Sent to company</Chip>;
  return <Chip tone="slate" icon={Undo2}>Withdrawn</Chip>;
}

/** Progress through the withdraw window: created → release. */
function WindowBar({ app, now }: { app: Application; now: number }) {
  const start = new Date(app.created_at).getTime();
  const end = new Date(app.release_at).getTime();
  const done = Math.min(Math.max((now - start) / Math.max(end - start, 1), 0), 1);
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-amber-100" aria-hidden>
      <div className="h-full rounded-full bg-amber-500 transition-[width] duration-700" style={{ width: `${done * 100}%` }} />
    </div>
  );
}

async function openResume(id: string) {
  // The pinned resume version, via a 60-second signed link fetched on click.
  const link = await api<{ url: string }>(`/applications/${id}/resume`);
  window.open(link.url, "_blank", "noopener,noreferrer");
}

export function ApplicationCard({
  app,
  viewer,
  onChanged,
}: {
  app: Application;
  viewer: "student" | "staff" | "recruiter";
  onChanged?: (updated: Application) => void;
}) {
  const now = useNow();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = app.status === "pending" && new Date(app.release_at).getTime() > now;
  const title = viewer === "student" ? app.company ?? "Unknown company" : app.student_name;
  const subtitle = viewer === "student" ? app.role : [app.company, app.role].filter(Boolean).join(" · ");

  async function withdraw() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api<Application>(`/applications/${app.id}/withdraw`, { method: "POST" });
      onChanged?.(updated);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  async function resume() {
    setError(null);
    try {
      await openResume(app.id);
    } catch (e) {
      setError(errorText(e));
    }
  }

  const s = app.score_breakdown;
  return (
    <article className="card p-0">
      <div className="flex flex-wrap items-center gap-4 p-4">
        {viewer === "student" ? (
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-50 font-semibold text-brand-700">
            {(app.company ?? "?").charAt(0)}
          </span>
        ) : (
          <Avatar name={app.student_name} />
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-slate-900">{title}</p>
          <p className="truncate text-sm text-slate-500">{subtitle || "—"}</p>
        </div>
        <StatusChip status={app.status} />
        <ScoreRing score={app.score} size={48} />
      </div>

      <div className="space-y-3 border-t border-slate-100 px-4 py-3 text-sm">
        {pending ? (
          <div className="space-y-2">
            <p className="flex flex-wrap items-center gap-x-2 text-slate-700">
              <Clock3 className="size-4 text-amber-500" aria-hidden />
              Sends <span className="font-medium">{timeUntil(app.release_at, now)}</span>
              <span className="text-slate-400">({formatDateTime(app.release_at)})</span>
            </p>
            <WindowBar app={app} now={now} />
          </div>
        ) : app.status === "submitted" ? (
          <p className="flex items-center gap-2 text-slate-600">
            <CircleCheck className="size-4 text-emerald-500" aria-hidden />
            Sent {app.decided_at ? formatDateTime(app.decided_at) : ""}
          </p>
        ) : app.status === "pending" ? (
          <p className="flex items-center gap-2 text-slate-600">
            <Spinner /> Sending now…
          </p>
        ) : (
          <p className="flex items-center gap-2 text-slate-500">
            <CircleX className="size-4" aria-hidden />
            Withdrawn {app.decided_at ? formatDateTime(app.decided_at) : ""}
          </p>
        )}

        <div className="flex flex-wrap gap-1.5">
          {s.matched_required.map((k, i) => (
            <Chip key={`m-${k}-${i}`} tone="green" icon={CircleCheck}>{k}</Chip>
          ))}
          {s.missing_required.map((k, i) => (
            <Chip key={`x-${k}-${i}`} tone="red" icon={CircleX}>{k}</Chip>
          ))}
        </div>

        <ErrorBox message={error} />

        <div className="flex flex-wrap items-center gap-2">
          {app.has_resume_file && (
            <button className="btn-secondary" onClick={resume}>
              <ExternalLink className="size-4" aria-hidden /> Resume as sent
            </button>
          )}
          {viewer === "student" && app.can_withdraw && pending && (
            confirming ? (
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-slate-600">Withdraw? This can&apos;t be undone.</span>
                <button className="btn bg-rose-600 hover:bg-rose-700" onClick={withdraw} disabled={busy}>
                  {busy && <Spinner />} Yes, withdraw
                </button>
                <button className="btn-ghost" onClick={() => setConfirming(false)} disabled={busy}>
                  Keep it
                </button>
              </span>
            ) : (
              <button className="btn-secondary text-rose-700" onClick={() => setConfirming(true)}>
                <Undo2 className="size-4" aria-hidden /> Withdraw
              </button>
            )
          )}
        </div>
      </div>
    </article>
  );
}
