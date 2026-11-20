"use client";

import { Bell, CheckCheck, Inbox } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { timeAgo, useNow } from "@/lib/time";
import type { Notification } from "@/lib/types";
import { useApi } from "@/lib/useApi";

/** Student notifications: unread badge, dropdown list, mark all read. Refreshes every minute. */
export function NotificationBell() {
  const { data, refresh } = useApi<Notification[]>("/me/notifications");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const now = useNow(60_000);
  const unread = data?.filter((n) => !n.read).length ?? 0;

  useEffect(() => {
    const id = window.setInterval(() => void refresh(), 60_000);
    return () => window.clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  async function markRead() {
    await api("/me/notifications/read", { method: "POST" });
    await refresh();
  }

  return (
    <div className="relative" ref={box}>
      <button
        className="relative rounded-full p-2 text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
        onClick={() => setOpen(!open)}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
      >
        <Bell className="size-5" aria-hidden />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex min-w-5 items-center justify-center rounded-full bg-rose-600 px-1 text-[11px] font-semibold text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-80 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
            <p className="font-semibold">Notifications</p>
            {unread > 0 && (
              <button className="btn-ghost ml-auto py-1 text-xs" onClick={markRead}>
                <CheckCheck className="size-3.5" aria-hidden /> Mark all read
              </button>
            )}
          </div>
          {!data?.length ? (
            <p className="flex items-center gap-2 px-4 py-6 text-sm text-slate-400">
              <Inbox className="size-4" aria-hidden /> Nothing yet.
            </p>
          ) : (
            <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto">
              {data.map((n) => (
                <li key={n.id} className={`px-4 py-3 text-sm ${n.read ? "text-slate-500" : "bg-brand-50/50 text-slate-800"}`}>
                  <p>{n.message}</p>
                  <p className="mt-0.5 text-xs text-slate-400">{timeAgo(n.created_at, now)}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
