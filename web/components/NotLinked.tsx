import { Link2Off } from "lucide-react";

import { EmptyState } from "./ui";

/** Shown to a signed-in student whose email isn't on any student record yet. */
export function NotLinked() {
  return (
    <EmptyState icon={Link2Off} title="Your account isn't linked to a student record yet">
      Ask the placement office to add you using the email you sign in with. Once they have, your jobs, eligibility and
      CV upload appear here.
    </EmptyState>
  );
}
