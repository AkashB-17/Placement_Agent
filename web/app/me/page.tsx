"use client";

import { Bell, Briefcase, CheckCheck, GraduationCap, Inbox, Link2Off, Rocket, Search, X } from "lucide-react";
import { useEffect, useState, type KeyboardEvent } from "react";

import { ApplicationCard } from "@/components/ApplicationCard";
import { MatchResultCard } from "@/components/MatchResultCard";
import { PolicyPicker } from "@/components/PolicyPicker";
import { Avatar, CardSkeletons, Chip, Chips, EmptyState, ErrorBox, PageHeader, Spinner, SuccessBox, errorText } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireRole } from "@/lib/auth";
import { timeAgo, useNow } from "@/lib/time";
import type { Application, JDSummary, MatchResult, Notification, PolicySummary, PreferencesOut, StudentDetail } from "@/lib/types";
import { invalidate, useApi } from "@/lib/useApi";

// ── Auto-apply preferences ──────────────────────────────────────────────────

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition ${checked ? "bg-brand-600" : "bg-slate-300"}`}
    >
      <span className={`inline-block size-5 rounded-full bg-white shadow transition ${checked ? "translate-x-5.5" : "translate-x-0.5"}`} />
    </button>
  );
}

function AutoApplyCard() {
  const { data, error: loadError, loading } = useApi<PreferencesOut>("/me/auto-apply");
  const [form, setForm] = useState<PreferencesOut | null>(null);
  const [company, setCompany] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  if (loading && !form) return <CardSkeletons count={1} />;
  if (!form) return <ErrorBox message={loadError?.message} />;

  const dirty = JSON.stringify([form.enabled, form.min_score, form.excluded_companies]) !==
    JSON.stringify([data?.enabled, data?.min_score, data?.excluded_companies]);

  function addCompany() {
    const name = company.trim();
    if (name && form && !form.excluded_companies.some((c) => c.toLowerCase() === name.toLowerCase())) {
      setForm({ ...form, excluded_companies: [...form.excluded_companies, name] });
    }
    setCompany("");
  }

  async function save() {
    if (!form) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await api<PreferencesOut>("/me/auto-apply", {
        method: "PUT",
        body: JSON.stringify({ enabled: form.enabled, min_score: form.min_score, excluded_companies: form.excluded_companies }),
      });
      invalidate("/me/auto-apply");
      setForm(updated);
      setSaved(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card space-y-5">
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
          <Rocket className="size-5" aria-hidden />
        </span>
        <div className="flex-1">
          <p className="font-semibold">Auto-apply</p>
          <p className="text-sm text-slate-500">
            When the placement office runs auto-apply for a job, we apply for you if you&apos;re eligible and score at least
            your minimum. You&apos;re notified and get {form.withdraw_hours} hours to withdraw before it&apos;s sent.
          </p>
        </div>
        <Toggle checked={form.enabled} onChange={(enabled) => setForm({ ...form, enabled })} label="Auto-apply on or off" />
      </div>

      <div className={form.enabled ? "space-y-5" : "pointer-events-none space-y-5 opacity-50"}>
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <label htmlFor="min-score" className="text-sm font-medium text-slate-700">Minimum match score</label>
            <span className="rounded-md bg-slate-100 px-2 py-0.5 text-sm font-semibold tabular-nums">{form.min_score}</span>
          </div>
          <input
            id="min-score"
            type="range"
            min={form.threshold}
            max={100}
            step={1}
            value={form.min_score}
            onChange={(e) => setForm({ ...form, min_score: Number(e.target.value) })}
            className="w-full accent-brand-600"
          />
          <p className="mt-1 text-xs text-slate-400">The college minimum is {form.threshold}; you can only raise it.</p>
        </div>

        <div>
          <label htmlFor="exclude" className="label">Never apply to</label>
          <div className="flex gap-2">
            <input
              id="exclude"
              className="input"
              placeholder="Company name"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              onKeyDown={(e: KeyboardEvent) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addCompany();
                }
              }}
            />
            <button type="button" className="btn-secondary" onClick={addCompany} disabled={!company.trim()}>
              Add
            </button>
          </div>
          {form.excluded_companies.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {form.excluded_companies.map((c) => (
                <span key={c} className="chip bg-slate-100 text-slate-700 ring-1 ring-slate-500/10 ring-inset">
                  {c}
                  <button
                    type="button"
                    className="rounded-full text-slate-400 hover:text-slate-700"
                    onClick={() => setForm({ ...form, excluded_companies: form.excluded_companies.filter((x) => x !== c) })}
                    aria-label={`Remove ${c}`}
                  >
                    <X className="size-3" aria-hidden />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <ErrorBox message={error} />
      {saved && !dirty && <SuccessBox>{form.enabled ? "Auto-apply is on." : "Auto-apply is off."}</SuccessBox>}
      <div className="flex justify-end">
        <button className="btn" onClick={save} disabled={busy || !dirty}>
          {busy && <Spinner />} Save preferences
        </button>
      </div>
    </section>
  );
}

// ── Notifications ───────────────────────────────────────────────────────────

function Notifications() {
  const { data, refresh } = useApi<Notification[]>("/me/notifications");
  const now = useNow(60_000);
  const unread = data?.filter((n) => !n.read).length ?? 0;

  async function markRead() {
    await api("/me/notifications/read", { method: "POST" });
    await refresh();
  }

  return (
    <section className="card p-0">
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
        <Bell className="size-4 text-slate-400" aria-hidden />
        <p className="font-semibold">Notifications</p>
        {unread > 0 && <span className="rounded-full bg-brand-600 px-2 py-0.5 text-xs font-semibold text-white">{unread}</span>}
        {unread > 0 && (
          <button className="btn-ghost ml-auto py-1 text-xs" onClick={markRead}>
            <CheckCheck className="size-3.5" aria-hidden /> Mark all read
          </button>
        )}
      </div>
      {!data?.length ? (
        <p className="flex items-center gap-2 px-4 py-6 text-sm text-slate-400">
          <Inbox className="size-4" aria-hidden /> Nothing yet.
        </p>
      ) : (
        <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto">
          {data.map((n) => (
            <li key={n.id} className={`px-4 py-3 text-sm ${n.read ? "text-slate-500" : "bg-brand-50/40 text-slate-800"}`}>
              <p>{n.message}</p>
              <p className="mt-0.5 text-xs text-slate-400">{timeAgo(n.created_at, now)}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── Page ────────────────────────────────────────────────────────────────────

function MyPage() {
  const me = useApi<StudentDetail>("/students/me");
  const policies = useApi<PolicySummary[]>("/policies");
  const jds = useApi<JDSummary[]>("/jds");
  const applications = useApi<Application[]>(me.data ? "/me/applications" : null);
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
  const applied = new Set(applications.data?.map((a) => a.jd_id));
  return (
    <>
      <PageHeader title="My placements" subtitle="Your applications, auto-apply settings and the jobs open to you." />
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
                  <Chip tone="brand" icon={GraduationCap}>{profile.branch} · {profile.batch}</Chip>
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

      <div className="grid gap-8 lg:grid-cols-5">
        <div className="space-y-8 lg:col-span-3">
          <section>
            <h2 className="mb-3 text-lg font-semibold">My applications</h2>
            {applications.loading && !applications.data ? (
              <CardSkeletons count={1} />
            ) : !applications.data?.length ? (
              <EmptyState icon={Rocket} title="No applications yet">
                Turn on auto-apply and you&apos;ll appear here when the placement office runs it for a job you qualify for.
              </EmptyState>
            ) : (
              <div className="space-y-3">
                {applications.data.map((a) => (
                  <ApplicationCard
                    key={a.id}
                    app={a}
                    viewer="student"
                    onChanged={() => {
                      invalidate("/me/notifications");
                      void applications.refresh();
                    }}
                  />
                ))}
              </div>
            )}
          </section>

          <section>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">Open positions</h2>
              {policies.data && policies.data.length > 1 && (
                <PolicyPicker policies={policies.data} value={policyId} onChange={setPolicyId} />
              )}
            </div>
            {jds.loading && !jds.data ? (
              <CardSkeletons count={2} />
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
                      {applied.has(jd.id) && <Chip tone="brand" icon={Rocket}>Applied</Chip>}
                      <button className="btn-secondary" disabled={!me.data || !policyId || busy !== null} onClick={() => check(jd.id)}>
                        {busy === jd.id ? <Spinner /> : <Search className="size-4" aria-hidden />}
                        {busy === jd.id ? "Checking…" : results[jd.id] ? "Check again" : "Check my match"}
                      </button>
                    </div>
                    {results[jd.id] && <MatchResultCard result={results[jd.id]} showName={false} />}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        <aside className="space-y-6 lg:col-span-2">
          {me.data && <AutoApplyCard />}
          {me.data && <Notifications />}
        </aside>
      </div>
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
