"use client";

import { ScrollText } from "lucide-react";

import type { PolicySummary } from "@/lib/types";

export function policyLabel(p: PolicySummary): string {
  const parts = [
    p.min_cgpa !== null ? `CGPA ≥ ${p.min_cgpa}` : null,
    p.max_active_backlogs !== null ? `≤ ${p.max_active_backlogs} backlogs` : null,
    p.allowed_batches.length ? `batch ${p.allowed_batches.join("/")}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : `Policy ${p.id.slice(0, 8)}`;
}

export function PolicyPicker({
  policies,
  value,
  onChange,
}: {
  policies: PolicySummary[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white py-1 pr-1 pl-3 text-sm shadow-sm">
      <ScrollText className="size-4 text-slate-400" aria-hidden />
      <span className="text-slate-500">Policy</span>
      <select
        className="max-w-72 rounded-md border-0 bg-transparent py-1 pr-7 pl-1 font-medium text-slate-800 focus:ring-2 focus:ring-brand-100 focus:outline-none"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {policies.map((p) => (
          <option key={p.id} value={p.id}>
            {policyLabel(p)}
          </option>
        ))}
      </select>
    </label>
  );
}
