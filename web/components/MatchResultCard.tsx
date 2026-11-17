"use client";

import { BookOpenText, ChevronDown, CircleCheck, CircleX, Quote, Rocket } from "lucide-react";
import { useState } from "react";

import type { MatchResult } from "@/lib/types";

import { Avatar, Chip, Chips, display } from "./ui";

/** Circular score gauge; colour follows the auto-apply threshold. */
export function ScoreRing({ score, threshold = 80, size = 56 }: { score: number; threshold?: number; size?: number }) {
  const stroke = 5;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const filled = (Math.min(Math.max(score, 0), 100) / 100) * circumference;
  const color = score >= threshold ? "text-emerald-500" : score >= threshold / 2 ? "text-amber-500" : "text-rose-500";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`Score ${score.toFixed(1)} out of 100`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={stroke} className="stroke-slate-100" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
          className={`stroke-current ${color} transition-[stroke-dasharray] duration-700`}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-sm font-semibold tabular-nums">{Math.round(score)}</span>
    </div>
  );
}

function SkillColumn({ title, matched, missing, missingTone }: { title: string; matched: string[]; missing: string[]; missingTone: "red" | "amber" }) {
  const total = matched.length + missing.length;
  return (
    <div>
      <p className="eyebrow mb-2">
        {title} <span className="font-normal normal-case text-slate-400">· {matched.length}/{total} matched</span>
      </p>
      {total === 0 ? (
        <p className="text-sm text-slate-400">None listed in the JD</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {matched.map((s, i) => (
            <Chip key={`m-${s}-${i}`} tone="green" icon={CircleCheck}>
              {s}
            </Chip>
          ))}
          {missing.map((s, i) => (
            <Chip key={`x-${s}-${i}`} tone={missingTone} icon={CircleX}>
              {s}
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}

/** One student's result for one JD: eligibility, score, evidence and cited clauses. */
export function MatchResultCard({
  result,
  threshold,
  rank,
  showName = true,
}: {
  result: MatchResult;
  /** Auto-apply threshold, when the API sent it (/ranked does; /match doesn't). */
  threshold?: number;
  rank?: number;
  showName?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { eligibility, score_breakdown: score, citations } = result;
  const hasDetails = Boolean(score) || citations.length > 0;

  return (
    <article className="card p-0">
      <div className="flex flex-wrap items-center gap-4 p-4 sm:p-5">
        {rank !== undefined && <span className="w-7 text-center text-sm font-semibold text-slate-400 tabular-nums">#{rank}</span>}
        {showName && <Avatar name={result.student_name} />}
        <div className="min-w-0 flex-1">
          {showName && <p className="font-medium text-slate-900">{result.student_name}</p>}
          <div className="mt-1 flex flex-wrap gap-1.5">
            {eligibility.eligible ? (
              <Chip tone="green" icon={CircleCheck}>Eligible</Chip>
            ) : (
              <Chip tone="red" icon={CircleX}>Not eligible</Chip>
            )}
            {result.auto_apply_recommended && (
              <Chip tone="brand" icon={Rocket}>
                Auto-apply recommended{threshold !== undefined ? ` (≥ ${threshold})` : ""}
              </Chip>
            )}
            {score && score.score === null && <Chip tone="slate">No required skills in JD</Chip>}
          </div>
        </div>
        {score && score.score !== null && <ScoreRing score={score.score} threshold={threshold ?? 80} />}
        {hasDetails && (
          <button className="btn-ghost" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? "Hide" : "Details"}
            <ChevronDown className={`size-4 transition ${open ? "rotate-180" : ""}`} aria-hidden />
          </button>
        )}
      </div>

      {!eligibility.eligible && (
        <ul className="space-y-1.5 border-t border-slate-100 px-4 py-3 text-sm sm:px-5">
          {eligibility.failed_rules.map((r) => (
            // A rule can fail twice (policy and JD both restrict branch/batch), so key by both.
            <li key={`${r.rule}-${r.source}`} className="flex gap-2">
              <CircleX className="mt-0.5 size-4 shrink-0 text-rose-500" aria-hidden />
              <span>
                <span className="text-slate-800 first-letter:uppercase">{r.description}</span>
                <span className="text-slate-500">
                  {" "}
                  · has {display(r.student_value)}, needs {display(r.required_value)}
                </span>
                <Chip tone="slate">{r.source === "jd" ? "from JD" : "from policy"}</Chip>
              </span>
            </li>
          ))}
        </ul>
      )}

      {open && score && (
        <div className="grid gap-6 border-t border-slate-100 bg-slate-50/60 p-4 sm:p-5 md:grid-cols-2">
          <SkillColumn title="Required skills" matched={score.matched_required} missing={score.missing_required} missingTone="red" />
          <SkillColumn title="Preferred skills" matched={score.matched_preferred} missing={score.missing_preferred} missingTone="amber" />
          <div className="md:col-span-2">
            <p className="eyebrow mb-2">Evidence from the resume · quotes checked word-for-word</p>
            {score.evidence.length ? (
              <ul className="grid gap-2 sm:grid-cols-2">
                {score.evidence.map((e, i) => (
                  <li key={`${e.skill}-${i}`} className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
                    <p className="mb-1 flex items-center gap-1.5 font-medium text-slate-800">
                      <Quote className="size-3.5 text-brand-500" aria-hidden />
                      {e.skill}
                    </p>
                    <p className="text-slate-600 italic">&ldquo;{e.quote}&rdquo;</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-400">No verified evidence.</p>
            )}
          </div>
        </div>
      )}

      {open && citations.length > 0 && (
        <div className="border-t border-slate-100 bg-slate-50/60 p-4 sm:p-5">
          <p className="eyebrow mb-3">Where the failed rules come from</p>
          <div className="space-y-4">
            {citations.map((c) => (
              <div key={`${c.rule}-${c.source}`}>
                <p className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-slate-800">
                  <BookOpenText className="size-4 text-slate-400" aria-hidden />
                  {c.rule.replaceAll("_", " ")}
                  <span className="font-normal text-slate-500">· {c.source === "jd" ? "job description" : "placement policy"}</span>
                </p>
                {c.chunks.map((chunk, i) => (
                  <blockquote key={i} className="mt-1.5 rounded-r-lg border-l-4 border-brand-200 bg-white px-3 py-2 text-sm whitespace-pre-line text-slate-600">
                    {chunk.text}
                  </blockquote>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}
