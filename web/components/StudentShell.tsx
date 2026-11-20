"use client";

import { Briefcase, FileText, LogOut, Menu, Rocket, Send, Sparkles, X, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useAuth } from "@/lib/auth";

import { NotificationBell } from "./NotificationBell";
import { Avatar } from "./ui";

const STUDENT_LINKS: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/me", label: "Jobs", icon: Briefcase },
  { href: "/me/applications", label: "Applications", icon: Send },
  { href: "/me/profile", label: "Profile & CV", icon: FileText },
  { href: "/me/auto-apply", label: "Auto-apply", icon: Rocket },
];

// "/me" is a prefix of the others, so it is only active on an exact match.
const isActive = (href: string, pathname: string) => (href === "/me" ? pathname === "/me" : pathname.startsWith(href));

function AccountMenu() {
  const { profile, signOut } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div className="relative" ref={box}>
      <button onClick={() => setOpen(!open)} aria-label="Account menu" aria-expanded={open} className="rounded-full">
        <Avatar name={profile?.email ?? "?"} className="size-9 text-sm" />
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-3 shadow-lg">
          <p className="truncate text-sm font-medium text-slate-800">{profile?.email}</p>
          <p className="text-xs text-slate-500">Student</p>
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
      )}
    </div>
  );
}

/** Layout for students: top bar (notifications, account) and a compact icon menu. */
export function StudentShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-slate-200 bg-white/95 px-4 backdrop-blur">
        <button className="btn-ghost px-2 lg:hidden" onClick={() => setMenuOpen(true)} aria-label="Open menu">
          <Menu className="size-5" aria-hidden />
        </button>
        <Link href="/me" className="flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-lg bg-brand-600 text-white shadow-sm">
            <Sparkles className="size-4" aria-hidden />
          </span>
          <span className="text-base font-semibold text-slate-900">Placement Portal</span>
        </Link>
        <div className="ml-auto flex items-center gap-2">
          <NotificationBell />
          <AccountMenu />
        </div>
      </header>

      <nav
        className="fixed top-16 bottom-0 left-0 z-20 hidden w-24 flex-col items-stretch gap-1 border-r border-slate-200 bg-white px-2 py-4 lg:flex"
        aria-label="Student"
      >
        {STUDENT_LINKS.map(({ href, label, icon: Icon }) => {
          const active = isActive(href, pathname);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`flex flex-col items-center gap-1 rounded-lg px-1 py-2.5 text-center text-[11px] font-medium transition ${
                active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              }`}
            >
              <Icon className={`size-5 ${active ? "text-brand-600" : "text-slate-500"}`} aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>

      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-slate-900/30" onClick={() => setMenuOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-white p-4 shadow-xl">
            <button className="btn-ghost absolute top-4 right-3" onClick={() => setMenuOpen(false)} aria-label="Close menu">
              <X className="size-5" aria-hidden />
            </button>
            <p className="mb-6 px-2 font-semibold">Placement Portal</p>
            <nav className="flex flex-col gap-1">
              {STUDENT_LINKS.map(({ href, label, icon: Icon }) => {
                const active = isActive(href, pathname);
                return (
                  <Link
                    key={href}
                    href={href}
                    onClick={() => setMenuOpen(false)}
                    className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${
                      active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    <Icon className="size-4" aria-hidden /> {label}
                  </Link>
                );
              })}
            </nav>
          </aside>
        </div>
      )}

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:pl-32">{children}</main>
    </div>
  );
}
