import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../api/client";

interface Item {
  id: string; status: string; type: string; total: string | null;
  counterparty: string | null; issue_date: string | null; created_at: string;
}

const STATUS_ES: Record<string, { label: string; cls: string }> = {
  processing: { label: "Procesando", cls: "bg-white/10 text-white/70" },
  pending_review: { label: "Por revisar", cls: "bg-amber-500/20 text-amber-300" },
  confirmed: { label: "Confirmada", cls: "bg-emerald-500/20 text-emerald-300" },
  rejected: { label: "Rechazada", cls: "bg-red-500/20 text-red-300" },
};

export default function History() {
  const [items, setItems] = useState<Item[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    apiGet<Item[]>("/invoices?days=7")
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));
  }, []);

  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">Tus facturas (últimos 7 días)</h1>
      {error && <p className="text-red-300">{error}</p>}
      {items.length === 0 && !error && (
        <p className="text-white/50">Todavía no hay facturas. <Link to="/" className="text-brand">Sube la primera</Link>.</p>
      )}
      {items.map((i) => {
        const st = STATUS_ES[i.status] ?? { label: i.status, cls: "bg-white/10" };
        return (
          <Link key={i.id} to={`/factura/${i.id}`} className="card flex items-center gap-3 hover:border-brand/50">
            <span className="text-2xl">{i.type === "received" ? "📥" : "📤"}</span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{i.counterparty ?? "Sin identificar"}</p>
              <p className="text-sm text-white/50">{i.issue_date ?? "—"}</p>
            </div>
            <div className="text-right">
              <p className="font-semibold">{i.total ? `${i.total} €` : "—"}</p>
              <span className={`rounded-full px-2 py-0.5 text-xs ${st.cls}`}>{st.label}</span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
