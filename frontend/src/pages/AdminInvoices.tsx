import { useEffect, useState } from "react";
import { apiBlob, apiGet } from "../api/client";
import DesgloseModal from "../components/DesgloseModal";

interface Row {
  id: string; company: string; type: string; status: string;
  invoice_number: string | null; issue_date: string | null;
  counterparty: string | null; counterparty_cif: string | null;
  total: string | null; created_at: string; tax_line_count: number;
}

export default function AdminInvoices() {
  const [rows, setRows] = useState<Row[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [status, setStatus] = useState("");
  const [cif, setCif] = useState("");
  const [error, setError] = useState("");
  const [desgloseId, setDesgloseId] = useState<string | null>(null);

  function query(): string {
    const q = new URLSearchParams();
    if (from) q.set("date_from", from);
    if (to) q.set("date_to", to);
    if (status) q.set("status", status);
    if (cif) q.set("cif", cif);
    return q.toString();
  }

  async function load() {
    try {
      setRows(await apiGet<Row[]>(`/reporting/invoices?${query()}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }
  useEffect(() => { load(); }, []);

  async function exportExcel() {
    const blob = await apiBlob(`/reporting/invoices.xlsx?${query()}`);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "facturas.xlsx";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Panel de facturas</h1>
      <div className="card grid grid-cols-2 gap-2 md:grid-cols-5">
        <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Todos los estados</option>
          <option value="pending_review">Por revisar</option>
          <option value="confirmed">Confirmadas</option>
          <option value="processing">Procesando</option>
        </select>
        <input className="input" placeholder="CIF" value={cif} onChange={(e) => setCif(e.target.value.toUpperCase())} />
        <div className="flex gap-2">
          <button className="btn-ghost flex-1" onClick={load}>Filtrar</button>
          <button className="btn-primary flex-1" onClick={exportExcel}>Excel</button>
        </div>
      </div>
      {error && <p className="text-red-300">{error}</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-white/50">
            <tr>
              <th className="p-2">Empresa</th><th className="p-2">Tipo</th><th className="p-2">Nº</th>
              <th className="p-2">Fecha</th><th className="p-2">Contraparte</th><th className="p-2">CIF</th>
              <th className="p-2 text-right">Total</th><th className="p-2">Estado</th>
              <th className="p-2">Desglose IVA</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-white/5">
                <td className="p-2">{r.company}</td>
                <td className="p-2">{r.type === "received" ? "📥" : "📤"}</td>
                <td className="p-2">{r.invoice_number ?? "—"}</td>
                <td className="p-2">{r.issue_date ?? "—"}</td>
                <td className="max-w-40 truncate p-2">{r.counterparty ?? "—"}</td>
                <td className="p-2 font-mono text-xs">{r.counterparty_cif ?? "—"}</td>
                <td className="p-2 text-right font-medium">{r.total ? `${r.total} €` : "—"}</td>
                <td className="p-2">{r.status}</td>
                <td className="p-2">
                  {r.tax_line_count === 0 ? (
                    <button className="text-white/60 hover:text-white" onClick={() => setDesgloseId(r.id)}>
                      —
                    </button>
                  ) : (
                    <button className="text-brand hover:opacity-80" onClick={() => setDesgloseId(r.id)}>
                      {r.tax_line_count === 1 ? "1 tramo" : `${r.tax_line_count} tramos`}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="p-4 text-center text-white/40">Sin resultados</p>}
      </div>
      {desgloseId && (
        <DesgloseModal
          invoiceId={desgloseId}
          onClose={() => setDesgloseId(null)}
          onSaved={load}
        />
      )}
    </div>
  );
}
