"use client";

import { ChevronDown, History } from "lucide-react";
import { useState } from "react";

import { formatDateTime } from "@/lib/time";
import type { AutoApplyRunRecord } from "@/lib/types";
import { useApi } from "@/lib/useApi";

import { Chip, ErrorBox, Skeleton, type Tone } from "./ui";

const STATUS: Record<AutoApplyRunRecord["status"], { label: string; tone: Tone }> = {
  completed: { label: "Ran", tone: "green" },
  skipped: { label: "Didn't run", tone: "amber" },
  failed: { label: "Failed", tone: "red" },
};

/** One line saying how a run ended, e.g. "1 applied · 2 skipped · 25 not opted in". */
export function runSummary(run: AutoApplyRunRecord): string {
  if (run.status !== "completed") return run.message ?? "No details.";
  return [
    `${run.applied} applied`,
    `${run.skipped.length} skipped`,
    `${run.not_opted_in} not opted in`,
  ].join(" · ");
}

export const triggerLabel = (run: AutoApplyRunRecord) =>
  run.trigger === "upload" ? "Automatic, after upload" : "Run by staff";

function RunRow({ run }: { run: AutoApplyRunRecord }) {
  const [open, setOpen] = useState(false);
  const status = STATUS[run.status];
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <Chip tone={status.tone}>{status.label}</Chip>
        <span className="font-medium text-slate-800">{triggerLabel(run)}</span>
        <span className="text-slate-500">{formatDateTime(run.ran_at)}</span>
        <span className="text-slate-700">{runSummary(run)}</span>
        {run.skipped.length > 0 && (
          <button className="btn-ghost ml-auto px-2 py-1 text-brand-700" onClick={() => setOpen(!open)} aria-expanded={open}>
            Why skipped <ChevronDown className={`size-4 transition ${open ? "rotate-180" : ""}`} aria-hidden />
          </button>
        )}
      </div>
      {open && (
        <ul className="mt-2 space-y-1 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
          {run.skipped.map((s) => (
            <li key={s.student_id} className="flex flex-wrap gap-x-2">
              <span className="font-medium text-slate-800">{s.student_name}</span>
              <span className="text-slate-600">{s.reason}</span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/** Recorded auto-apply runs for one job (GET /auto-apply/runs?jd_id=), newest first. */
export function AutoApplyHistory({ jdId }: { jdId: string }) {
  const runs = useApi<AutoApplyRunRecord[]>(`/auto-apply/runs?jd_id=${encodeURIComponent(jdId)}&limit=10`);
  return (
    <section className="card space-y-3">
      <p className="flex items-center gap-2 font-semibold text-slate-900">
        <History className="size-4 text-slate-500" aria-hidden /> Auto-apply history
      </p>
      <ErrorBox message={runs.error?.message} />
      {runs.loading && !runs.data ? (
        <Skeleton className="h-10 w-full" />
      ) : !runs.data?.length ? (
        <p className="text-sm text-slate-500">
          No runs yet. Auto-apply runs by itself when a job is uploaded, or use Run auto-apply above.
        </p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {runs.data.map((run) => <RunRow key={run.id} run={run} />)}
        </ul>
      )}
    </section>
  );
}
