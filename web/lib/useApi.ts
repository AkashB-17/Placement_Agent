"use client";

import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "./api";
import { supabase } from "./supabase";

/**
 * GET with an in-memory cache: a page revisited in the same session shows its last data
 * at once and refreshes it in the background (stale-while-revalidate). The cache lives
 * only in this tab's memory and is wiped on sign-out, so one user's data never shows for
 * another.
 */
const cache = new Map<string, unknown>();
const inflight = new Map<string, Promise<unknown>>();

supabase.auth.onAuthStateChange((event) => {
  if (event === "SIGNED_OUT" || event === "SIGNED_IN") cache.clear();
});

function load<T>(path: string): Promise<T> {
  let request = inflight.get(path) as Promise<T> | undefined;
  if (!request) {
    request = api<T>(path).finally(() => inflight.delete(path));
    inflight.set(path, request);
  }
  return request;
}

/** Drop cached GETs whose path starts with any prefix (call after a write). */
export function invalidate(...prefixes: string[]) {
  for (const key of cache.keys()) {
    if (prefixes.some((p) => key.startsWith(p))) cache.delete(key);
  }
}

export function useApi<T>(path: string | null, options: { revalidate?: boolean } = {}) {
  // revalidate=false: cached data is final until refresh() (for expensive calls like /ranked).
  const revalidate = options.revalidate ?? true;
  const [data, setData] = useState<T | undefined>(() => (path ? (cache.get(path) as T | undefined) : undefined));
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(Boolean(path) && !cache.has(path ?? ""));

  const refresh = useCallback(async () => {
    if (!path) return;
    // Pages show skeletons only for `loading && !data`, so a background refresh stays quiet.
    setLoading(true);
    try {
      const fresh = await load<T>(path);
      cache.set(path, fresh);
      setData(fresh);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    if (!path) {
      setData(undefined);
      setLoading(false);
      return;
    }
    setData(cache.get(path) as T | undefined);
    setError(null);
    if (revalidate || !cache.has(path)) void refresh();
  }, [path, refresh, revalidate]);

  return { data, error, loading, refresh };
}
