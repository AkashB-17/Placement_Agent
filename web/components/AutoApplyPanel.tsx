"use client";

import { ArrowRight, CircleSlash, Rocket, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/time";
import type { AutoApplyRun, JDSummary } from "@/lib/types";
import { invalidate } from "@/lib/useApi";

import { Avatar, ErrorBox, Spinner, SuccessBox, errorText } from "./ui";

/** Officer action: create pending applications for opted-in students who qualify. */
export function AutoApplyPanel({
  jd,
  policyId,
  threshold,
  onRan,
}: {
  jd: JDSummary;
  policyId: string;
  threshold: number;
  onRan?: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<AutoApplyRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const result = await api<AutoApplyRun>(`/jds/${jd.id}/auto-apply?policy_id=${encodeURIComponent(policyId)}`, {
        method: "POST",
      });
      invalidate("/applications", "/auto-apply/runs");
      setRun(result);
      onRan?.();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <section className="card space-y-4 border-brand-200 bg-gradient-to-br from-brand-50/70 to-surface">
      <div className="flex flex-wrap items-start gap-4">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white shadow-sm">
          <Rocket className="size-5" aria-hidden />
        </span>
        <div className="min-w-60 flex-1">
          <p className="font-semibold">Auto-apply for {jd.company ?? "this job"}</p>
          <p className="text-sm text-slate-600">
            Applies for every student who opted in, is eligible, and scores at least {threshold} (or their own higher bar).
            Each student is notified and can withdraw for 24 hours, or until 6 hours before the deadline, before anything is
            sent. Running it again only adds new qualifiers.
          </p>
        </div>
        {!confirming && (
          <button className="btn" onClick={() => setConfirming(true)} disabled={busy}>
            <Rocket className="size-4" aria-hidden /> Run auto-apply
          </button>
        )}
      </div>

      {confirming && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-brand-200 bg-surface p-3 text-sm">
          <ShieldAlert className="size-4 text-brand-600" aria-hidden />
          <span className="flex-1 text-slate-700">
            This creates real pending applications and notifies students. Stored scores are reused; only students not yet scored for this job need an AI call.
          </span>
          <button className="btn" onClick={start} disabled={busy}>
            {busy && <Spinner />} {busy ? "Applying…" : "Confirm"}
          </button>
          <button className="btn-ghost" onClick={() => setConfirming(false)} disabled={busy}>
            Cancel
          </button>
        </div>
      )}

      <ErrorBox message={error} />

      {run && (
        <div className="space-y-4">
          <SuccessBox>
            {run.created.length === 0
              ? "No new applications."
              : `${run.created.length} pending application${run.created.length === 1 ? "" : "s"} created. They'll be sent ${formatDateTime(run.release_at)} unless withdrawn.`}
            {run.not_opted_in > 0 && ` ${run.not_opted_in} student${run.not_opted_in === 1 ? " hasn't" : "s haven't"} opted in.`}
          </SuccessBox>

          {run.created.length > 0 && (
            <div>
              <p className="eyebrow mb-2">Applied</p>
              <ul className="flex flex-wrap gap-2">
                {run.created.map((a) => (
                  <li key={a.id} className="flex items-center gap-2 rounded-full border border-slate-200 bg-surface py-1 pr-3 pl-1 text-sm">
                    <Avatar name={a.student_name} className="size-6 text-[10px]" />
                    {a.student_name}
                    <span className="font-semibold tabular-nums text-emerald-600">{Math.round(a.score)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {run.skipped.length > 0 && (
            <div>
              <p className="eyebrow mb-2">Not applied</p>
              <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-surface text-sm">
                {run.skipped.map((s) => (
                  <li key={s.student_id} className="flex gap-3 px-3 py-2">
                    <CircleSlash className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden />
                    <span>
                      <span className="font-medium text-slate-800">{s.student_name}</span>
                      <span className="text-slate-500"> · {s.reason}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <Link href={`/applications?jd=${jd.id}`} className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline">
            Track these applications <ArrowRight className="size-4" aria-hidden />
          </Link>
        </div>
      )}
    </section>
  );
}
