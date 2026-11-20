"use client";

import { Rocket } from "lucide-react";
import Link from "next/link";

import { ApplicationCard } from "@/components/ApplicationCard";
import { NotLinked } from "@/components/NotLinked";
import { CardSkeletons, EmptyState, ErrorBox, PageHeader } from "@/components/ui";
import { RequireRole } from "@/lib/auth";
import type { Application, StudentDetail } from "@/lib/types";
import { invalidate, useApi } from "@/lib/useApi";

function ApplicationsPage() {
  const me = useApi<StudentDetail>("/students/me");
  const applications = useApi<Application[]>(me.data ? "/me/applications" : null);

  if (me.error?.status === 404) return <NotLinked />;

  return (
    <>
      <PageHeader
        title="My applications"
        subtitle="Applications made for you by auto-apply. A pending application is sent when its countdown ends; withdraw before then if you don't want it."
      />
      <ErrorBox message={me.error?.message ?? applications.error?.message} />
      {applications.loading && !applications.data ? (
        <CardSkeletons count={2} />
      ) : !applications.data?.length ? (
        <EmptyState icon={Rocket} title="No applications yet">
          Turn on <Link href="/me/auto-apply" className="font-medium text-brand-700 hover:underline">auto-apply</Link> and
          you&apos;ll appear here when the placement office runs it for a job you qualify for.
        </EmptyState>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {applications.data.map((a) => (
            <ApplicationCard
              key={a.id}
              app={a}
              viewer="student"
              onChanged={() => {
                invalidate("/me/notifications", "/me/jobs");
                void applications.refresh();
              }}
            />
          ))}
        </div>
      )}
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["student"]}>
      <ApplicationsPage />
    </RequireRole>
  );
}
