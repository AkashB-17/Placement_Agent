"use client";

import { Save } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/api";
import type { JDDetail } from "@/lib/types";

import { ErrorBox, Spinner, errorText } from "./ui";

const COLLEGE_TZ = "Asia/Kolkata"; // matches the API's deadline_utc_offset_minutes (IST)

/** The deadline as date and time inputs in college time; a date-only deadline (end of day) has no time. */
function deadlineInputs(deadlineAt: string | null): { date: string; time: string } {
  if (!deadlineAt) return { date: "", time: "" };
  const at = new Date(deadlineAt);
  const date = at.toLocaleDateString("en-CA", { timeZone: COLLEGE_TZ }); // YYYY-MM-DD
  const time = at.toLocaleTimeString("en-GB", { timeZone: COLLEGE_TZ, hour: "2-digit", minute: "2-digit" });
  return { date, time: time === "23:59" ? "" : time };
}

const list = (text: string) => text.split(/[,\n]/).map((s) => s.trim()).filter(Boolean);

/** An admin's edit of a job (PUT /jds/{id}). The posted JD text itself is not changed. */
export function JDEditForm({
  jd,
  deadlineAt,
  onSaved,
  onCancel,
}: {
  jd: JDDetail;
  deadlineAt: string | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const r = jd.requirements;
  const initialDeadline = deadlineInputs(deadlineAt);
  const [form, setForm] = useState({
    company: r.company ?? "",
    role: r.role ?? "",
    ctc: r.ctc ?? "",
    experience_required: r.experience_required ?? "",
    min_cgpa_override: r.min_cgpa_override === null ? "" : String(r.min_cgpa_override),
    allowed_branches: r.allowed_branches.join(", "),
    allowed_batches: r.allowed_batches.join(", "),
    required_skills: r.required_skills.join(", "),
    preferred_skills: r.preferred_skills.join(", "),
    deadline_date: initialDeadline.date,
    deadline_time: initialDeadline.time,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const deadlineTouched = form.deadline_date !== initialDeadline.date || form.deadline_time !== initialDeadline.time;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    // An untouched deadline is sent back exactly as stored, so it doesn't count as a change.
    const deadline = deadlineTouched
      ? form.deadline_date
        ? form.deadline_time
          ? `${form.deadline_date}T${form.deadline_time}`
          : form.deadline_date
        : null
      : r.deadline;
    try {
      await api<JDDetail>(`/jds/${jd.id}`, {
        method: "PUT",
        body: JSON.stringify({
          company: form.company || null,
          role: form.role || null,
          ctc: form.ctc || null,
          experience_required: form.experience_required || null,
          min_cgpa_override: form.min_cgpa_override.trim() === "" ? null : Number(form.min_cgpa_override),
          allowed_branches: list(form.allowed_branches),
          allowed_batches: list(form.allowed_batches),
          required_skills: list(form.required_skills),
          preferred_skills: list(form.preferred_skills),
          deadline,
        }),
      });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label>
          <span className="label">Company</span>
          <input className="input" value={form.company} onChange={(e) => set("company", e.target.value)} />
        </label>
        <label>
          <span className="label">Role</span>
          <input className="input" value={form.role} onChange={(e) => set("role", e.target.value)} />
        </label>
        <label>
          <span className="label">CTC / stipend</span>
          <input className="input" value={form.ctc} onChange={(e) => set("ctc", e.target.value)} />
        </label>
        <label>
          <span className="label">Experience</span>
          <input className="input" value={form.experience_required} onChange={(e) => set("experience_required", e.target.value)} />
        </label>
        <div>
          <span className="label">Deadline (college time)</span>
          <div className="flex gap-2">
            <input className="input" type="date" value={form.deadline_date} onChange={(e) => set("deadline_date", e.target.value)} aria-label="Deadline date" />
            <input className="input w-32" type="time" value={form.deadline_time} onChange={(e) => set("deadline_time", e.target.value)} aria-label="Deadline time" />
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {r.deadline ? `Currently "${r.deadline}". ` : "Rolling (no deadline). "}No time means the end of that day.
          </p>
        </div>
        <label>
          <span className="label">Minimum CGPA (blank: none)</span>
          <input className="input" type="number" min={0} max={10} step={0.01} value={form.min_cgpa_override} onChange={(e) => set("min_cgpa_override", e.target.value)} />
        </label>
        <label>
          <span className="label">Allowed branches (comma-separated; blank: all)</span>
          <input className="input" value={form.allowed_branches} onChange={(e) => set("allowed_branches", e.target.value)} placeholder="CSE, IT, ECE" />
        </label>
        <label>
          <span className="label">Allowed batches (blank: all)</span>
          <input className="input" value={form.allowed_batches} onChange={(e) => set("allowed_batches", e.target.value)} placeholder="2027" />
        </label>
      </div>
      <label className="block">
        <span className="label">Required skills (comma-separated)</span>
        <textarea className="input min-h-16" value={form.required_skills} onChange={(e) => set("required_skills", e.target.value)} required />
      </label>
      <label className="block">
        <span className="label">Preferred skills</span>
        <textarea className="input min-h-16" value={form.preferred_skills} onChange={(e) => set("preferred_skills", e.target.value)} />
      </label>
      <p className="text-xs text-slate-500">
        Students and rankings use these details at once; changed skills are re-scored. Applications already made keep their
        snapshot. {deadlineTouched && "Moving the deadline earlier reschedules pending applications and notifies those students. "}
        The posted JD text is not changed.
      </p>
      <ErrorBox message={error} />
      <div className="flex gap-2">
        <button className="btn" type="submit" disabled={busy}>
          {busy ? <Spinner /> : <Save className="size-4" aria-hidden />} Save changes
        </button>
        <button className="btn-ghost" type="button" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </form>
  );
}
