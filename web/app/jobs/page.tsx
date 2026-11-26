"use client";

import { Briefcase, CircleCheck, CircleX, Database, RefreshCw, Rocket, Sparkles, Trophy, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AutoApplyHistory } from "@/components/AutoApplyHistory";
import { AutoApplyPanel } from "@/components/AutoApplyPanel";
import { MatchResultCard } from "@/components/MatchResultCard";
import { PolicyPicker } from "@/components/PolicyPicker";
import { DeadlineEditor } from "@/components/DeadlineEditor";
import { CardSkeletons, Chip, EmptyState, ErrorBox, PageHeader, Spinner, StatCard, errorText } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireRole } from "@/lib/auth";
import type { JDSummary, PolicySummary, RankedResponse } from "@/lib/types";
import { invalidate, useApi } from "@/lib/useApi";

type Filter = "all" | "eligible" | "ineligible";

function JobCard({ jd, selected, onSelect }: { jd: JDSummary; selected: boolean; onSelect: () => void }) {
  return (
    <button
      onClick={onSelect}
      aria-pressed={selected}
      className={`card group flex flex-col p-4 text-left transition hover:border-brand-300 hover:shadow-md ${
        selected ? "border-brand-500 ring-2 ring-brand-100" : ""
      }`}
    >
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-base font-semibold text-brand-700">
          {(jd.company ?? "?").charAt(0)}
        </span>
        <div className="min-w-0">
          <p className="truncate font-medium text-slate-900">{jd.company ?? "Unknown company"}</p>
          <p className="truncate text-sm text-slate-500">{jd.role ?? "Role not stated"}</p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1">
        {jd.required_skills.slice(0, 4).map((s, i) => (
          <Chip key={`${s}-${i}`}>{s}</Chip>
        ))}
        {jd.required_skills.length > 4 && <Chip>+{jd.required_skills.length - 4}</Chip>}
      </div>
    </button>
  );
}

function Results({ jd, policyId }: { jd: JDSummary; policyId: string }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [runsVersion, setRunsVersion] = useState(0); // bumped after a manual run: reloads the history
  const path = `/jds/${jd.id}/ranked?policy_id=${encodeURIComponent(policyId)}`;
  const { data, error, loading, refresh } = useApi<RankedResponse>(path, { revalidate: false });
  const [rescoring, setRescoring] = useState(false);
  const [rescoreError, setRescoreError] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<{ ai: number; cached: number } | null>(null);

  // Re-score bypasses the server's score cache (one AI call per eligible student), then the
  // normal ranking is reloaded, which now reads the fresh scores from the cache.
  async function rescore() {
    setRescoring(true);
    setRescoreError(null);
    try {
      const fresh = await api<RankedResponse>(`${path}&refresh=true`);
      setLastRun({ ai: fresh.ai_calls, cached: fresh.cached_scores });
      await refresh();
    } catch (e) {
      setRescoreError(errorText(e));
    } finally {
      setRescoring(false);
    }
  }

  const stats = useMemo(() => {
    if (!data) return null;
    const top = data.eligible.find((r) => r.score_breakdown?.score != null);
    return {
      eligible: data.eligible.length,
      ineligible: data.ineligible.length,
      autoApply: data.eligible.filter((r) => r.auto_apply_recommended).length,
      top: top?.score_breakdown?.score ?? null,
    };
  }, [data]);

  if (loading && !data) {
    return (
      <div className="space-y-4">
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Spinner /> Checking eligibility and scoring resumes. Stored scores are reused; only new resume/JD pairs need an AI call.
        </p>
        <CardSkeletons count={3} />
      </div>
    );
  }
  if (error && !data) return <ErrorBox message={error.message} />;
  if (!data || !stats) return null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">
          {jd.company} <span className="font-normal text-slate-500">· {jd.role}</span>
        </h2>
        <div className="flex flex-wrap gap-2">
          <button
            className="btn-secondary"
            onClick={() => {
              setLastRun(null);
              void refresh();
            }}
            disabled={loading || rescoring}
            title="Re-check eligibility; scores come from the cache, so no AI calls"
          >
            {loading && !rescoring ? <Spinner /> : <RefreshCw className="size-4" aria-hidden />} Re-run
          </button>
          <button
            className="btn-secondary"
            onClick={rescore}
            disabled={loading || rescoring}
            title="Ignore stored scores and ask the AI again for every eligible student"
          >
            {rescoring ? <Spinner /> : <Sparkles className="size-4" aria-hidden />} Re-score with AI
          </button>
        </div>
      </div>
      <p className="-mt-3 flex items-center gap-1.5 text-xs text-slate-500">
        <Database className="size-3.5" aria-hidden />
        {(() => {
          const ai = lastRun?.ai ?? data.ai_calls;
          const cached = lastRun ? 0 : data.cached_scores;
          if (ai === 0 && cached === 0) return "No eligible student needed scoring.";
          if (ai === 0) return `All ${cached} scores from the score cache · no AI calls`;
          if (cached === 0) return `${ai} score${ai === 1 ? "" : "s"} computed by AI and cached for next time`;
          return `${cached} scores from cache · ${ai} new AI call${ai === 1 ? "" : "s"}`;
        })()}
      </p>
      <ErrorBox message={rescoreError} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Eligible" value={stats.eligible} icon={CircleCheck} tone="green" />
        <StatCard label="Not eligible" value={stats.ineligible} icon={CircleX} tone="red" />
        <StatCard label={`Qualify for auto-apply (≥ ${data.auto_apply_threshold})`} value={stats.autoApply} icon={Rocket} tone="brand" />
        <StatCard label="Top score" value={stats.top !== null ? stats.top.toFixed(1) : "—"} icon={Trophy} tone="amber" />
      </div>
      <ErrorBox message={error?.message} />
      <AutoApplyPanel jd={jd} policyId={policyId} threshold={data.auto_apply_threshold} onRan={() => setRunsVersion((v) => v + 1)} />
      <AutoApplyHistory key={runsVersion} jdId={jd.id} />

      <div className="inline-flex rounded-lg border border-slate-200 bg-surface p-1 text-sm shadow-sm" role="tablist">
        {(
          [
            ["all", `All (${stats.eligible + stats.ineligible})`],
            ["eligible", `Eligible (${stats.eligible})`],
            ["ineligible", `Not eligible (${stats.ineligible})`],
          ] as [Filter, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={filter === key}
            onClick={() => setFilter(key)}
            className={`rounded-md px-3 py-1.5 font-medium transition ${filter === key ? "bg-brand-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"}`}
          >
            {label}
          </button>
        ))}
      </div>

      {filter !== "ineligible" && (
        <section className="space-y-3">
          {filter === "all" && <p className="eyebrow">Ranked by score</p>}
          {data.eligible.length === 0 ? (
            <p className="text-sm text-slate-500">No student meets every rule for this job.</p>
          ) : (
            data.eligible.map((r, i) => (
              <MatchResultCard key={r.student_id} result={r} threshold={data.auto_apply_threshold} rank={i + 1} />
            ))
          )}
        </section>
      )}
      {filter !== "eligible" && data.ineligible.length > 0 && (
        <section className="space-y-3">
          {filter === "all" && <p className="eyebrow pt-2">Not eligible</p>}
          {data.ineligible.map((r) => (
            <MatchResultCard key={r.student_id} result={r} threshold={data.auto_apply_threshold} />
          ))}
        </section>
      )}
    </div>
  );
}

