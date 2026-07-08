/** Cliente API: tenant por subdominio (automático vía Host) con fallback de
 * cabecera X-Tenant-Slug (?tenant=slug o localStorage) para el dominio
 * *.replit.app, donde no hay wildcard por tenant (ADR-0012). */

const API = "/api/v1";

export function tenantSlug(): string | null {
  const url = new URL(window.location.href);
  const fromQuery = url.searchParams.get("tenant");
  if (fromQuery) {
    localStorage.setItem("tenant_slug", fromQuery);
    return fromQuery;
  }
  return localStorage.getItem("tenant_slug");
}

// Captura el ?tenant de la URL en el arranque del módulo (antes de que el router
// pueda redirigir a /login y perder el query param). Sin esto, en la primera
// visita con localStorage vacío, la carrera de efectos de React haría que
// /branding se llamase sin X-Tenant-Slug y saliera "Asesoría no encontrada".
try {
  const t = new URL(window.location.href).searchParams.get("tenant");
  if (t) localStorage.setItem("tenant_slug", t);
} catch {
  /* entorno sin window: ignorar */
}

let accessToken: string | null = sessionStorage.getItem("access_token");
let refreshToken: string | null = localStorage.getItem("refresh_token");

export function setTokens(access: string | null, refresh: string | null) {
  accessToken = access;
  refreshToken = refresh;
  if (access) sessionStorage.setItem("access_token", access);
  else sessionStorage.removeItem("access_token");
  if (refresh) localStorage.setItem("refresh_token", refresh);
  else localStorage.removeItem("refresh_token");
}

function baseHeaders(): Record<string, string> {
  const h: Record<string, string> = {};
  const slug = tenantSlug();
  if (slug) h["X-Tenant-Slug"] = slug;
  if (accessToken) h["Authorization"] = `Bearer ${accessToken}`;
  return h;
}

async function tryRefresh(): Promise<boolean> {
  if (!refreshToken) return false;
  const res = await fetch(`${API}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...baseHeaders() },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) {
    setTokens(null, null);
    return false;
  }
  const data = await res.json();
  setTokens(data.access_token, data.refresh_token);
  return true;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function request(path: string, init: RequestInit = {}, retried = false): Promise<Response> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { ...baseHeaders(), ...(init.headers || {}) },
  });
  if (res.status === 403 && !retried && refreshToken && !path.startsWith("/auth/")) {
    if (await tryRefresh()) return request(path, init, true);
  }
  return res;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await request(path);
  if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail ?? "Error");
  return res.json();
}

export async function apiJson<T>(path: string, method: string, body: unknown): Promise<T> {
  const res = await request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, (data as { detail?: string }).detail ?? "Error");
  return data as T;
}

export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const res = await request(path, { method: "POST", body: form });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, (data as { detail?: string }).detail ?? "Error");
  return data as T;
}

export async function apiBlob(path: string): Promise<Blob> {
  const res = await request(path);
  if (!res.ok) throw new ApiError(res.status, "No se pudo descargar");
  return res.blob();
}
