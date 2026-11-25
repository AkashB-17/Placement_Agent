"use client";

import { Briefcase, FileUp, GraduationCap, Rocket, ScrollText, X, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState, type DragEvent, type FormEvent, type InputHTMLAttributes } from "react";

import { ErrorBox, PageHeader, Spinner, SuccessBox, Warnings, errorText } from "@/components/ui";
import { api } from "@/lib/api";
import { RequireRole, useAuth } from "@/lib/auth";
import type { IngestResponse } from "@/lib/types";
import { invalidate } from "@/lib/useApi";

type Tab = "policy" | "jd" | "student";
type Status = { busy: boolean; error: string | null; result: IngestResponse | null };
const IDLE: Status = { busy: false, error: null, result: null };

function useSubmit(path: string, invalidates: string[]) {
  const [status, setStatus] = useState<Status>(IDLE);
  async function submit(form: FormData) {
    setStatus({ busy: true, error: null, result: null });
    try {
      const result = await api<IngestResponse>(path, { method: "POST", body: form });
      invalidate(...invalidates);
      setStatus({ busy: false, error: null, result });
      return true;
    } catch (e) {
      setStatus({ busy: false, error: errorText(e), result: null });
      return false;
    }
  }
  return { status, submit };
}

function Result({ status, noun }: { status: Status; noun: string }) {
  return (
    <div className="space-y-2">
      <ErrorBox message={status.error} />
      {status.result && (
        <SuccessBox>
          {noun} saved <span className="text-emerald-600">(id {status.result.id.slice(0, 8)})</span>.
        </SuccessBox>
      )}
      {status.result?.auto_apply && (
        <p className="flex items-start gap-2 rounded-lg border border-brand-200 bg-brand-50 p-3 text-sm text-brand-700">
          <Rocket className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{status.result.auto_apply} Results appear under Applications.</span>
        </p>
      )}
      <Warnings items={status.result?.warnings} />
    </div>
  );
}

/** Click-or-drop file picker for .pdf/.txt. */
function DropZone({ file, onFile, name, required }: { file: File | null; onFile: (f: File | null) => void; name?: string; required?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped && input.current) {
      const transfer = new DataTransfer();
      transfer.items.add(dropped);
      input.current.files = transfer.files; // keeps a named input in sync for FormData
      onFile(dropped);
    }
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={`relative rounded-xl border-2 border-dashed p-5 text-center transition ${
        over ? "border-brand-500 bg-brand-50" : "border-slate-200 bg-slate-50/50 hover:border-slate-300"
      }`}
    >
      <input
        ref={input}
        type="file"
        name={name}
        required={required}
        accept=".pdf,.txt"
        className="absolute inset-0 cursor-pointer opacity-0"
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        aria-label="Choose a .pdf or .txt file"
      />
      {file ? (
        <div className="flex items-center justify-center gap-2 text-sm">
          <FileUp className="size-4 text-brand-600" aria-hidden />
          <span className="font-medium text-slate-800">{file.name}</span>
          <span className="text-slate-400">({Math.max(1, Math.round(file.size / 1024))} KB)</span>
          <button
            type="button"
            className="relative z-10 rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
            onClick={() => {
              if (input.current) input.current.value = "";
              onFile(null);
            }}
            aria-label="Remove file"
          >
            <X className="size-4" aria-hidden />
          </button>
        </div>
      ) : (
        <div className="pointer-events-none text-sm text-slate-500">
          <FileUp className="mx-auto mb-1.5 size-5 text-slate-400" aria-hidden />
          <span className="font-medium text-brand-600">Choose a file</span> or drag it here
          <span className="block text-xs text-slate-400">.pdf or .txt</span>
        </div>
      )}
    </div>
  );
}

/** Text area or a .pdf/.txt file (the API rejects both at once). */
function DocumentForm({ path, noun, hint, invalidates }: { path: string; noun: string; hint: string; invalidates: string[] }) {
  const { status, submit } = useSubmit(path, invalidates);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [formKey, setFormKey] = useState(0);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData();
    if (file) form.append("file", file);
    else form.append("text", text);
    if (await submit(form)) {
      setText("");
      setFile(null);
      setFormKey((k) => k + 1); // remounts the drop zone, clearing its input
    }
  }

  return (
    <form onSubmit={onSubmit} className="card space-y-4">
      <p className="text-sm text-slate-500">{hint}</p>
      <div>
        <label className="label" htmlFor={`${noun}-text`}>Paste the text</label>
        <textarea
          id={`${noun}-text`}
          className="input h-44 font-mono text-[13px]"
          placeholder={file ? "Using the file below" : `Paste the ${noun} here…`}
          value={text}
          disabled={file !== null}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      <div className="flex items-center gap-3 text-xs text-slate-400 uppercase">
        <span className="h-px flex-1 bg-slate-200" /> or upload <span className="h-px flex-1 bg-slate-200" />
      </div>
      <DropZone key={formKey} file={file} onFile={setFile} />
      <div className="flex justify-end">
        <button className="btn" disabled={status.busy || (!file && !text.trim())}>
          {status.busy && <Spinner />}
          {status.busy ? "Reading and extracting rules…" : `Save ${noun}`}
        </button>
      </div>
      <Result status={status} noun={noun.charAt(0).toUpperCase() + noun.slice(1)} />
    </form>
  );
}

