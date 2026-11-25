"use client";

import { Clock3, Inbox, Send, Undo2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ApplicationCard } from "@/components/ApplicationCard";
import { DeadlineEditor } from "@/components/DeadlineEditor";
import { CardSkeletons, EmptyState, ErrorBox, PageHeader, StatCard } from "@/components/ui";
import { RequireRole, useAuth } from "@/lib/auth";
import type { Application, ApplicationStatus, JDSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";

type Filter = "all" | ApplicationStatus;

function ApplicationsPage() {
  const { profile } = useAuth();
  const recruiter = profile?.role === "recruiter";
  const applications = useApi<Application[]>("/applications");
  const jds = useApi<JDSummary[]>("/jds");
  const [jdId, setJdId] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("jd");
    if (requested) setJdId(requested);
  }, []);

  // Statuses change with time (pending → sent), so refresh every minute while open.
  useEffect(() => {
    const id = window.setInterval(() => void applications.refresh(), 60_000);
    return () => window.clearInterval(id);
  }, [applications.refresh]); // eslint-disable-line react-hooks/exhaustive-deps

  const all = applications.data ?? [];
  const forJd = jdId ? all.filter((a) => a.jd_id === jdId) : all;
  const shown = filter === "all" ? forJd : forJd.filter((a) => a.status === filter);
  const counts = useMemo(() => {
    const c = { pending: 0, submitted: 0, withdrawn: 0 };
    forJd.forEach((a) => (c[a.status] += 1));
    return c;
  }, [forJd]);
  const jobsWithApplications = (jds.data ?? []).filter((jd) => all.some((a) => a.jd_id === jd.id));
  const myJobs = recruiter ? (jds.data ?? []).filter((jd) => jd.can_edit_deadline) : [];

  return (
    <>
      <PageHeader
        title="Applications"
        subtitle={
          recruiter
            ? "Applications to your jobs. You see each one once the student's withdraw window has closed and it has been sent."
            : "Every auto-apply application. Pending ones are sent automatically when the student's withdraw window closes."
        }
        actions={
          jobsWithApplications.length > 0 && (
            <select className="input w-64" value={jdId} onChange={(e) => setJdId(e.target.value)} aria-label="Filter by job">
              <option value="">All jobs</option>
              {jobsWithApplications.map((jd) => (
                <option key={jd.id} value={jd.id}>
                  {[jd.company, jd.role].filter(Boolean).join(" · ") || jd.id.slice(0, 8)}
                </option>
              ))}
            </select>
          )
        }
      />
      <ErrorBox message={applications.error?.message} />

      {recruiter && myJobs.length > 0 && (
        <section className="card mb-6 space-y-3">
          <p className="font-semibold text-slate-900">Your jobs</p>
          <ul className="divide-y divide-slate-100">
            {myJobs.map((jd) => (
              <li key={jd.id} className="space-y-1 py-3 first:pt-0 last:pb-0">
                <p className="font-medium text-slate-800">{[jd.company, jd.role].filter(Boolean).join(" · ") || "Untitled job"}</p>
                <DeadlineEditor jd={jd} onChanged={() => { void jds.refresh(); void applications.refresh(); }} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {!recruiter && (
        <div className="mb-6 grid gap-3 sm:grid-cols-3">
          <button onClick={() => setFilter(filter === "pending" ? "all" : "pending")} className="text-left" aria-pressed={filter === "pending"}>
            <StatCard label="Pending · can still be withdrawn" value={counts.pending} icon={Clock3} tone="amber" />
          </button>
          <button onClick={() => setFilter(filter === "submitted" ? "all" : "submitted")} className="text-left" aria-pressed={filter === "submitted"}>
            <StatCard label="Sent to company" value={counts.submitted} icon={Send} tone="green" />
          </button>
          <button onClick={() => setFilter(filter === "withdrawn" ? "all" : "withdrawn")} className="text-left" aria-pressed={filter === "withdrawn"}>
            <StatCard label="Withdrawn by student" value={counts.withdrawn} icon={Undo2} tone="slate" />
          </button>
        </div>
      )}
      {filter !== "all" && (
        <p className="mb-3 text-sm text-slate-500">
          Showing {filter} only.{" "}
          <button className="font-medium text-brand-700 hover:underline" onClick={() => setFilter("all")}>
            Show all
          </button>
        </p>
      )}

      {applications.loading && !applications.data ? (
        <div className="grid gap-4 md:grid-cols-2">
          <CardSkeletons count={4} />
        </div>
      ) : shown.length === 0 ? (
        <EmptyState icon={Inbox} title={recruiter ? "No applications sent to you yet" : "No applications here"}>
          {recruiter
            ? "Applications appear once students apply (or auto-apply applies for them when a job is posted) and their withdraw window closes."
            : "Auto-apply runs by itself when a job is uploaded; you can also run it again from the Rank candidates page."}
        </EmptyState>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {shown.map((a) => (
            <ApplicationCard key={a.id} app={a} viewer={recruiter ? "recruiter" : "staff"} />
          ))}
        </div>
      )}
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["officer", "admin", "recruiter"]}>
      <ApplicationsPage />
    </RequireRole>
  );
}
