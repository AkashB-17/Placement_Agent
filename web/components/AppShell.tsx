"use client";

import { BarChart3, GraduationCap, LogOut, Menu, Send, ShieldCheck, Sparkles, Upload, UserRound, Users, X, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";

import { Avatar } from "./ui";

const LINKS: { href: string; label: string; icon: LucideIcon; roles: Role[] }[] = [
  { href: "/jobs", label: "Rank candidates", icon: BarChart3, roles: ["officer", "admin"] },
  { href: "/students", label: "Students", icon: GraduationCap, roles: ["officer", "admin"] },
  { href: "/applications", label: "Applications", icon: Send, roles: ["officer", "admin", "recruiter"] },
  { href: "/upload", label: "Upload", icon: Upload, roles: ["officer", "admin", "recruiter"] },
  { href: "/me", label: "My placements", icon: UserRound, roles: ["student"] },
  { href: "/admin", label: "Users & roles", icon: Users, roles: ["admin"] },
];

const ROLE_LABEL: Record<Role, string> = {
  admin: "Administrator",
  officer: "Placement officer",
  recruiter: "Recruiter",
  student: "Student",
};

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2.5 px-2">
      <span className="flex size-8 items-center justify-center rounded-lg bg-brand-600 text-white shadow-sm">
        <Sparkles className="size-4" aria-hidden />
      </span>
      <span className="leading-tight">
        <span className="block text-sm font-semibold text-slate-900">Placement Portal</span>
        <span className="block text-[11px] text-slate-500">Eligibility &amp; skill matching</span>
      </span>
    </Link>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { profile, signOut } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  if (!profile) return null;

  return (
    <div className="flex h-full flex-col gap-6 p-4">
      <Brand />
      <nav className="flex flex-1 flex-col gap-1" aria-label="Main">
        {LINKS.filter((l) => l.roles.includes(profile.role)).map(({ href, label, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              }`}
            >
              <Icon className={`size-4 ${active ? "text-brand-600" : "text-slate-400"}`} aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center gap-3">
          <Avatar name={profile.email ?? "?"} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-800" title={profile.email ?? undefined}>
              {profile.email}
            </p>
            <p className="flex items-center gap-1 text-xs text-slate-500">
              <ShieldCheck className="size-3" aria-hidden />
              {ROLE_LABEL[profile.role]}
            </p>
          </div>
        </div>
        <button
          className="btn-ghost mt-3 w-full justify-start"
          onClick={async () => {
            await signOut();
            router.replace("/login");
          }}
        >
          <LogOut className="size-4" aria-hidden /> Sign out
        </button>
      </div>
    </div>
  );
}

/** Sidebar layout for signed-in pages; the login page renders without it. */
export function AppShell({ children }: { children: ReactNode }) {
  const { profile } = useAuth();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  if (!profile || pathname === "/login") {
    return <main className="min-h-screen">{children}</main>;
  }

  return (
    <div className="min-h-screen lg:pl-64">
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-slate-200 bg-white lg:block">
        <SidebarContent />
      </aside>

      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur lg:hidden">
        <Brand />
        <button className="btn-ghost" onClick={() => setMenuOpen(true)} aria-label="Open menu">
          <Menu className="size-5" aria-hidden />
        </button>
      </header>

      {menuOpen && (
        <div className="fixed inset-0 z-30 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-slate-900/30" onClick={() => setMenuOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-white shadow-xl">
            <button className="btn-ghost absolute top-4 right-3" onClick={() => setMenuOpen(false)} aria-label="Close menu">
              <X className="size-5" aria-hidden />
            </button>
            <SidebarContent onNavigate={() => setMenuOpen(false)} />
          </aside>
        </div>
      )}

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-10">{children}</main>
    </div>
  );
}
