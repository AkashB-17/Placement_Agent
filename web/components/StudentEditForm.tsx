"use client";

import { Save } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/api";
import type { StudentDetail, StudentProfile } from "@/lib/types";

import { ErrorBox, Spinner, errorText } from "./ui";

type Form = Omit<StudentProfile, "cgpa" | "active_backlogs" | "email"> & {
  email: string;
  cgpa: string;
  active_backlogs: string;
};

/** The placement office corrects a student's academic record (PUT /students/{id}).
 *  The student's CV is theirs and is not part of this form. */
export function StudentEditForm({
  detail,
  onSaved,
  onCancel,
}: {
  detail: StudentDetail;
  onSaved: (updated: StudentDetail) => void;
  onCancel: () => void;
}) {
  const p = detail.profile;
  const [form, setForm] = useState<Form>({
    name: p.name,
    email: p.email ?? "",
    branch: p.branch,
    batch: p.batch,
    cgpa: String(p.cgpa),
    active_backlogs: String(p.active_backlogs),
    is_placed: p.is_placed,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const updated = await api<StudentDetail>(`/students/${detail.id}`, {
        method: "PUT",
        body: JSON.stringify({
          name: form.name,
          email: form.email.trim() || null,
          branch: form.branch,
          batch: form.batch,
          cgpa: Number(form.cgpa),
          active_backlogs: Number(form.active_backlogs),
          is_placed: form.is_placed,
        }),
      });
      onSaved(updated);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const emailChanged = form.email.trim().toLowerCase() !== (p.email ?? "").toLowerCase();
  return (
    <form onSubmit={save} className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label>
          <span className="label">Name</span>
          <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required />
        </label>
        <label>
          <span className="label">Login email</span>
          <input className="input" type="email" value={form.email} onChange={(e) => set("email", e.target.value)} />
        </label>
        <label>
          <span className="label">Branch</span>
          <input className="input" value={form.branch} onChange={(e) => set("branch", e.target.value)} required />
        </label>
        <label>
          <span className="label">Batch (graduating year)</span>
          <input className="input" value={form.batch} onChange={(e) => set("batch", e.target.value)} required />
        </label>
        <label>
          <span className="label">CGPA</span>
          <input className="input" type="number" min={0} max={10} step={0.01} value={form.cgpa} onChange={(e) => set("cgpa", e.target.value)} required />
        </label>
        <label>
          <span className="label">Active backlogs</span>
          <input className="input" type="number" min={0} step={1} value={form.active_backlogs} onChange={(e) => set("active_backlogs", e.target.value)} required />
        </label>
      </div>
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" className="size-4 accent-brand-600" checked={form.is_placed} onChange={(e) => set("is_placed", e.target.checked)} />
        Already placed
      </label>
      {emailChanged && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          The login email links this record to the student&apos;s account. After the change, only someone signed in with the new
          email sees this record.
        </p>
      )}
      <p className="text-xs text-slate-500">
        Changes apply to eligibility straight away. Applications already made keep the details from when they were made.
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
