"use client";

import { Briefcase, GraduationCap, Link2Off, Search } from "lucide-react";
import { useEffect, useState } from "react";

import { MatchResultCard } from "@/components/MatchResultCard";
import { PolicyPicker } from "@/components/PolicyPicker";
import { Avatar, CardSkeletons, Chip, Chips, EmptyState, ErrorBox, PageHeader, Spinner, errorText } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireRole } from "@/lib/auth";
import type { JDSummary, MatchResult, PolicySummary, StudentDetail } from "@/lib/types";
import { useApi } from "@/lib/useApi";

function MyPage() {
  const me = useApi<StudentDetail>("/students/me");
  const policies = useApi<PolicySummary[]>("/policies");
  const jds = useApi<JDSummary[]>("/jds");
  const [policyId, setPolicyId] = useState("");
  const [results, setResults] = useState<Record<string, MatchResult>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!policyId && policies.data?.length) setPolicyId(policies.data[0].id);
  }, [policies.data, policyId]);

  async function check(jdId: string) {
    if (!me.data) return;
    setBusy(jdId);
    setError(null);
    try {
      const result = await api<MatchResult>("/match", {
        method: "POST",
        body: JSON.stringify({ jd_id: jdId, student_id: me.data.id, policy_id: policyId }),
      });
      setResults((r) => ({ ...r, [jdId]: result }));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  if (me.error?.status === 404) {
    return (
      <>
        <PageHeader title="My placements" />
        <EmptyState icon={Link2Off} title="Your account isn't linked to a student record yet">
          Ask the placement office to add you using the email you sign in with.
        </EmptyState>
      </>
    );
  }

  const profile = me.data?.profile;
  return (
    <>
      <PageHeader
        title="My placements"
        subtitle="Check whether you're eligible for each job and how your resume matches its skills."
        actions={policies.data && policies.data.length > 1 ? <PolicyPicker policies={policies.data} value={policyId} onChange={setPolicyId} /> : undefined}
      />
      <ErrorBox message={me.error?.message ?? policies.error?.message ?? jds.error?.message ?? error} />

      {me.loading && !me.data ? (
        <CardSkeletons count={1} />
      ) : (
        profile && (
          <section className="card mb-8 flex flex-col gap-5 sm:flex-row sm:items-center">
            <div className="flex items-center gap-4">
              <Avatar name={profile.name} className="size-14 text-lg" />
              <div>
                <p className="text-lg font-semibold">{profile.name}</p>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  <Chip tone="brand" icon={GraduationCap}>
                    {profile.branch} · {profile.batch}
                  </Chip>
                  <Chip>CGPA {profile.cgpa.toFixed(2)}</Chip>
                  <Chip tone={profile.active_backlogs > 0 ? "red" : "slate"}>{profile.active_backlogs} active backlogs</Chip>
                  {profile.is_placed && <Chip tone="green">Placed</Chip>}
                </div>
              </div>
            </div>
            <div className="sm:ml-auto sm:max-w-md">
              <p className="eyebrow mb-2">Skills in your resume</p>
              <Chips items={me.data?.parsed_resume.skills ?? []} tone="slate" empty="None found" />
            </div>
          </section>
        )
      )}

      <h2 className="mb-3 text-lg font-semibold">Open positions</h2>
      {jds.loading && !jds.data ? (
        <div className="space-y-3">
          <CardSkeletons count={2} />
        </div>
      ) : jds.data?.length === 0 ? (
        <EmptyState icon={Briefcase} title="No jobs posted yet" />
      ) : (
        <div className="space-y-4">
          {jds.data?.map((jd) => (
            <div key={jd.id} className="space-y-2">
              <div className="card flex flex-wrap items-center gap-4 p-4">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-50 font-semibold text-brand-700">
                  {(jd.company ?? "?").charAt(0)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{jd.company ?? "Unknown company"}</p>
                  <p className="text-sm text-slate-500">{jd.role ?? "Role not stated"}</p>
                </div>
                <button className="btn" disabled={!me.data || !policyId || busy !== null} onClick={() => check(jd.id)}>
                  {busy === jd.id ? <Spinner /> : <Search className="size-4" aria-hidden />}
                  {busy === jd.id ? "Checking…" : results[jd.id] ? "Check again" : "Check my match"}
                </button>
              </div>
              {results[jd.id] && <MatchResultCard result={results[jd.id]} showName={false} />}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["student"]}>
      <MyPage />
    </RequireRole>
  );
}
