"use client";

import { ChevronRight, ExternalLink, FileText, GraduationCap, Search, UserPlus } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Avatar, Chip, Chips, EmptyState, ErrorBox, PageHeader, Skeleton, Spinner, errorText } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireRole } from "@/lib/auth";
import type { StudentDetail, StudentSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";

function StudentDetailPanel({ student }: { student: StudentSummary }) {
  const { data: detail, error, loading } = useApi<StudentDetail>(`/students/${student.id}`);
  const [opening, setOpening] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  async function openResume() {
    setOpening(true);
    setLinkError(null);
    try {
      // Short-lived signed link to the private bucket; fetched on click, never stored.
      const link = await api<{ url: string }>(`/students/${student.id}/resume`);
      window.open(link.url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setLinkError(errorText(e));
    } finally {
      setOpening(false);
    }
  }

  if (loading && !detail) {
    return (
      <div className="space-y-2 p-5">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-6 w-2/3" />
      </div>
    );
  }
  if (error && !detail) return <div className="p-5"><ErrorBox message={error.message} /></div>;
  if (!detail) return null;

  const { parsed_resume: resume } = detail;
  return (
    <div className="grid gap-5 bg-slate-50/60 p-5 md:grid-cols-3">
      <div className="md:col-span-2 space-y-4">
        <div>
          <p className="eyebrow mb-2">Skills found in the resume</p>
          <Chips items={resume.skills} tone="slate" empty="None extracted" />
        </div>
        {resume.projects.length > 0 && (
          <div>
            <p className="eyebrow mb-2">Projects</p>
            <ul className="space-y-1 text-sm text-slate-700">
              {resume.projects.map((p, i) => (
                <li key={`${p}-${i}`} className="flex gap-2">
                  <ChevronRight className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden />
                  {p}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <div className="space-y-3">
        <p className="eyebrow">Resume file</p>
        {detail.has_resume_file ? (
          <button className="btn-secondary w-full" onClick={openResume} disabled={opening}>
            {opening ? <Spinner /> : <ExternalLink className="size-4" aria-hidden />}
            Open (link valid 60 s)
          </button>
        ) : (
          <p className="flex items-center gap-2 text-sm text-slate-400">
            <FileText className="size-4" aria-hidden /> Text only, no file stored
          </p>
        )}
        <ErrorBox message={linkError} />
      </div>
    </div>
  );
}

function StudentsPage() {
  const { data: students, error, loading } = useApi<StudentSummary[]>("/students");
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!students || !q) return students ?? [];
    return students.filter((s) => [s.name, s.email ?? "", s.branch, s.batch].some((v) => v.toLowerCase().includes(q)));
  }, [students, query]);

  return (
    <>
      <PageHeader
        title="Students"
        subtitle="Everyone in the placement pool. Click a student for parsed skills and their resume file."
        actions={
          <Link href="/upload?tab=student" className="btn">
            <UserPlus className="size-4" aria-hidden /> Add student
          </Link>
        }
      />
      <ErrorBox message={error?.message} />

      {loading && !students ? (
        <div className="card space-y-3">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : students && students.length === 0 ? (
        <EmptyState icon={GraduationCap} title="No students yet">
          Add students on the Upload page with their resume.
        </EmptyState>
      ) : (
        <div className="card overflow-hidden p-0">
          <div className="flex items-center gap-3 border-b border-slate-100 p-3">
            <div className="relative max-w-sm flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
              <input
                className="input pl-9"
                placeholder="Search by name, email, branch or batch"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search students"
              />
            </div>
            <span className="text-sm text-slate-500">
              {filtered.length} of {students?.length ?? 0}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-2.5 font-semibold">Student</th>
                  <th className="px-4 py-2.5 font-semibold">Branch</th>
                  <th className="px-4 py-2.5 font-semibold">Batch</th>
                  <th className="px-4 py-2.5 text-right font-semibold">CGPA</th>
                  <th className="px-4 py-2.5 text-right font-semibold">Backlogs</th>
                  <th className="px-4 py-2.5 font-semibold">Status</th>
                  <th className="w-10" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((s) => {
                  const open = openId === s.id;
                  return (
                    <StudentRows key={s.id} student={s} open={open} onToggle={() => setOpenId(open ? null : s.id)} />
                  );
                })}
              </tbody>
            </table>
          </div>
          {filtered.length === 0 && <p className="p-6 text-center text-sm text-slate-500">No student matches &ldquo;{query}&rdquo;.</p>}
        </div>
      )}
    </>
  );
}

function StudentRows({ student: s, open, onToggle }: { student: StudentSummary; open: boolean; onToggle: () => void }) {
  return (
    <>
      <tr
        className={`cursor-pointer border-t border-slate-100 transition hover:bg-slate-50 ${open ? "bg-slate-50" : ""}`}
        onClick={onToggle}
        aria-expanded={open}
      >
        <td className="px-4 py-3">
          <div className="flex items-center gap-3">
            <Avatar name={s.name} className="size-8 text-xs" />
            <div className="min-w-0">
              <p className="font-medium text-slate-900">{s.name}</p>
              <p className="truncate text-xs text-slate-500">{s.email ?? "No login linked"}</p>
            </div>
          </div>
        </td>
        <td className="px-4 py-3"><Chip tone="brand">{s.branch}</Chip></td>
        <td className="px-4 py-3 text-slate-700">{s.batch}</td>
        <td className="px-4 py-3 text-right font-medium tabular-nums">{s.cgpa.toFixed(2)}</td>
        <td className={`px-4 py-3 text-right tabular-nums ${s.active_backlogs > 0 ? "font-medium text-rose-600" : "text-slate-700"}`}>
          {s.active_backlogs}
        </td>
        <td className="px-4 py-3">{s.is_placed ? <Chip tone="green">Placed</Chip> : <Chip>Seeking</Chip>}</td>
        <td className="px-2 py-3 text-slate-400">
          <ChevronRight className={`size-4 transition ${open ? "rotate-90" : ""}`} aria-hidden />
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={7} className="border-t border-slate-100 p-0">
            <StudentDetailPanel student={s} />
          </td>
        </tr>
      )}
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["officer", "admin"]}>
      <StudentsPage />
    </RequireRole>
  );
}
