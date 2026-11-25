"use client";

import { Mail, ShieldCheck, Users } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { ThresholdSettings } from "@/components/ThresholdSettings";
import { Avatar, Chip, ErrorBox, PageHeader, Skeleton, Spinner, StatCard, SuccessBox, errorText, type Tone } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireRole, useAuth } from "@/lib/auth";
import type { Profile, Role } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const ROLES: Role[] = ["student", "officer", "recruiter", "admin"];
const ROLE_TONE: Record<Role, Tone> = { admin: "brand", officer: "green", recruiter: "amber", student: "slate" };

function AdminPage() {
  const { profile: me } = useAuth();
  const { data: users, error: loadError, loading, refresh } = useApi<Profile[]>("/admin/users");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("officer");
  const [busy, setBusy] = useState(false);
  const [changing, setChanging] = useState<string | null>(null);

  const counts = useMemo(() => {
    const c: Record<Role, number> = { admin: 0, officer: 0, recruiter: 0, student: 0 };
    users?.forEach((u) => (c[u.role] += 1));
    return c;
  }, [users]);

  async function invite(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created = await api<Profile>("/admin/invite", { method: "POST", body: JSON.stringify({ email, role }) });
      setNotice(`Invitation sent to ${created.email} as ${created.role}.`);
      setEmail("");
      await refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(user: Profile, next: Role) {
    setChanging(user.id);
    setError(null);
    setNotice(null);
    try {
      await api<Profile>(`/admin/users/${user.id}/role`, { method: "PUT", body: JSON.stringify({ role: next }) });
      setNotice(`${user.email} is now ${next}.`);
      await refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setChanging(null);
    }
  }

  return (
    <>
      <PageHeader title="Users & settings" subtitle="Everyone who signs up starts as a student. Officers, recruiters and admins are granted here, along with college-wide settings." />

      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Admins" value={counts.admin} icon={ShieldCheck} tone="brand" />
        <StatCard label="Officers" value={counts.officer} icon={Users} tone="green" />
        <StatCard label="Recruiters" value={counts.recruiter} icon={Users} tone="amber" />
        <StatCard label="Students" value={counts.student} icon={Users} tone="slate" />
      </div>

      <div className="mb-6">
        <ThresholdSettings />
      </div>

      <div className="mb-6 space-y-3">
        <ErrorBox message={error ?? loadError?.message} />
        {notice && <SuccessBox>{notice}</SuccessBox>}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <form onSubmit={invite} className="card h-fit space-y-4">
          <div>
            <p className="font-semibold">Invite someone</p>
            <p className="text-sm text-slate-500">They get an email link from Supabase to join with this role.</p>
          </div>
          <div>
            <label className="label" htmlFor="invite-email">Email</label>
            <input id="invite-email" type="email" className="input" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="invite-role">Role</label>
            <select id="invite-role" className="input" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </div>
          <button className="btn w-full" disabled={busy}>
            {busy ? <Spinner /> : <Mail className="size-4" aria-hidden />}
            {busy ? "Sending…" : "Send invite"}
          </button>
        </form>

        <div className="card overflow-hidden p-0 lg:col-span-2">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
              <tr>
                <th className="px-4 py-2.5 font-semibold">User</th>
                <th className="px-4 py-2.5 font-semibold">Role</th>
                <th className="px-4 py-2.5 font-semibold">Change to</th>
              </tr>
            </thead>
            <tbody>
              {loading && !users
                ? Array.from({ length: 3 }, (_, i) => (
                    <tr key={i} className="border-t border-slate-100">
                      <td className="px-4 py-3" colSpan={3}>
                        <Skeleton className="h-8 w-full" />
                      </td>
                    </tr>
                  ))
                : users?.map((u) => {
                    const isMe = u.id === me?.id;
                    return (
                      <tr key={u.id} className="border-t border-slate-100">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-3">
                            <Avatar name={u.email ?? "?"} className="size-8 text-xs" />
                            <span className="truncate">
                              {u.email}
                              {isMe && <span className="ml-1.5 text-xs text-slate-400">(you)</span>}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <Chip tone={ROLE_TONE[u.role]}>{u.role}</Chip>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <select
                              className="input w-36 py-1.5"
                              value={u.role}
                              disabled={isMe || changing !== null}
                              title={isMe ? "You can't change your own role" : undefined}
                              onChange={(e) => changeRole(u, e.target.value as Role)}
                              aria-label={`Role for ${u.email}`}
                            >
                              {ROLES.map((r) => (
                                <option key={r}>{r}</option>
                              ))}
                            </select>
                            {changing === u.id && <Spinner />}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["admin"]}>
      <AdminPage />
    </RequireRole>
  );
}
