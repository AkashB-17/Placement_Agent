"use client";

import {
  ArrowLeft,
  ArrowUpDown,
  Briefcase,
  CircleCheck,
  CircleX,
  Clock3,
  FileText,
  Lightbulb,
  ListChecks,
  Search,
  Send,
  Sparkles,
  Target,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ApplicationCard } from "./ApplicationCard";
import { MatchResultCard } from "./MatchResultCard";
import { NotLinked } from "./NotLinked";
import { Chip, EmptyState, ErrorBox, Skeleton, Spinner, display, errorText, type Tone } from "./ui";
import { api } from "@/lib/api";
import { formatDateTime, timeAgo, timeUntil, useNow } from "@/lib/time";
import type { Application, CvTipsResponse, JDDetail, MatchResult, MyJob, MyJobsResponse, StudentDetail } from "@/lib/types";
import { invalidate, useApi } from "@/lib/useApi";

type StatusFilter = "all" | "eligible" | "applied" | "not_eligible" | "closed";
type Sort = "newest" | "closing";
type DetailTab = "description" | "eligibility" | "match";
const DAY_MS = 24 * 60 * 60 * 1000;

/** One label per job, in priority order: an application beats eligibility, closed beats both. */
function jobStatus(job: MyJob): { key: StatusFilter; label: string; tone: Tone } {
  if (job.application) {
    if (job.application.status === "submitted") return { key: "applied", label: "Sent to company", tone: "green" };
    if (job.application.status === "withdrawn") return { key: "applied", label: "Withdrawn", tone: "slate" };
    return { key: "applied", label: "Applied", tone: "brand" };
  }
  if (job.closed) return { key: "closed", label: "Applications closed", tone: "slate" };
  return job.eligibility.eligible
    ? { key: "eligible", label: "Eligible", tone: "green" }
    : { key: "not_eligible", label: "Not eligible", tone: "red" };
}

function Deadline({ job, now }: { job: MyJob; now: number }) {
  if (job.closed) return <span className="text-slate-400">Closed</span>;
  if (!job.deadline_at) return <span className="text-slate-400">Rolling deadline</span>;
  const urgent = new Date(job.deadline_at).getTime() - now < DAY_MS;
  return <span className={urgent ? "font-medium text-rose-600" : "text-slate-500"}>Closes {timeUntil(job.deadline_at, now)}</span>;
}

function CompanyMark({ name, size = "size-10 text-base" }: { name: string | null; size?: string }) {
  return (
    <span className={`flex shrink-0 items-center justify-center rounded-lg bg-brand-50 font-semibold text-brand-700 ${size}`}>
      {(name ?? "?").charAt(0)}
    </span>
  );
}

// ── Detail tabs ─────────────────────────────────────────────────────────────

function DescriptionTab({ jobId }: { jobId: string }) {
  const { data, error, loading } = useApi<JDDetail>(`/jds/${jobId}`);
  if (loading && !data) return <div className="space-y-2"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-5/6" /></div>;
  if (error && !data) return <ErrorBox message={error.message} />;
  if (!data) return null;
  const r = data.requirements;
  return (
    <div className="space-y-6">
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
        <dt className="text-slate-500">CTC / stipend</dt><dd>{display(r.ctc)}</dd>
        <dt className="text-slate-500">Experience</dt><dd>{display(r.experience_required)}</dd>
        <dt className="text-slate-500">Required skills</dt><dd>{display(r.required_skills)}</dd>
        <dt className="text-slate-500">Preferred skills</dt><dd>{display(r.preferred_skills)}</dd>
      </dl>
      <div>
        <p className="eyebrow mb-2">Full job description</p>
        <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-4 text-sm leading-relaxed whitespace-pre-line text-slate-700">
          {data.source_text}
        </div>
      </div>
    </div>
  );
}