function RankPage() {
  const policies = useApi<PolicySummary[]>("/policies");
  const jds = useApi<JDSummary[]>("/jds");
  const [policyId, setPolicyId] = useState("");
  const [selectedJd, setSelectedJd] = useState<JDSummary | null>(null);

  useEffect(() => {
    if (!policyId && policies.data?.length) setPolicyId(policies.data[0].id);
  }, [policies.data, policyId]);

  const loading = (policies.loading && !policies.data) || (jds.loading && !jds.data);
  const error = policies.error ?? jds.error;

  return (
    <>
      <PageHeader
        title="Rank candidates"
        subtitle="Pick a job. Students are checked against fixed eligibility rules first; only eligible students are scored on the JD's skills."
        actions={policies.data && policies.data.length > 0 ? <PolicyPicker policies={policies.data} value={policyId} onChange={setPolicyId} /> : undefined}
      />
      <ErrorBox message={error?.message} />

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <CardSkeletons count={3} />
        </div>
      ) : policies.data?.length === 0 ? (
        <EmptyState icon={Briefcase} title="No placement policy yet">
          Upload one on the <Link href="/upload" className="font-medium text-brand-600 hover:underline">Upload</Link> page first.
        </EmptyState>
      ) : jds.data?.length === 0 ? (
        <EmptyState icon={Briefcase} title="No job descriptions yet">
          Add one on the <Link href="/upload" className="font-medium text-brand-600 hover:underline">Upload</Link> page.
        </EmptyState>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {jds.data?.map((jd) => (
            <JobCard key={jd.id} jd={jd} selected={selectedJd?.id === jd.id} onSelect={() => setSelectedJd(jd)} />
          ))}
        </div>
      )}

      <div className="mt-10">
        {selectedJd && (
          <div className="card mb-6 p-4">
            <DeadlineEditor
              key={selectedJd.id}
              jd={jds.data?.find((j) => j.id === selectedJd.id) ?? selectedJd}
              onChanged={() => {
                invalidate("/me/jobs", "/applications");
                void jds.refresh();
              }}
            />
          </div>
        )}
        {selectedJd && policyId ? (
          <Results key={`${selectedJd.id}-${policyId}`} jd={selectedJd} policyId={policyId} />
        ) : (
          !loading &&
          (jds.data?.length ?? 0) > 0 && (
            <EmptyState icon={Users} title="Select a job to rank students">
              Results include each student&apos;s score, the skills they match or miss, and the resume quotes behind them.
            </EmptyState>
          )
        )}
      </div>
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["officer", "admin"]}>
      <RankPage />
    </RequireRole>
  );
}
