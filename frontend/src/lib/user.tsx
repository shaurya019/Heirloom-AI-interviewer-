import { createContext, useContext, type ReactNode } from "react";
import { useLocalStorage } from "./hooks";

const Ctx = createContext<{ userId: string; setUserId: (id: string) => void } | null>(null);

export function UserProvider({ children }: { children: ReactNode }) {
  const [userId, setUserId] = useLocalStorage("heirloom.userId", "frank");
  return <Ctx.Provider value={{ userId, setUserId }}>{children}</Ctx.Provider>;
}

export function useUser() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useUser outside UserProvider");
  return c;
}
