"use client";

import { Check, UserCheck, X } from "lucide-react";
import { useState } from "react";

import { Avatar, Chip, EmptyState, ErrorBox, PageHeader, Skeleton, Spinner, SuccessBox, errorText } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireRole } from "@/lib/auth";
import { formatDateTime } from "@/lib/time";
import type { RegistrationOut } from "@/lib/types";
import { invalidate, useApi } from "@/lib/useApi";

type Status = RegistrationOut["status"];

/** One pending request: details are editable before approving (the office verifies them). */
function PendingCard({ request, onDecided }: { request: RegistrationOut; onDecided: (message: string) => void }) {
  const [form, setForm] = useState({
    name: request.name,
    branch: request.branch,
    batch: request.batch,
    cgpa: String(request.cgpa),
    active_backlogs: String(request.active_backlogs),
  });
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  async function decide(action: "approve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      const body =
        action === "approve"
          ? { ...form, cgpa: Number(form.cgpa), active_backlogs: Number(form.active_backlogs) }
          : { note };
      await api(`/registrations/${request.user_id}/${action}`, { method: "POST", body: JSON.stringify(body) });
      onDecided(action === "approve" ? `${form.name} approved: their account is now linked.` : `${request.name}'s request was rejected.`);
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <li className="card space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Avatar name={request.name} />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-slate-900">{request.name}</p>
          <p className="truncate text-sm text-slate-500">{request.email} · asked {formatDateTime(request.submitted_at)}</p>
        </div>
        <Chip tone="amber">Waiting for approval</Chip>
      </div>
      <div className="grid gap-3 sm:grid-cols-5">
        <label className="sm:col-span-2">
          <span className="label">Name</span>
          <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} />
        </label>
        <label>
          <span className="label">Branch</span>
          <input className="input" value={form.branch} onChange={(e) => set("branch", e.target.value)} />
        </label>
        <label>
          <span className="label">Batch</span>
          <input className="input" value={form.batch} onChange={(e) => set("batch", e.target.value)} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label>
            <span className="label">CGPA</span>
            <input className="input" type="number" min={0} max={10} step={0.01} value={form.cgpa} onChange={(e) => set("cgpa", e.target.value)} />
          </label>
          <label>
            <span className="label">Backlogs</span>
            <input className="input" type="number" min={0} step={1} value={form.active_backlogs} onChange={(e) => set("active_backlogs", e.target.value)} />
          </label>
        </div>
      </div>
      <p className="text-xs text-slate-500">Self-reported by the student. Check them against your records and correct anything before approving.</p>
      <ErrorBox message={error} />
      {rejecting ? (
        <div className="space-y-2 rounded-lg border border-rose-200 bg-rose-50 p-3">
          <label className="block">
            <span className="label">Reason (the student sees this)</span>
            <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. CGPA doesn't match our records" />
          </label>
          <div className="flex gap-2">
            <button className="btn bg-rose-600 hover:bg-rose-600 hover:brightness-110" disabled={busy || !note.trim()} onClick={() => decide("reject")}>
              {busy ? <Spinner /> : <X className="size-4" aria-hidden />} Reject
            </button>
            <button className="btn-ghost" onClick={() => setRejecting(false)} disabled={busy}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button className="btn" disabled={busy} onClick={() => decide("approve")}>
            {busy ? <Spinner /> : <Check className="size-4" aria-hidden />} Approve
          </button>
          <button className="btn-ghost text-rose-600" disabled={busy} onClick={() => setRejecting(true)}>
            <X className="size-4" aria-hidden /> Reject…
          </button>
        </div>
      )}
    </li>
  );
}

function DecidedRow({ request }: { request: RegistrationOut }) {
  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <Avatar name={request.name} className="size-8 text-xs" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-900">{request.name} <span className="font-normal text-slate-500">· {request.email}</span></p>
        <p className="text-xs text-slate-500">
          {request.branch} · {request.batch} · CGPA {request.cgpa}
          {request.decided_at && ` · decided ${formatDateTime(request.decided_at)}`}
          {request.note && ` · “${request.note}”`}
        </p>
      </div>
      <Chip tone={request.status === "approved" ? "green" : "red"}>{request.status === "approved" ? "Approved" : "Rejected"}</Chip>
    </li>
  );
}

function ApprovalsPage() {
  const [tab, setTab] = useState<Status>("pending");
  const list = useApi<RegistrationOut[]>(`/registrations?status=${tab}`);
  const [notice, setNotice] = useState<string | null>(null);

  function decided(message: string) {
    setNotice(message);
    invalidate("/registrations", "/students");
    void list.refresh();
  }

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Students who signed up themselves and asked to join. Approving creates their student record and links their account."
      />
      <div className="mb-4 inline-flex rounded-lg border border-slate-200 bg-surface p-1 text-sm shadow-sm" role="tablist">
        {(["pending", "approved", "rejected"] as Status[]).map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => { setTab(key); setNotice(null); }}
            className={`rounded-md px-3 py-1.5 font-medium capitalize transition ${tab === key ? "bg-brand-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"}`}
          >
            {key === "pending" ? "Waiting" : key}
          </button>
        ))}
      </div>
      {notice && <div className="mb-4"><SuccessBox>{notice}</SuccessBox></div>}
      <ErrorBox message={list.error?.message} />
      {list.loading && !list.data ? (
        <div className="card space-y-3">{[0, 1].map((i) => <Skeleton key={i} className="h-24 w-full" />)}</div>
      ) : !list.data?.length ? (
        <EmptyState icon={UserCheck} title={tab === "pending" ? "No one is waiting" : `No ${tab} requests`}>
          {tab === "pending" ? "Students who sign up and send their details appear here for approval." : "Decided requests are listed here."}
        </EmptyState>
      ) : tab === "pending" ? (
        <ul className="space-y-4">
          {list.data.map((r) => <PendingCard key={r.user_id} request={r} onDecided={decided} />)}
        </ul>
      ) : (
        <ul className="card divide-y divide-slate-100 py-0">
          {list.data.map((r) => <DecidedRow key={r.user_id} request={r} />)}
        </ul>
      )}
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["officer", "admin"]}>
      <ApprovalsPage />
    </RequireRole>
  );
}
