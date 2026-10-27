"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface Result<T> { key: string; data?: T; error?: string }

/**
 * Loads data for `key` (anything that should trigger a refetch) and exposes loading / error / reload / mutate.
 * State is only set after the request resolves, and `loading` is derived from the key, so the effect never
 * sets state synchronously.
 */
export function useLoad<T>(key: string, fn: () => Promise<T>) {
  const [res, setRes] = useState<Result<T> | null>(null);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  useEffect(() => { fnRef.current = fn; });
  const full = `${key}#${tick}`;

  useEffect(() => {
    let live = true;
    fnRef.current().then(
      (data) => { if (live) setRes({ key: full, data }); },
      (e: unknown) => { if (live) setRes({ key: full, error: e instanceof Error ? e.message : String(e) }); },
    );
    return () => { live = false; };
  }, [full]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const mutate = useCallback((data: T) => setRes({ key: full, data }), [full]);
  const current = res && res.key === full ? res : null;
  return { data: current?.data, error: current?.error ?? null, loading: current === null, reload, mutate };
}
