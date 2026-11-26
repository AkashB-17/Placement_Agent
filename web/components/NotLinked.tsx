"use client";

import { Clock3, Mail, Phone, RefreshCw, Send, UserPlus, XCircle } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { api } from "@/lib/api";
import { PLACEMENT_CONTACT, placementPhoneHref } from "@/lib/contact";
import { formatDateTime } from "@/lib/time";
import type { MyRegistration, RegistrationIn } from "@/lib/types";
import { useApi } from "@/lib/useApi";

import { ErrorBox, Skeleton, Spinner, errorText } from "./ui";

function RegistrationForm({ initial, onSubmitted }: { initial?: RegistrationIn; onSubmitted: () => void }) {
  const [form, setForm] = useState({
    name: initial?.name ?? "",
    branch: initial?.branch ?? "",
    batch: initial?.batch ?? "",
    cgpa: initial ? String(initial.cgpa) : "",
    active_backlogs: initial ? String(initial.active_backlogs) : "0",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api<MyRegistration>("/me/registration", {
        method: "POST",
        body: JSON.stringify({ ...form, cgpa: Number(form.cgpa), active_backlogs: Number(form.active_backlogs) }),
      });
      onSubmitted();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="sm:col-span-2">
          <span className="label">Full name</span>
          <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required />
        </label>
        <label>
          <span className="label">Branch</span>
          <input className="input" value={form.branch} onChange={(e) => set("branch", e.target.value)} placeholder="CSE" required />
        </label>
        <label>
          <span className="label">Batch (graduating year)</span>
          <input className="input" value={form.batch} onChange={(e) => set("batch", e.target.value)} placeholder="2027" required />
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
      <p className="text-xs text-slate-500">
        The placement office checks these against its records before approving, and may correct them.
      </p>
      <ErrorBox message={error} />
      <button className="btn" type="submit" disabled={busy}>
        {busy ? <Spinner /> : <Send className="size-4" aria-hidden />} Send for approval
      </button>
    </form>
  );
}

/**
 * Shown to a signed-in student whose email isn't on any student record yet: they ask to be
 * added (POST /me/registration), then wait for the placement office to approve.
 */
export function NotLinked() {
  const mine = useApi<MyRegistration>("/me/registration");
  const [editing, setEditing] = useState(false);
  const request = mine.data?.request;

  function refresh() {
    setEditing(false);
    void mine.refresh();
  }

  // Approved (or added by the office) since this page loaded: reload to show the portal.
  const linked = mine.data?.linked ?? false;
  useEffect(() => {
    if (linked) window.location.reload();
  }, [linked]);

  if ((mine.loading && !mine.data) || linked) {
    return <div className="card mx-auto max-w-xl"><Skeleton className="h-40 w-full" /></div>;
  }

  const contact = (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
      <span>Questions? Contact the placement office:</span>
      <a href={`mailto:${PLACEMENT_CONTACT.email}`} className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline">
        <Mail className="size-3.5" aria-hidden /> {PLACEMENT_CONTACT.email}
      </a>
      <a href={placementPhoneHref} className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline">
        <Phone className="size-3.5" aria-hidden /> {PLACEMENT_CONTACT.phone}
      </a>
    </p>
  );

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <ErrorBox message={mine.error?.message} />
      {request?.status === "pending" && !editing ? (
        <section className="card space-y-4">
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-700">
              <Clock3 className="size-5" aria-hidden />
            </span>
            <div>
              <p className="font-semibold text-slate-900">Waiting for approval</p>
              <p className="text-sm text-slate-600">
                You asked to join on {formatDateTime(request.submitted_at)}. Once the placement office approves, your jobs,
                eligibility and CV upload appear here.
              </p>
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-lg bg-slate-50 p-3 text-sm">
            <dt className="text-slate-500">Name</dt><dd>{request.name}</dd>
            <dt className="text-slate-500">Branch · batch</dt><dd>{request.branch} · {request.batch}</dd>
            <dt className="text-slate-500">CGPA</dt><dd>{request.cgpa}</dd>
            <dt className="text-slate-500">Active backlogs</dt><dd>{request.active_backlogs}</dd>
          </dl>
          <div className="flex flex-wrap gap-2">
            <button className="btn-secondary" onClick={refresh}>
              <RefreshCw className="size-4" aria-hidden /> Check again
            </button>
            <button className="btn-ghost" onClick={() => setEditing(true)}>Edit my request</button>
          </div>
          {contact}
        </section>
      ) : (
        <section className="card space-y-4">
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
              <UserPlus className="size-5" aria-hidden />
            </span>
            <div>
              <p className="font-semibold text-slate-900">Join the placement portal</p>
              <p className="text-sm text-slate-600">
                Your account isn&apos;t linked to a student record yet. Send your details; the placement office approves you
                and your account is linked to {request?.email ?? "your email"}.
              </p>
            </div>
          </div>
          {request?.status === "rejected" && !editing && (
            <p className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
              <XCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span>
                Your request was not approved{request.note ? `: ${request.note}` : "."} Correct your details and send it again.
              </span>
            </p>
          )}
          <RegistrationForm initial={request ?? undefined} onSubmitted={refresh} />
          {contact}
        </section>
      )}
    </div>
  );
}
