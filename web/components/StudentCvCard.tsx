"use client";

import { ExternalLink, FileText, FileUp, TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";

import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/time";
import type { StudentDetail } from "@/lib/types";

import { ErrorBox, Spinner, SuccessBox, errorText } from "./ui";

/**
 * The student's own CV: upload, replace and view. Academic details come from the placement
 * office and are not editable here. Each upload is stored as a new version; applications
 * already made keep the version they were scored on.
 */
export function StudentCvCard({ detail, onUploaded }: { detail: StudentDetail; onUploaded: (updated: StudentDetail) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function upload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const form = new FormData();
      form.append("resume", file);
      const updated = await api<StudentDetail>("/students/me/resume", { method: "PUT", body: form });
      onUploaded(updated);
      setSaved(true);
      setFile(null);
      if (input.current) input.current.value = "";
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function openCv() {
    setOpening(true);
    setError(null);
    try {
      const link = await api<{ url: string }>(`/students/${detail.id}/resume`);
      window.open(link.url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setOpening(false);
    }
  }

  return (
    <section className="card mb-8 space-y-4">
      <div className="flex flex-wrap items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
          <FileText className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">Your CV</p>
          {detail.has_resume ? (
            <p className="text-sm text-slate-500">
              Uploaded {detail.resume_updated_at ? formatDateTime(detail.resume_updated_at) : ""}. Replacing it gives you a fresh
              score; applications already made keep the CV they were scored on.
            </p>
          ) : (
            <p className="flex items-center gap-1.5 text-sm text-amber-700">
              <TriangleAlert className="size-4" aria-hidden />
              Upload your CV to be scored for jobs and to use auto-apply.
            </p>
          )}
        </div>
        {detail.has_resume_file && (
          <button className="btn-secondary" onClick={openCv} disabled={opening}>
            {opening ? <Spinner /> : <ExternalLink className="size-4" aria-hidden />} Open current CV
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="btn-secondary cursor-pointer">
          <FileUp className="size-4" aria-hidden />
          {file ? file.name : detail.has_resume ? "Choose a new CV" : "Choose your CV"}
          <input
            ref={input}
            type="file"
            accept=".pdf,.txt"
            className="sr-only"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setSaved(false);
            }}
          />
        </label>
        <button className="btn" onClick={upload} disabled={!file || busy}>
          {busy && <Spinner />}
          {busy ? "Reading your CV…" : detail.has_resume ? "Replace CV" : "Upload CV"}
        </button>
        <span className="text-xs text-slate-400">PDF or TXT. Text-based PDFs work best (not scans).</span>
      </div>

      <ErrorBox message={error} />
      {saved && <SuccessBox>CV saved. We found {detail.parsed_resume.skills.length} skills in it.</SuccessBox>}
    </section>
  );
}
