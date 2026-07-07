import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { apiGet, apiJson, apiUpload } from "../api/client";

interface Company { id: string; name: string; cif: string; status: string; notes: string; invoice_count: number }
interface PendingUser { id: string; email: string; full_name: string; company_id: string | null }
interface ImportReport { created: number; skipped_duplicates: number; errors: string[] }

export default function AdminCompanies() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [pending, setPending] = useState<PendingUser[]>([]);
  const [name, setName] = useState("");
  const [cif, setCif] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function load() {
    try {
      setCompanies(await apiGet<Company[]>("/companies"));
      setPending(await apiGet<PendingUser[]>("/users/pending"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }
  useEffect(() => { load(); }, []);

  async function createCompany() {
    setError(""); setMsg("");
    try {
      await apiJson("/companies", "POST", { name, cif });
      setName(""); setCif("");
      setMsg("Empresa creada");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function approveUser(id: string) {
    await apiJson(`/users/${id}/approve`, "POST", {});
    load();
  }

  async function approveCompany(id: string) {
    await apiJson(`/companies/${id}/approve`, "POST", {});
    load();
  }

  async function onImport(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setError(""); setMsg("");
    const form = new FormData();
    form.append("file", f);
    try {
      const rep = await apiUpload<ImportReport>("/companies/import-excel", form);
      setMsg(`Importadas ${rep.created} · duplicadas ${rep.skipped_duplicates} · errores ${rep.errors.length}`);
      if (rep.errors.length) setError(rep.errors.slice(0, 8).join(" · "));
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al importar");
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Empresas y accesos</h1>

      {pending.length > 0 && (
        <div className="card space-y-2">
          <h2 className="font-semibold text-amber-300">Solicitudes de acceso pendientes</h2>
          {pending.map((u) => (
            <div key={u.id} className="flex items-center justify-between gap-2 border-t border-white/5 pt-2">
              <div>
                <p>{u.full_name}</p>
                <p className="text-sm text-white/50">{u.email}</p>
              </div>
              <button className="btn-primary px-3 py-2 text-sm" onClick={() => approveUser(u.id)}>Aprobar</button>
            </div>
          ))}
        </div>
      )}

      <div className="card space-y-3">
        <h2 className="font-semibold">Nueva empresa</h2>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          <input className="input" placeholder="Nombre" value={name} onChange={(e) => setName(e.target.value)} />
          <input className="input" placeholder="CIF" value={cif} onChange={(e) => setCif(e.target.value.toUpperCase())} />
          <button className="btn-primary" onClick={createCompany}>Crear</button>
        </div>
        <input ref={fileRef} type="file" accept=".xlsx" className="hidden" onChange={onImport} />
        <button className="btn-ghost w-full" onClick={() => fileRef.current?.click()}>
          📄 Importar Excel de empresas (nombre · CIF · notas)
        </button>
        {msg && <p className="text-sm text-emerald-300">{msg}</p>}
        {error && <p className="text-sm text-red-300">{error}</p>}
      </div>

      <div className="space-y-2">
        {companies.map((c) => (
          <div key={c.id} className="card flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{c.name}</p>
              <p className="font-mono text-xs text-white/50">{c.cif} · {c.invoice_count} facturas</p>
            </div>
            {c.status === "pending" ? (
              <button className="btn-primary px-3 py-2 text-sm" onClick={() => approveCompany(c.id)}>Activar</button>
            ) : (
              <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-xs text-emerald-300">{c.status}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
