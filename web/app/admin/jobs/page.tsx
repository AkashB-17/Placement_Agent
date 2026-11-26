"use client";

import { Briefcase, Pencil, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { runSummary, triggerLabel } from "@/components/AutoApplyHistory";
import { JDEditForm } from "@/components/JDEditForm";
import { Chip, EmptyState, ErrorBox, PageHeader, Skeleton, Spinner, SuccessBox, errorText } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireRole } from "@/lib/auth";
import { formatDateTime } from "@/lib/time";
import type { Application, AutoApplyRunRecord, JDDetail, JDSummary } from "@/lib/types";
import { invalidate, useApi } from "@/lib/useApi";

type Counts = { total: number; pending: number; submitted: number };

function EditPanel({ jd, onDone }: { jd: JDSummary; onDone: (saved: boolean) => void }) {
  const detail = useApi<JDDetail>(`/jds/${jd.id}`);
  if (detail.loading && !detail.data) return <Skeleton className="h-40 w-full" />;
  if (!detail.data) return <ErrorBox message={detail.error?.message} />;
  return <JDEditForm jd={detail.data} deadlineAt={jd.deadline_at} onSaved={() => onDone(true)} onCancel={() => onDone(false)} />;
}

function RemovePanel({ jd, counts, onDone }: { jd: JDSummary; counts: Counts; onDone: (removed: boolean) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api(`/jds/${jd.id}`, { method: "DELETE" });
      onDone(true);
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm">
      <p className="font-medium text-rose-800">Remove {[jd.company, jd.role].filter(Boolean).join(" – ") || "this job"}?</p>
      <p className="text-rose-800">
        {counts.total === 0
          ? "It has no applications. "
          : `This also deletes its ${counts.total} application${counts.total === 1 ? "" : "s"} (${counts.pending} pending, ${counts.submitted} sent to the company). Those students are notified. `}
        Students stop seeing the job at once. This can&apos;t be undone.
      </p>
      <ErrorBox message={error} />
      <div className="flex gap-2">
        <button className="btn bg-rose-600 hover:bg-rose-600 hover:brightness-110" onClick={remove} disabled={busy}>
          {busy ? <Spinner /> : <Trash2 className="size-4" aria-hidden />} Yes, remove
        </button>
        <button className="btn-ghost" onClick={() => onDone(false)} disabled={busy}>Cancel</button>
      </div>
    </div>
  );
}

function JobsAdminPage() {
  const jds = useApi<JDSummary[]>("/jds");
  const applications = useApi<Application[]>("/applications");
  const runs = useApi<AutoApplyRunRecord[]>("/auto-apply/runs?limit=500");
  const latestRun = useMemo(() => {
    const byJd = new Map<string, AutoApplyRunRecord>();
    for (const run of runs.data ?? []) if (!byJd.has(run.jd_id)) byJd.set(run.jd_id, run); // newest first
    return byJd;
  }, [runs.data]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<{ id: string; mode: "edit" | "remove" } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const counts = useMemo(() => {
    const byJd = new Map<string, Counts>();
    for (const a of applications.data ?? []) {
      const c = byJd.get(a.jd_id) ?? { total: 0, pending: 0, submitted: 0 };
      c.total += 1;
      if (a.status === "pending") c.pending += 1;
      if (a.status === "submitted") c.submitted += 1;
      byJd.set(a.jd_id, c);
    }
    return byJd;
  }, [applications.data]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const all = jds.data ?? [];
    return q ? all.filter((j) => [j.company ?? "", j.role ?? ""].some((v) => v.toLowerCase().includes(q))) : all;
  }, [jds.data, query]);

  function done(changed: boolean, message: string) {
    setOpen(null);
    if (!changed) return;
    setNotice(message);
    // Job details feed eligibility, rankings and the student board.
    invalidate("/jds", "/me/jobs", "/applications");
    void jds.refresh();
    void applications.refresh();
  }

  return (
    <>
      <PageHeader
        title="Jobs"
        subtitle="Every job description in the portal. Correct a job's details or remove it."
        actions={<Link href="/upload" className="btn">Add a job</Link>}
      />
      <ErrorBox message={jds.error?.message ?? applications.error?.message} />
      {notice && <div className="mb-4"><SuccessBox>{notice}</SuccessBox></div>}

      {jds.loading && !jds.data ? (
        <div className="card space-y-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
      ) : jds.data?.length === 0 ? (
        <EmptyState icon={Briefcase} title="No jobs yet">Add one on the Upload page.</EmptyState>
      ) : (
        <div className="card overflow-hidden p-0">
          <div className="flex items-center gap-3 border-b border-slate-100 p-3">
            <div className="relative max-w-sm flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
              <input className="input pl-9" placeholder="Search by company or role" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search jobs" />
            </div>
            <span className="text-sm text-slate-500">{shown.length} of {jds.data?.length ?? 0}</span>
          </div>
          <ul className="divide-y divide-slate-100">
            {shown.map((jd) => {
              const c = counts.get(jd.id) ?? { total: 0, pending: 0, submitted: 0 };
              const closed = jd.deadline_at !== null && new Date(jd.deadline_at).getTime() <= Date.now();
              const isOpen = open?.id === jd.id;
              return (
                <li key={jd.id} className="p-4">
                  <div className="flex flex-wrap items-start gap-3">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-50 font-semibold text-brand-700">
                      {(jd.company ?? "?").charAt(0)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-slate-900">{jd.role ?? "Role not stated"}</p>
                      <p className="text-sm text-slate-600">{jd.company ?? "Unknown company"}</p>
                      <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                        <span>{jd.deadline_at ? `${closed ? "Closed" : "Closes"} ${formatDateTime(jd.deadline_at)}` : "Rolling deadline"}</span>
                        {jd.posted_at && <span>Posted {formatDateTime(jd.posted_at)}</span>}
                        <span>{c.total} application{c.total === 1 ? "" : "s"}</span>
                      </p>
                      {latestRun.get(jd.id) && (
                        <p className="mt-1 text-xs text-slate-500">
                          Last auto-apply ({triggerLabel(latestRun.get(jd.id)!).toLowerCase()}, {formatDateTime(latestRun.get(jd.id)!.ran_at)}):{" "}
                          <span className="text-slate-700">{runSummary(latestRun.get(jd.id)!)}</span>
                        </p>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {jd.edited_at && <Chip tone="brand">Edited</Chip>}
                      {jd.deadline_changed_at && <Chip tone="amber">Deadline changed</Chip>}
                      {closed && <Chip>Closed</Chip>}
                      <button className="btn-secondary" onClick={() => { setNotice(null); setOpen(isOpen && open?.mode === "edit" ? null : { id: jd.id, mode: "edit" }); }}>
                        <Pencil className="size-4" aria-hidden /> Edit
                      </button>
                      <button className="btn-ghost text-rose-600" onClick={() => { setNotice(null); setOpen(isOpen && open?.mode === "remove" ? null : { id: jd.id, mode: "remove" }); }}>
                        <Trash2 className="size-4" aria-hidden /> Remove
                      </button>
                    </div>
                  </div>
                  {isOpen && (
                    <div className="mt-4">
                      {open.mode === "edit" ? (
                        <EditPanel jd={jd} onDone={(saved) => done(saved, "Job details saved.")} />
                      ) : (
                        <RemovePanel jd={jd} counts={c} onDone={(removed) => done(removed, "Job removed.")} />
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {shown.length === 0 && <p className="p-6 text-center text-sm text-slate-500">No job matches &ldquo;{query}&rdquo;.</p>}
        </div>
      )}
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["admin"]}>
      <JobsAdminPage />
    </RequireRole>
  );
}
