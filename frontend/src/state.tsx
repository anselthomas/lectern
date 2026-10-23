import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { hasSession } from "./auth";

type MeCtx = { me: any; loading: boolean; refresh: () => Promise<any>; setMe: (m: any) => void };
const Ctx = createContext<MeCtx>({ me: null, loading: true, refresh: async () => null, setMe: () => undefined });

export function MeProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<any>(null);
  const [loading, setLoading] = useState(hasSession());
  const refresh = useCallback(async () => {
    if (!hasSession()) { setMe(null); setLoading(false); return null; }
    try {
      const m = await api("/me");
      setMe(m);
      return m;
    } catch {
      setMe(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    refresh();
    const out = () => setMe(null);
    window.addEventListener("lectern:signed-out", out);
    return () => window.removeEventListener("lectern:signed-out", out);
  }, [refresh]);
  return <Ctx.Provider value={{ me, loading, refresh, setMe }}>{children}</Ctx.Provider>;
}

export const useMe = () => useContext(Ctx);

/** Fetch helper with loading/error state and manual reload. */
export function useApi<T = any>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<any>(null);
  const [loading, setLoading] = useState(!!path);
  const load = useCallback(async (quiet = false) => {
    if (!path) return;
    if (!quiet) setLoading(true);
    try {
      const d = await api<T>(path);
      setData(d);
      setError(null);
      return d;
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [path, ...deps]);
  useEffect(() => { load(); }, [load]);
  return { data, error, loading, reload: load, setData };
}
