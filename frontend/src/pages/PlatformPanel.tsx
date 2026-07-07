import { useState, type FormEvent } from "react";

/** Panel de plataforma. Independiente del tenant: usa fetch directo. */
const API = "/api/v1/platform";

interface Tenant { id: string; slug: string; name: string; status: string; is_demo: boolean; custom_domain: string | null }
interface Metrics { slug: string; companies: number; users: number; invoices: number; ocr_cost_eur: string }

export default function PlatformPanel() {
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [totpUri, setTotpUri] = useState("");
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState("");
  const [slug, setSlug] = useState("");
  const [tname, setTname] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPass, setAdminPass] = useState("");
  const [c1, setC1] = useState("#FF7A00");
  const [c2, setC2] = useState("#1C1C1E");
  const [demo, setDemo] = useState(false);

  async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
    const res = await fetch(`${API}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error((data as { detail?: string }).detail ?? "Error");
    return data as T;
  }

  async function login(e: FormEvent) {
    e.preventDefault();
    setError(""); setTotpUri("");
    try {
      const data = await call<{ access_token: string; totp_provisioning_uri: string | null }>(
        "/auth/login", "POST", { email, password, otp }
      );
      if (data.totp_provisioning_uri) {
        setTotpUri(data.totp_provisioning_uri);
        return;
      }
      setToken(data.access_token);
      setTenants(await callWith(data.access_token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    }
  }

  async function callWith(tk: string): Promise<Tenant[]> {
    const res = await fetch(`${API}/tenants`, { headers: { Authorization: `Bearer ${tk}` } });
    return res.json();
  }

  async function createTenant(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await call("/tenants", "POST", {
        slug, name: tname, admin_email: adminEmail, admin_password: adminPass,
        color_primary: c1, color_secondary: c2, is_demo: demo,
      });
      setTenants(await callWith(token));
      setSlug(""); setTname(""); setAdminEmail(""); setAdminPass("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    }
  }

  async function loadMetrics(id: string) {
    setMetrics(await call<Metrics>(`/tenants/${id}/metrics`));
  }

  async function lifecycle(id: string, action: "suspend" | "reactivate") {
    await call(`/tenants/${id}/lifecycle`, "POST", { action });
    setTenants(await callWith(token));
  }

  if (!token)
    return (
      <div className="mx-auto mt-10 max-w-sm">
        <h1 className="mb-4 text-center text-xl font-bold">Panel de Plataforma · Autoken</h1>
        <form onSubmit={login} className="card space-y-3">
          <input className="input" type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <input className="input" type="password" placeholder="Contraseña" value={password} onChange={(e) => setPassword(e.target.value)} />
          <input className="input" placeholder="Código 2FA (6 dígitos)" value={otp} onChange={(e) => setOtp(e.target.value)} />
          {totpUri && (
            <div className="rounded-lg bg-amber-500/15 p-3 text-xs text-amber-200">
              <p className="mb-1 font-semibold">Configura tu 2FA (una sola vez):</p>
              <p>Añade esta URI en Google Authenticator / Authy y vuelve a entrar con el código:</p>
              <code className="mt-1 block break-all">{totpUri}</code>
            </div>
          )}
          {error && <p className="text-sm text-red-300">{error}</p>}
          <button className="btn-primary w-full">Entrar</button>
        </form>
      </div>
    );

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold">Asesorías (tenants)</h1>
      <form onSubmit={createTenant} className="card grid grid-cols-2 gap-2 md:grid-cols-4">
        <input className="input" placeholder="slug (setex)" value={slug} onChange={(e) => setSlug(e.target.value)} />
        <input className="input" placeholder="Nombre" value={tname} onChange={(e) => setTname(e.target.value)} />
        <input className="input" placeholder="Email admin" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} />
        <input className="input" type="password" placeholder="Contraseña admin (12+)" value={adminPass} onChange={(e) => setAdminPass(e.target.value)} />
        <label className="flex items-center gap-2 text-sm"><span className="text-white/50">Primario</span>
          <input type="color" value={c1} onChange={(e) => setC1(e.target.value)} /></label>
        <label className="flex items-center gap-2 text-sm"><span className="text-white/50">Fondo</span>
          <input type="color" value={c2} onChange={(e) => setC2(e.target.value)} /></label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} /> Demo
        </label>
        <button className="btn-primary">Crear asesoría</button>
      </form>
      {error && <p className="text-red-300">{error}</p>}

      <div className="space-y-2">
        {tenants.map((t) => (
          <div key={t.id} className="card flex flex-wrap items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="font-medium">{t.name} {t.is_demo && <span className="text-xs text-amber-300">(demo)</span>}</p>
              <p className="text-xs text-white/50">
                {t.slug}.autoken.es · {t.status}
              </p>
            </div>
            <button className="btn-ghost px-3 py-2 text-sm" onClick={() => loadMetrics(t.id)}>Métricas</button>
            {t.status === "active" ? (
              <button className="btn-ghost px-3 py-2 text-sm text-red-300" onClick={() => lifecycle(t.id, "suspend")}>Suspender</button>
            ) : (
              <button className="btn-primary px-3 py-2 text-sm" onClick={() => lifecycle(t.id, "reactivate")}>Reactivar</button>
            )}
          </div>
        ))}
      </div>

      {metrics && (
        <div className="card">
          <h2 className="mb-2 font-semibold">Métricas · {metrics.slug}</h2>
          <p className="text-sm text-white/70">
            Empresas: {metrics.companies} · Usuarios: {metrics.users} · Facturas: {metrics.invoices} ·
            Coste OCR: {metrics.ocr_cost_eur} €
          </p>
        </div>
      )}
    </div>
  );
}
