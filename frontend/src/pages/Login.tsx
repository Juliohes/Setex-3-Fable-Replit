import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { apiJson } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export default function Login() {
  const { login, branding } = useAuth();
  const nav = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [companyCif, setCompanyCif] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      if (mode === "login") {
        await login(email, password);
        nav("/");
      } else {
        const res = await apiJson<{ detail: string }>("/auth/register", "POST", {
          email,
          password,
          full_name: fullName,
          company_name: companyName,
          company_cif: companyCif,
        });
        setNotice(res.detail);
        setMode("login");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error inesperado");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-10 max-w-sm">
      <div className="mb-8 text-center">
        {branding?.logo_url ? (
          <img src={branding.logo_url} alt="" className="mx-auto mb-3 h-16 w-16 rounded-2xl" />
        ) : (
          <div className="mx-auto mb-3 h-16 w-16 rounded-2xl bg-brand" />
        )}
        <h1 className="text-2xl font-bold">{branding?.app_name ?? "Autoken Facturas"}</h1>
        <p className="mt-1 text-sm text-white/50">Digitaliza tus facturas en segundos</p>
      </div>

      <form onSubmit={onSubmit} className="card space-y-4">
        {mode === "register" && (
          <>
            <div>
              <label className="label">Nombre completo</label>
              <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} required minLength={2} />
            </div>
            <div>
              <label className="label">Nombre de tu empresa</label>
              <input className="input" value={companyName} onChange={(e) => setCompanyName(e.target.value)} required minLength={2} />
            </div>
            <div>
              <label className="label">CIF de tu empresa</label>
              <input className="input" value={companyCif} onChange={(e) => setCompanyCif(e.target.value)} required placeholder="B12345678" />
            </div>
          </>
        )}
        <div>
          <label className="label">Email</label>
          <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="username" />
        </div>
        <div>
          <label className="label">Contraseña</label>
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={mode === "register" ? 10 : 1} autoComplete={mode === "login" ? "current-password" : "new-password"} />
        </div>

        {error && <p className="rounded-lg bg-red-500/15 p-3 text-sm text-red-300">{error}</p>}
        {notice && <p className="rounded-lg bg-emerald-500/15 p-3 text-sm text-emerald-300">{notice}</p>}

        <button className="btn-primary w-full" disabled={busy}>
          {busy ? "Un momento…" : mode === "login" ? "Entrar" : "Solicitar acceso"}
        </button>
        <button
          type="button"
          className="w-full text-center text-sm text-white/50 hover:text-white"
          onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}
        >
          {mode === "login" ? "¿No tienes cuenta? Regístrate" : "¿Ya tienes cuenta? Entra"}
        </button>
      </form>
    </div>
  );
}
