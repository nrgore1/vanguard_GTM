import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, session, type Property, type User } from "./api";

interface AuthState {
  user: User | null; loading: boolean; properties: Property[]; users: { id: number; name: string; role: string }[];
  login: (email: string, password: string) => Promise<void>; logout: () => void; isAdmin: boolean;
  propName: (id: string) => string; refreshUsers: () => void;
}
const Ctx = createContext<AuthState>(null as unknown as AuthState);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [properties, setProperties] = useState<Property[]>([]);
  const [users, setUsers] = useState<{ id: number; name: string; role: string }[]>([]);

  const loadShared = useCallback(async () => {
    const [p, u] = await Promise.all([api.properties(), api.users()]);
    setProperties(p);
    setUsers(u);
  }, []);

  useEffect(() => {
    const out = () => setUser(null);
    window.addEventListener("vanguard:logout", out);
    if (!session.token) { setLoading(false); return () => window.removeEventListener("vanguard:logout", out); }
    api.me().then(async (u) => { setUser(u); await loadShared(); }).catch(() => session.clear()).finally(() => setLoading(false));
    return () => window.removeEventListener("vanguard:logout", out);
  }, [loadShared]);

  const login = async (email: string, password: string) => {
    const r = await api.login(email, password);
    session.set(r.token);
    setUser(r.user);
    await loadShared();
  };
  const logout = () => { session.clear(); setUser(null); };
  const names = Object.fromEntries(properties.map((p) => [p.id, p.name]));

  return (
    <Ctx.Provider value={{
      user, loading, properties, users, login, logout, isAdmin: user?.role === "admin",
      propName: (id) => names[id] ?? id, refreshUsers: () => { api.users().then(setUsers); },
    }}>
      {children}
    </Ctx.Provider>
  );
}

/** Tiny data hook: load(), with loading/error state and a reload(). */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    fn().then((d) => { setData(d); setError(null); }).catch(setError).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload, setData };
}