function EligibilityTab({ job }: { job: MyJob }) {
  const { data } = useApi<JDDetail>(`/jds/${job.id}`);
  const r = data?.requirements;
  const failedSources = new Map(job.eligibility.failed_rules.map((f) => [`${f.rule}-${f.source}`, f]));
  return (
    <div className="space-y-5">
      {job.eligibility.eligible ? (
        <p className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          <CircleCheck className="size-4" aria-hidden /> You meet every rule the placement policy and this job state.
        </p>
      ) : (
        <div className="space-y-2">
          <p className="text-sm font-medium text-slate-800">You don&apos;t meet these rules:</p>
          <ul className="space-y-2">
            {job.eligibility.failed_rules.map((f) => (
              <li key={`${f.rule}-${f.source}`} className="flex gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm">
                <CircleX className="mt-0.5 size-4 shrink-0 text-rose-500" aria-hidden />
                <span>
                  <span className="text-slate-800 first-letter:uppercase">{f.description}</span>
                  <span className="text-slate-500"> · you have {display(f.student_value)}, needs {display(f.required_value)}</span>
                  <span className="ml-1"><Chip>{f.source === "jd" ? "from this job" : "from the placement policy"}</Chip></span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {r && (
        <div>
          <p className="eyebrow mb-2">What this job asks for</p>
          <ul className="space-y-1.5 text-sm text-slate-700">
            <li>Minimum CGPA: {r.min_cgpa_override ?? "as per the placement policy"}</li>
            <li>Branches: {r.allowed_branches.length ? r.allowed_branches.join(", ") : "any (per the placement policy)"}</li>
            <li>Batches: {r.allowed_batches.length ? r.allowed_batches.join(", ") : "any (per the placement policy)"}</li>
            <li>Deadline: {display(r.deadline)}</li>
          </ul>
          {failedSources.size === 0 && (
            <p className="mt-2 text-xs text-slate-400">Eligibility is checked by fixed rules against your official record, never by AI.</p>
          )}
        </div>
      )}
    </div>
  );
}

const withPolicy = (path: string, policyId: string | null) =>
  policyId ? `${path}?policy_id=${encodeURIComponent(policyId)}` : path;

/** Gaps come from the verified score (code); the AI only suggests what to do about each. */
function CvTipsPanel({ job, policyId, missingRequired, missingPreferred }: {
  job: MyJob;
  policyId: string | null;
  missingRequired: string[];
  missingPreferred: string[];
}) {
  const [tips, setTips] = useState<CvTipsResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const missing = missingRequired.length + missingPreferred.length;

  async function load() {
    setBusy(true);
    setError(null);
    try {
      setTips(await api<CvTipsResponse>(withPolicy(`/me/jobs/${job.id}/cv-tips`, policyId), { method: "POST" }));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  if (missing === 0) return null;
  return (
    <section className="space-y-3 rounded-xl border border-amber-200 bg-amber-50/40 p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="flex items-center gap-2 font-semibold text-slate-900">
            <Lightbulb className="size-4 text-amber-600" aria-hidden /> Improve your CV for this job
          </h3>
          <p className="mt-1 text-sm text-slate-600">
            Your CV doesn&apos;t show {missing} of the skills this job asks for:
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {missingRequired.map((s) => <Chip key={`r-${s}`} tone="red">{s} · required</Chip>)}
            {missingPreferred.map((s) => <Chip key={`p-${s}`} tone="amber">{s} · preferred</Chip>)}
          </div>
        </div>
        {!tips && (
          <button className="btn-secondary" onClick={load} disabled={busy}>
            {busy ? <Spinner /> : <Sparkles className="size-4" aria-hidden />}
            {busy ? "Thinking…" : "Suggest changes"}
          </button>
        )}
      </div>
      <ErrorBox message={error} />
      {tips && (
        <ul className="space-y-2.5">
          {tips.tips.map((tip) => (
            <li key={tip.skill} className="rounded-lg border border-slate-200 bg-surface p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-900">{tip.skill}</span>
                <Chip tone={tip.required ? "red" : "amber"}>{tip.required ? "Required" : "Preferred"}</Chip>
                <Chip tone={tip.kind === "surface" ? "brand" : "slate"}>
                  {tip.kind === "surface" ? "You may already have this" : "Skill to build"}
                </Chip>
              </div>
              {tip.related_quote && (
                <p className="mt-2 border-l-2 border-brand-200 pl-3 text-sm text-slate-500 italic">
                  From your CV: &ldquo;{tip.related_quote}&rdquo;
                </p>
              )}
              <p className="mt-2 text-sm text-slate-700">{tip.suggestion}</p>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-slate-500">
        Only add skills you have really used: recruiters check. The gaps come from a fixed check of your CV; the suggestions are
        written by AI. After editing, upload the new CV under{" "}
        <Link href="/me/profile" className="font-medium text-brand-700 hover:underline">Profile &amp; CV</Link> and check your match again.
      </p>
    </section>
  );
}

function MatchTab({ job, student, policyId }: { job: MyJob; student: StudentDetail; policyId: string | null }) {
  const [result, setResult] = useState<MatchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function check() {
    if (!policyId) return;
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api<MatchResult>("/match", {
          method: "POST",
          body: JSON.stringify({ jd_id: job.id, student_id: student.id, policy_id: policyId }),
        }),
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  if (!student.has_resume) {
    return (
      <EmptyState icon={FileText} title="Upload your CV to see your match">
        Your score compares the skills in your CV with this job&apos;s. <Link href="/me/profile" className="font-medium text-brand-700 hover:underline">Upload it under Profile &amp; CV</Link>.
      </EmptyState>
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="flex-1 text-sm text-slate-600">
          See which of this job&apos;s skills your CV proves, with the exact sentence for each. Scores are worked out by a fixed formula.
        </p>
        <button className="btn" onClick={check} disabled={busy || !policyId}>
          {busy ? <Spinner /> : <Target className="size-4" aria-hidden />}
          {busy ? "Checking…" : result ? "Check again" : "Check my match"}
        </button>
      </div>
      <ErrorBox message={error} />
      {result && <MatchResultCard result={result} showName={false} />}
      {result?.eligibility.eligible && result.score_breakdown && (
        <CvTipsPanel
          job={job}
          policyId={policyId}
          missingRequired={result.score_breakdown.missing_required}
          missingPreferred={result.score_breakdown.missing_preferred}
        />
      )}
    </div>
  );
}

/** Apply button under the status chip; disabled with the reason when applying isn't possible. */
function ApplyAction({ job, student, policyId, onApplied }: {
  job: MyJob;
  student: StudentDetail;
  policyId: string | null;
  onApplied: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setConfirming(false);
    setError(null);
  }, [job.id]);

  // A withdrawn application can be re-applied by the student (never by auto-apply).
  const reapply = job.application?.status === "withdrawn";
  if (job.application && !reapply) return null;
  const blocked = job.closed
    ? "Applications for this job are closed."
    : !job.eligibility.eligible
      ? "You don't meet this job's eligibility rules: see Eligibility criteria."
      : !student.has_resume
        ? "Upload your CV under Profile & CV before applying."
        : !policyId
          ? "The placement office hasn't published a policy yet."
          : null;

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      await api<Application>(withPolicy(`/me/jobs/${job.id}/apply`, policyId), { method: "POST" });
      setConfirming(false);
      invalidate("/me/applications", "/me/notifications");
      onApplied();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-2">
      {!confirming && (
        <button className="btn" disabled={!!blocked} title={blocked ?? undefined} onClick={() => setConfirming(true)}>
          <Send className="size-4" aria-hidden /> {reapply ? "Apply again" : "Apply"}
        </button>
      )}
      {!student.has_resume && job.eligibility.eligible && !job.closed && (
        <p className="text-xs text-slate-500">
          <Link href="/me/profile" className="font-medium text-brand-700 hover:underline">Upload your CV</Link> to apply.
        </p>
      )}
      {confirming && (
        <div className="max-w-xs space-y-2 rounded-lg border border-brand-200 bg-brand-50/60 p-3 text-sm">
          <p className="text-slate-700">
            {reapply ? "Apply again" : "Apply"} with your current CV and match score? It&apos;s sent to the company after a withdraw window; you
            can withdraw until then.
          </p>
          <div className="flex gap-2">
            <button className="btn" onClick={apply} disabled={busy}>
              {busy ? <Spinner /> : <Send className="size-4" aria-hidden />} {busy ? "Applying…" : "Yes, apply"}
            </button>
            <button className="btn-ghost" onClick={() => setConfirming(false)} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}
      <ErrorBox message={error} />
    </div>
  );
}

function JobDetail({
  job,
  student,
  policyId,
  application,
  onChanged,
  onBack,
}: {
  job: MyJob;
  student: StudentDetail;
  policyId: string | null;
  application: Application | undefined;
  onChanged: () => void;
  onBack: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>("description");
  const now = useNow();
  const status = jobStatus(job);
  useEffect(() => setTab("description"), [job.id]);

  const tabs: [DetailTab, string, typeof FileText][] = [
    ["description", "Job description", FileText],
    ["eligibility", "Eligibility criteria", ListChecks],
    ["match", "My match", Sparkles],
  ];

  return (
    <div className="space-y-5">
      <button className="btn-ghost -ml-2 lg:hidden" onClick={onBack}>
        <ArrowLeft className="size-4" aria-hidden /> All jobs
      </button>
      <div className="flex flex-wrap items-start gap-4">
        <CompanyMark name={job.company} size="size-14 text-xl" />
        <div className="min-w-0 flex-1">
          <h2 className="text-xl font-semibold text-slate-900">{job.role ?? "Role not stated"}</h2>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm text-slate-600">
            <span className="font-medium text-slate-800">{job.company ?? "Unknown company"}</span>
            {job.ctc && <><span className="text-slate-300">|</span><span>{job.ctc}</span></>}
            <span className="text-slate-300">|</span>
            <Deadline job={job} now={now} />
          </p>
          {job.deadline && <p className="mt-0.5 text-xs text-slate-400">Deadline as posted: {job.deadline}</p>}
        </div>
        <div className="flex flex-col items-end gap-2">
          <Chip tone={status.tone}>{status.label}</Chip>
          <ApplyAction job={job} student={student} policyId={policyId} onApplied={onChanged} />
        </div>
      </div>

      {application && (
        <div className="space-y-2">
          <p className="flex items-center gap-1.5 text-sm text-slate-600">
            <Clock3 className="size-4 text-brand-500" aria-hidden />
            {application.source === "manual" ? "You applied" : "You applied through auto-apply"} on{" "}
            {formatDateTime(application.created_at)} with the CV you had then.
          </p>
          <ApplicationCard app={application} viewer="student" onChanged={onChanged} />
        </div>
      )}

      <div className="flex gap-1 border-b border-slate-200" role="tablist">
        {tabs.map(([key, label, Icon]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`-mb-px flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition ${
              tab === key ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </button>
        ))}
      </div>
      {tab === "description" && <DescriptionTab jobId={job.id} />}
      {tab === "eligibility" && <EligibilityTab job={job} />}
      {tab === "match" && <MatchTab key={job.id} job={job} student={student} policyId={policyId} />}
    </div>
  );
}

// ── Page ────────────────────────────────────────────────────────────────────

/** The student job board: filters, job list and job detail (GET /me/jobs). */
export function JobBoard() {
  const me = useApi<StudentDetail>("/students/me");
  const board = useApi<MyJobsResponse>(me.data ? "/me/jobs" : null);
  const applications = useApi<Application[]>(me.data ? "/me/applications" : null);
  const now = useNow();

  const [tab, setTab] = useState<"all" | "applied">("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [sort, setSort] = useState<Sort>("newest");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showDetailOnMobile, setShowDetailOnMobile] = useState(false);

  const jobs = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = (board.data?.jobs ?? []).filter((j) => {
      if (tab === "applied" && !j.application) return false;
      if (status !== "all" && jobStatus(j).key !== status) return false;
      return !q || [j.company ?? "", j.role ?? ""].some((v) => v.toLowerCase().includes(q));
    });
    const posted = (j: MyJob) => (j.posted_at ? new Date(j.posted_at).getTime() : 0);
    const closes = (j: MyJob) => (j.closed ? Infinity : j.deadline_at ? new Date(j.deadline_at).getTime() : Number.MAX_SAFE_INTEGER);
    return [...list].sort((a, b) => (sort === "newest" ? posted(b) - posted(a) : closes(a) - closes(b)));
  }, [board.data, tab, status, sort, query]);

  const filtersActive = status !== "all" || sort !== "newest" || query.trim() !== "";
  const appliedCount = board.data?.jobs.filter((j) => j.application).length ?? 0;
  const selected = jobs.find((j) => j.id === selectedId) ?? jobs[0] ?? null;
  const applicationFor = (jdId: string) => applications.data?.find((a) => a.jd_id === jdId);

  function refreshAfterChange() {
    invalidate("/me/notifications");
    void board.refresh();
    void applications.refresh();
  }

  if (me.error?.status === 404) return <NotLinked />;

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="card flex flex-wrap items-end gap-3 p-3">
        <label className="text-sm">
          <span className="mb-1 block text-xs font-medium text-slate-500">Status</span>
          <select className="input w-44 py-1.5" value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
            <option value="all">All</option>
            <option value="eligible">Eligible</option>
            <option value="applied">Applied</option>
            <option value="not_eligible">Not eligible</option>
            <option value="closed">Closed</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 flex items-center gap-1 text-xs font-medium text-slate-500"><ArrowUpDown className="size-3" aria-hidden /> Sort by</span>
          <select className="input w-44 py-1.5" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="newest">Newest first</option>
            <option value="closing">Closing soon</option>
          </select>
        </label>
        {filtersActive && (
          <button className="btn-ghost text-brand-700" onClick={() => { setStatus("all"); setSort("newest"); setQuery(""); }}>
            Clear all filters
          </button>
        )}
        <div className="relative ml-auto w-full sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
          <input className="input pl-9" placeholder="Search by job title or company" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search jobs" />
        </div>
      </div>
      <ErrorBox message={me.error?.message ?? board.error?.message} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(300px,380px)_minmax(0,1fr)]">
        {/* List */}
        <section className={`card min-w-0 flex-col p-0 lg:max-h-[calc(100vh-13rem)] ${showDetailOnMobile ? "hidden lg:flex" : "flex"}`}>
          <div className="flex border-b border-slate-200" role="tablist">
            {([["all", "All jobs", board.data?.jobs.length], ["applied", "Applied jobs", appliedCount]] as const).map(([key, label, count]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={`-mb-px flex-1 border-b-2 px-3 py-3 text-sm font-medium transition ${
                  tab === key ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"
                }`}
              >
                {label}{count !== undefined && <span className="ml-1 text-xs text-slate-400">({count})</span>}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto">
            {board.loading && !board.data ? (
              <div className="space-y-3 p-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-16 w-full" />)}</div>
            ) : jobs.length === 0 ? (
              <div className="p-6">
                <EmptyState icon={Briefcase} title={tab === "applied" ? "No applications yet" : "No jobs match"}>
                  {tab === "applied" ? "Jobs you're applied to through auto-apply show up here." : "Try clearing the filters or the search."}
                </EmptyState>
              </div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {jobs.map((job) => {
                  const s = jobStatus(job);
                  const active = selected?.id === job.id;
                  return (
                    <li key={job.id}>
                      <button
                        onClick={() => { setSelectedId(job.id); setShowDetailOnMobile(true); }}
                        aria-current={active ? "true" : undefined}
                        className={`flex w-full gap-3 px-4 py-3.5 text-left transition hover:bg-slate-50 ${active ? "bg-brand-50/60 shadow-[inset_3px_0_0] shadow-brand-600" : ""}`}
                      >
                        <CompanyMark name={job.company} />
                        <span className="min-w-0 flex-1">
                          <span className="line-clamp-2 block font-semibold leading-snug text-slate-900">{job.role ?? "Role not stated"}</span>
                          <span className="block truncate text-sm text-slate-600">{job.company ?? "Unknown company"}{job.ctc ? ` · ${job.ctc}` : ""}</span>
                          <span className="mt-0.5 block text-xs">
                            {job.posted_at && <span className="text-slate-400">{timeAgo(job.posted_at, now)} · </span>}
                            <Deadline job={job} now={now} />
                          </span>
                        </span>
                        <span className="shrink-0 self-start"><Chip tone={s.tone}>{s.label}</Chip></span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </section>

        {/* Detail */}
        <section className={`card min-w-0 lg:max-h-[calc(100vh-13rem)] lg:overflow-y-auto ${showDetailOnMobile ? "block" : "hidden lg:block"}`}>
          {selected && me.data ? (
            <JobDetail
              job={selected}
              student={me.data}
              policyId={board.data?.policy_id ?? null}
              application={applicationFor(selected.id)}
              onChanged={refreshAfterChange}
              onBack={() => setShowDetailOnMobile(false)}
            />
          ) : (
            !board.loading && <EmptyState icon={Briefcase} title="Select a job to see its details" />
          )}
        </section>
      </div>
    </div>
  );
}
