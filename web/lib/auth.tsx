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
  signIn: (email: string, password: string) => Promise<string | null>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    } catch (e) {
      setProfile(null);
      setError(e instanceof ApiError ? e.message : "Could not load your profile.");
    } finally {
      setLoading(false);
    }
  }, []);

  // Re-read the profile whenever the signed-in *user* changes, whatever the event: a normal
  // sign-in, an email-confirmation link, an invite link or a password-reset link
  // (PASSWORD_RECOVERY). Token refreshes keep the same user and only update the session.
  const userIdRef = useRef<string | null | undefined>(undefined);
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

  const signIn = useCallback(async (email: string, password: string) => {
    const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
    return signInError ? signInError.message : null;
  }, []);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
  }, []);

  return (
    <AuthContext.Provider value={{ loading, session, profile, error, signIn, signOut }}>
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
  const { loading, session, profile, error, signOut } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !session) router.replace("/login");
  }, [loading, session, router]);

  if (loading || !session) return <FullPageSpinner />;
  if (error || !profile) {
    return (
      <Notice title="We couldn't load your account" tone="error">
        <p>{error ?? "No profile exists for this account."}</p>
        <button
          className="btn-secondary mt-4"
          onClick={async () => {
            await signOut();
            router.replace("/login");
          }}
        >
          Sign out
        </button>
      </Notice>
    );
  }
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
