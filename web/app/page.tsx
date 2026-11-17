"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ErrorBox } from "@/components/ui";
import { FullPageSpinner, homeFor, useAuth } from "@/lib/auth";

export default function Home() {
  const { loading, session, profile, error } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!session) router.replace("/login");
    else if (profile) router.replace(homeFor(profile.role));
  }, [loading, session, profile, router]);

  if (error) {
    return (
      <div className="mx-auto mt-16 max-w-md px-4">
        <ErrorBox message={error} />
      </div>
    );
  }
  return <FullPageSpinner />;
}
