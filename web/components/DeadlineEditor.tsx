"use client";

import { CalendarClock, Save } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/time";
import type { DeadlineChange, JDSummary } from "@/lib/types";

import { ErrorBox, Spinner, SuccessBox, errorText } from "./ui";

/** Show a job's deadline and, for whoever may (recruiter: own jobs; staff: any), change it
 *  with PUT /jds/{id}/deadline. Shortening moves pending applications earlier server-side. */
export function DeadlineEditor({ jd, onChanged }: { jd: JDSummary; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DeadlineChange | null>(null);

  function start() {
    // Prefill from the current deadline when it's a plain ISO date (others: pick fresh).
    const iso = /^\d{4}-\d{2}-\d{2}/.exec(jd.deadline ?? "")?.[0] ?? "";
    setDate(iso);
    setTime(/T(\d{2}:\d{2})/.exec(jd.deadline ?? "")?.[1] ?? "");
    setResult(null);
    setError(null);
    setEditing(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const change = await api<DeadlineChange>(`/jds/${jd.id}/deadline`, {
        method: "PUT",
        body: JSON.stringify({ deadline: time ? `${date}T${time}` : date }),
      });
      setResult(change);
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <CalendarClock className="size-4 text-slate-400" aria-hidden />
        <span className="text-slate-700">
          Deadline: <span className="font-medium">{jd.deadline ?? "not stated"}</span>
          {jd.deadline_at && <span className="text-slate-500"> (closes {formatDateTime(jd.deadline_at)})</span>}
        </span>
        {jd.can_edit_deadline && !editing && (
          <button className="btn-ghost px-2 py-1 text-brand-700" onClick={start}>Change</button>
        )}
      </div>
      {jd.deadline_changed_at && (
        <p className="text-xs text-slate-500">
          Changed {formatDateTime(jd.deadline_changed_at)}; the JD originally said &ldquo;{jd.original_deadline ?? "no deadline"}&rdquo;.
        </p>
      )}
      {editing && (
        <form onSubmit={save} className="space-y-3 rounded-lg border border-slate-200 bg-surface p-3">
          <div className="flex flex-wrap items-end gap-3">
            <label>
              <span className="label">New deadline</span>
              <input className="input w-44" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
            </label>
            <label>
              <span className="label">Time (optional)</span>
              <input className="input w-32" type="time" value={time} onChange={(e) => setTime(e.target.value)} />
            </label>
          </div>
          <p className="text-xs text-slate-500">
            College time. Without a time, the job closes at the end of that day. If the new deadline is earlier, pending
            applications are moved earlier to reach you in time, and those students are notified.
          </p>
          <ErrorBox message={error} />
          <div className="flex gap-2">
            <button className="btn" type="submit" disabled={busy || !date}>
              {busy ? <Spinner /> : <Save className="size-4" aria-hidden />} Save deadline
            </button>
            <button className="btn-ghost" type="button" onClick={() => setEditing(false)} disabled={busy}>Cancel</button>
          </div>
        </form>
      )}
      {result && (
        <SuccessBox>
          Deadline set to {formatDateTime(result.deadline_at)}.
          {result.rescheduled > 0
            ? ` ${result.rescheduled} pending application${result.rescheduled === 1 ? "" : "s"} moved earlier; the students were notified.`
            : " No pending applications needed to move."}
        </SuccessBox>
      )}
    </div>
  );
}
