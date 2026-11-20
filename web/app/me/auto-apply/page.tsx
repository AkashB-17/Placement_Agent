"use client";

import { AutoApplySettings } from "@/components/AutoApplySettings";
import { NotLinked } from "@/components/NotLinked";
import { CardSkeletons, PageHeader } from "@/components/ui";
import { RequireRole } from "@/lib/auth";
import type { StudentDetail } from "@/lib/types";
import { useApi } from "@/lib/useApi";

function AutoApplyPage() {
  const me = useApi<StudentDetail>("/students/me");
  if (me.error?.status === 404) return <NotLinked />;

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Auto-apply"
        subtitle="Let the system apply for you when you're eligible and your score clears your bar. Nothing is sent before you can review and withdraw it."
      />
      {me.data && !me.data.has_resume && (
        <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          Auto-apply needs your CV: upload it under Profile &amp; CV first, or you&apos;ll be skipped.
        </p>
      )}
      {me.loading && !me.data ? <CardSkeletons count={1} /> : <AutoApplySettings />}
    </div>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["student"]}>
      <AutoApplyPage />
    </RequireRole>
  );
}
