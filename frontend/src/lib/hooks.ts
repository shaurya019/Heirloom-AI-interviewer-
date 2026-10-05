import { useEffect, useState } from "react";

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function useLocalStorage(key: string, initial: string): [string, (v: string) => void] {
  const [v, setV] = useState<string>(() => {
    try { return localStorage.getItem(key) ?? initial; } catch { return initial; }
  });
  const set = (nv: string) => {
    setV(nv);
    try { localStorage.setItem(key, nv); } catch { /* storage unavailable */ }
  };
  return [v, set];
}
