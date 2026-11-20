"use client";

import { JobBoard } from "@/components/JobBoard";
import { RequireRole } from "@/lib/auth";

export default function Page() {
  return (
    <RequireRole roles={["student"]}>
      <JobBoard />
    </RequireRole>
  );
}
