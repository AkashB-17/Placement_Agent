/**
 * The app's logo: a briefcase (jobs) with a check mark (placed / eligible).
 * Drawn in the same 24×24, 2px-stroke style as the lucide icons used everywhere else,
 * so it inherits the text colour like they do. app/icon.svg is the same mark as the favicon.
 */
export function LogoMark({ className = "size-5" }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <rect x="2" y="7" width="20" height="14" rx="2.5" />
      <path d="m8.5 14 2.5 2.5 4.5-4.5" />
    </svg>
  );
}
