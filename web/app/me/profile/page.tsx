"use client";

import { GraduationCap, Lock } from "lucide-react";

import { NotLinked } from "@/components/NotLinked";
import { StudentCvCard } from "@/components/StudentCvCard";
import { Avatar, CardSkeletons, Chip, Chips, ErrorBox, PageHeader } from "@/components/ui";
import { RequireRole } from "@/lib/auth";
import type { StudentDetail } from "@/lib/types";
import { invalidate, useApi } from "@/lib/useApi";

function ProfilePage() {
  const me = useApi<StudentDetail>("/students/me");
  if (me.error?.status === 404) return <NotLinked />;
  const profile = me.data?.profile;

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Profile & CV" subtitle="Your academic details come from the placement office. Your CV is yours to upload and update." />
      <ErrorBox message={me.error?.message} />
      {me.loading && !me.data ? (
        <CardSkeletons count={2} />
      ) : (
        profile &&
        me.data && (
          <>
            <section className="card mb-6 space-y-5">
              <div className="flex flex-wrap items-center gap-4">
                <Avatar name={profile.name} className="size-14 text-lg" />
                <div>
                  <p className="text-lg font-semibold">{profile.name}</p>
                  <p className="text-sm text-slate-500">{profile.email}</p>
                </div>
              </div>
              <div>
                <p className="eyebrow mb-2 flex items-center gap-1.5">
                  <Lock className="size-3" aria-hidden /> Academic record (set by the placement office)
                </p>
                <div className="flex flex-wrap gap-1.5">
                  <Chip tone="brand" icon={GraduationCap}>{profile.branch} · batch {profile.batch}</Chip>
                  <Chip>CGPA {profile.cgpa.toFixed(2)}</Chip>
                  <Chip tone={profile.active_backlogs > 0 ? "red" : "slate"}>{profile.active_backlogs} active backlogs</Chip>
                  {profile.is_placed && <Chip tone="green">Placed</Chip>}
                </div>
                <p className="mt-2 text-xs text-slate-400">Something wrong here? Contact the placement office to correct it.</p>
              </div>
              <div>
                <p className="eyebrow mb-2">Skills found in your CV</p>
                <Chips items={me.data.parsed_resume.skills} tone="slate" empty={me.data.has_resume ? "None found" : "Upload your CV below"} />
              </div>
            </section>
            <StudentCvCard
              detail={me.data}
              onUploaded={() => {
                // A new CV changes skills and scores.
                invalidate("/students/me", "/me/jobs");
                void me.refresh();
              }}
            />
          </>
        )
      )}
    </div>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["student"]}>
      <ProfilePage />
    </RequireRole>
  );
}
