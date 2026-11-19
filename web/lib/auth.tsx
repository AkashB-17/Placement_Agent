"use client";

import type { Session } from "@supabase/supabase-js";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { api, ApiError } from "./api";
import { supabase } from "./supabase";
import type { Profile, Role } from "./types";

interface AuthState {
  loading: boolean;
  session: Session | null;
  profile: Profile | null;
  error: string | null;
  /** Why the user was signed out automatically (shown on the sign-in page). */
  notice: string | null;
  signIn: (email: string, password: string) => Promise<string | null>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const userIdRef = useRef<string | null | undefined>(undefined);

  // The role comes from the backend (public.profiles), never from the token's user_metadata.
  const loadProfile = useCallback(async (next: Session | null) => {
    setSession(next);
    setError(null);
    if (!next) {
      setProfile(null);
      setLoading(false);
      return;
    }
    try {
      setProfile(await api<Profile>("/admin/me"));
      setNotice(null);
    } catch (e) {
      setProfile(null);
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        // The API rejects this session (expired, revoked, or no profile). Keeping it would
        // leave the user stuck on an error page, so sign out locally and explain on /login.
        setNotice(
          e.status === 401
            ? "Your session has expired or is no longer valid. Please sign in again."
            : "This account has no profile on the server yet. If you were just invited, open the link in your email; otherwise contact the placement office.",
        );
        userIdRef.current = null;
        setSession(null);
        await supabase.auth.signOut({ scope: "local" });
      } else {
        // API unreachable or misconfigured: keep the session so signing in again retries.
        setError(e instanceof ApiError ? e.message : "Could not load your profile.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Re-read the profile whenever the signed-in *user* changes, whatever the event: a normal
  // sign-in, an email-confirmation link, an invite link or a password-reset link
  // (PASSWORD_RECOVERY). Token refreshes keep the same user and only update the session.
  useEffect(() => {
    const handle = (next: Session | null) => {
      const nextId = next?.user.id ?? null;
      if (nextId !== userIdRef.current) {
        userIdRef.current = nextId;
        void loadProfile(next);
      } else {
        setSession(next);
      }
    };
    supabase.auth.getSession().then(({ data }) => handle(data.session));
    const { data: listener } = supabase.auth.onAuthStateChange((_event, next) => handle(next));
    return () => listener.subscription.unsubscribe();
  }, [loadProfile]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const { data, error: signInError } = await supabase.auth.signInWithPassword({ email, password });
      if (signInError) return signInError.message;
      // Always (re)load the profile: signing in again as the same user after a failed load
      // would otherwise be treated as "same user" and never retry.
      setNotice(null);
      userIdRef.current = data.session?.user.id ?? null;
      await loadProfile(data.session);
      return null;
    },
    [loadProfile],
  );

  const signOut = useCallback(async () => {
    setNotice(null);
    await supabase.auth.signOut();
  }, []);

  return (
    <AuthContext.Provider value={{ loading, session, profile, error, notice, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

export function homeFor(role: Role): string {
  switch (role) {
    case "student":
      return "/me";
    case "recruiter":
      return "/applications";
    default:
      return "/jobs";
  }
}

/**
 * Hides a page from roles that can't use it. This is only UX: the API enforces the
 * same rules (require_role) and would refuse the requests anyway.
 */
export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { loading, session, profile } = useAuth();
  const router = useRouter();
  // Anything short of a loaded profile (signed out, rejected session, API unreachable) goes
  // to /login, which shows why. Never leave the user on a dead-end error page.
  const ready = !loading && Boolean(session) && Boolean(profile);

  useEffect(() => {
    if (!loading && !ready) router.replace("/login");
  }, [loading, ready, router]);

  if (!ready || !profile) return <FullPageSpinner />;
  if (!roles.includes(profile.role)) {
    return (
      <Notice title="This page isn't available for your role" tone="warning">
        <p>You're signed in as {profile.role}.</p>
        <Link href={homeFor(profile.role)} className="btn-secondary mt-4">
          Go to my home page
        </Link>
      </Notice>
    );
  }
  return <>{children}</>;
}

export function FullPageSpinner() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center text-slate-400" role="status">
      <Loader2 className="size-6 animate-spin" aria-hidden />
      <span className="sr-only">Loading</span>
    </div>
  );
}

function Notice({ title, tone, children }: { title: string; tone: "error" | "warning"; children: ReactNode }) {
  const color = tone === "error" ? "border-rose-200 bg-rose-50 text-rose-900" : "border-amber-200 bg-amber-50 text-amber-900";
  return (
    <div className="mx-auto mt-16 max-w-md">
      <div className={`rounded-xl border p-6 text-sm ${color}`}>
        <p className="mb-1 text-base font-semibold">{title}</p>
        {children}
      </div>
    </div>
  );
}
