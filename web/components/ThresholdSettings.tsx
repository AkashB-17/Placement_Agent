"use client";

import { Gauge, Save } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/time";
import type { AppSettings } from "@/lib/types";
import { invalidate, useApi } from "@/lib/useApi";

import { ErrorBox, Skeleton, Spinner, SuccessBox, errorText } from "./ui";

/** Admin control for the college-wide minimum auto-apply score (GET/PUT /admin/settings). */
export function ThresholdSettings() {
  const current = useApi<AppSettings>("/admin/settings");
  const [value, setValue] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (current.data && value === null) setValue(current.data.auto_apply_threshold);
  }, [current.data, value]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (value === null) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await api<AppSettings>("/admin/settings", { method: "PUT", body: JSON.stringify({ auto_apply_threshold: value }) });
      // Rankings, the recommended flag and students' preference limits all read it.
      invalidate("/admin/settings", "/jds/", "/me/auto-apply");
      await current.refresh();
      setSaved(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (current.loading && !current.data) return <section className="card"><Skeleton className="h-24 w-full" /></section>;
  const data = current.data;
  const dirty = data !== undefined && value !== null && value !== data.auto_apply_threshold;

  return (
    <section className="card space-y-4">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
          <Gauge className="size-5" aria-hidden />
        </span>
        <div>
          <p className="font-semibold text-slate-900">Minimum auto-apply score</p>
          <p className="text-sm text-slate-600">
            Students are auto-applied only when their score reaches this (or their own, higher bar). It also decides who is
            marked &ldquo;auto-apply recommended&rdquo; in rankings.
          </p>
        </div>
      </div>
      <ErrorBox message={current.error?.message} />
      {data && value !== null && (
        <form onSubmit={save} className="space-y-3">
          <div className="flex flex-wrap items-center gap-4">
            <input
              type="range" min={0} max={100} step={1} value={value}
              onChange={(e) => { setValue(Number(e.target.value)); setSaved(false); }}
              className="w-64 accent-brand-600" aria-label="Minimum auto-apply score"
            />
            <label className="flex items-center gap-2 text-sm">
              <input
                className="input w-24" type="number" min={0} max={100} step={0.5} value={value}
                onChange={(e) => { setValue(Number(e.target.value)); setSaved(false); }}
              />
              <span className="text-slate-500">/ 100</span>
            </label>
            <button className="btn" type="submit" disabled={busy || !dirty}>
              {busy ? <Spinner /> : <Save className="size-4" aria-hidden />} Save
            </button>
          </div>
          <p className="text-xs text-slate-500">
            {data.updated_at ? `Last changed ${formatDateTime(data.updated_at)}. ` : "Using the default. "}
            Default: {data.default_auto_apply_threshold}. Takes effect at once for rankings and the next auto-apply runs;
            applications already made are not affected. Students whose own bar is higher keep it.
          </p>
          <ErrorBox message={error} />
          {saved && <SuccessBox>Saved: auto-apply now needs a score of at least {data.auto_apply_threshold}.</SuccessBox>}
        </form>
      )}
    </section>
  );
}
