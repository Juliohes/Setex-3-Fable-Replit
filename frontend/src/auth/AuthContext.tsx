import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiGet, apiJson, setTokens } from "../api/client";

export interface Branding {
  tenant_slug: string;
  app_name: string;
  logo_url: string | null;
  color_primary: string;
  color_secondary: string;
}

interface Session {
  role: string;
  full_name: string;
  company_ids: string[];
}

interface AuthState {
  branding: Branding | null;
  brandingError: boolean;
  session: Session | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthState>(null as unknown as AuthState);

/** Convierte #RRGGBB en "R G B" para las CSS variables de Tailwind. */
function hexToRgb(hex: string): string {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)).join(" ");
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState<Branding | null>(null);
  const [brandingError, setBrandingError] = useState(false);
  const [session, setSession] = useState<Session | null>(() => {
    const raw = sessionStorage.getItem("session");
    return raw ? (JSON.parse(raw) as Session) : null;
  });

  useEffect(() => {
    apiGet<Branding>("/branding")
      .then((b) => {
        setBranding(b);
        document.title = b.app_name;
        const root = document.documentElement;
        root.style.setProperty("--color-primary", hexToRgb(b.color_primary));
        root.style.setProperty("--color-secondary", hexToRgb(b.color_secondary));
      })
      .catch(() => setBrandingError(true));
  }, []);

  async function login(email: string, password: string) {
    const data = await apiJson<{
      access_token: string;
      refresh_token: string;
      role: string;
      full_name: string;
      company_ids: string[];
    }>("/auth/login", "POST", { email, password });
    setTokens(data.access_token, data.refresh_token);
    const s = { role: data.role, full_name: data.full_name, company_ids: data.company_ids };
    sessionStorage.setItem("session", JSON.stringify(s));
    setSession(s);
  }

  function logout() {
    setTokens(null, null);
    sessionStorage.removeItem("session");
    setSession(null);
  }

  return (
    <Ctx.Provider value={{ branding, brandingError, session, login, logout }}>{children}</Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
