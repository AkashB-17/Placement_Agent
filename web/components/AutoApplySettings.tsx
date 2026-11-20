"use client";

import { Rocket, X } from "lucide-react";
import { useEffect, useState, type KeyboardEvent } from "react";

import { api } from "@/lib/api";
import type { PreferencesOut } from "@/lib/types";
import { invalidate, useApi } from "@/lib/useApi";

import { CardSkeletons, ErrorBox, Spinner, SuccessBox, errorText } from "./ui";

/** The student's auto-apply preferences: on/off, minimum score, companies to avoid. */
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

export function AutoApplySettings() {
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