function Field({ label, name, hint, ...rest }: { label: string; name: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <label className="label" htmlFor={name}>{label}</label>
      <input id={name} name={name} className="input" {...rest} />
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

function StudentForm() {
  // A new student changes every ranking, so cached /jds/{id}/ranked results go too.
  const { status, submit } = useSubmit("/students", ["/students", "/jds/"]);
  const [file, setFile] = useState<File | null>(null);
  const [formKey, setFormKey] = useState(0);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    form.set("is_placed", form.get("is_placed") ? "true" : "false");
    if (!form.get("email")) form.delete("email");
    const cv = form.get("resume");
    if (!(cv instanceof File) || cv.size === 0) form.delete("resume"); // CV is optional
    if (await submit(form)) {
      setFile(null);
      setFormKey((k) => k + 1);
    }
  }

  return (
    <form key={formKey} onSubmit={onSubmit} className="card space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Full name" name="name" required />
        <Field label="Login email" name="email" type="email" hint="Links the record to the student's account so they can upload their CV. Required unless you attach a CV." />
        <Field label="Branch" name="branch" placeholder="CSE" required />
        <Field label="Batch (graduation year)" name="batch" placeholder="2027" required />
        <Field label="CGPA" name="cgpa" type="number" step="0.01" min="0" max="10" placeholder="0 – 10" required />
        <Field label="Active backlogs" name="active_backlogs" type="number" min="0" defaultValue="0" required />
      </div>
      <label className="flex w-fit items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" name="is_placed" className="size-4 rounded border-slate-300 accent-brand-600" /> Already placed
      </label>
      <div>
        <p className="label">CV <span className="font-normal text-slate-400">(optional: students upload their own)</span></p>
        <DropZone file={file} onFile={setFile} name="resume" />
      </div>
      <div className="flex justify-end">
        <button className="btn" disabled={status.busy}>
          {status.busy && <Spinner />}
          {status.busy ? "Parsing resume…" : "Save student"}
        </button>
      </div>
      <Result status={status} noun="Student" />
    </form>
  );
}

const TABS: { key: Tab; label: string; icon: LucideIcon; staffOnly: boolean }[] = [
  { key: "policy", label: "Placement policy", icon: ScrollText, staffOnly: true },
  { key: "jd", label: "Job description", icon: Briefcase, staffOnly: false },
  { key: "student", label: "Student", icon: GraduationCap, staffOnly: true },
];

function UploadPage() {
  const { profile } = useAuth();
  const staff = profile?.role === "officer" || profile?.role === "admin";
  const tabs = TABS.filter((t) => staff || !t.staffOnly);
  const [tab, setTab] = useState<Tab>(staff ? "policy" : "jd");

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("tab") as Tab | null;
    if (requested && tabs.some((t) => t.key === requested)) setTab(requested);
  }, []); // read the URL once on load

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Upload"
        subtitle="AI reads the document into rules, then each rule is checked against the text. A rule the document doesn't state is dropped and listed as a warning."
      />
      {tabs.length > 1 && (
        <div className="mb-6 flex gap-1 border-b border-slate-200" role="tablist">
          {tabs.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={`-mb-px flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition ${
                tab === key ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </button>
          ))}
        </div>
      )}
      {tab === "policy" && staff && (
        <DocumentForm
          path="/policies"
          noun="policy"
          hint="The campus placement policy: CGPA cut-off, backlogs, branches, batches and the rule for already-placed students."
          invalidates={["/policies", "/jds/"]}
        />
      )}
      {tab === "jd" && (
        <DocumentForm
          path="/jds"
          noun="job description"
          hint="Company, role, required and preferred skills, and any extra eligibility rules the company sets."
          invalidates={["/jds"]}
        />
      )}
      {tab === "student" && staff && <StudentForm />}
    </div>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["officer", "admin", "recruiter"]}>
      <UploadPage />
    </RequireRole>
  );
}
