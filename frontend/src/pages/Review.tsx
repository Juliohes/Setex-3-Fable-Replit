import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { apiGet, apiJson } from "../api/client";

interface TaxLine { iva_pct: string | null; base: string | null; cuota: string | null }
interface ReviewData {
  id: string; status: string; type: string;
  total: string | null; counterparty_cif: string | null; issue_date: string | null;
  counterparty_cif_status: string; counterparty_name_match: string;
  counterparty_official_name: string | null; counterparty_source: string | null;
  counterparty_name: string | null;
  own_name: string; own_cif: string; own_cif_as_read_ok: boolean | null;
  invoice_number: string | null; tax_lines: TaxLine[];
  irpf_pct: string | null; irpf_cuota: string | null;
  field_flags: Record<string, string>;
  confirm_blocked: boolean; confirm_blocked_reason: string | null;
}

/** Colores de campo según flag del árbitro: verde/ámbar/rojo (plan §3.6-6). */
function flagClass(flag?: string): string {
  if (flag === "review") return "border-amber-400/60";
  if (flag === "missing") return "border-red-400/70";
  return "border-white/15";
}

export default function Review() {
  const { id } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState<ReviewData | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  // Campos editables
  const [total, setTotal] = useState("");
  const [cif, setCif] = useState("");
  const [date, setDate] = useState("");
  const [name, setName] = useState("");
  const [num, setNum] = useState("");
  const [lines, setLines] = useState<{ iva_pct: string; base: string; cuota: string }[]>([]);
  const [irpfPct, setIrpfPct] = useState("");
  const [irpfCuota, setIrpfCuota] = useState("");

  async function load() {
    try {
      const d = await apiGet<ReviewData>(`/invoices/${id}`);
      setData(d);
      if (d.status === "processing") { setTimeout(load, 2500); return; }
      setTotal(d.total ?? "");
      setCif(d.counterparty_cif ?? "");
      setDate(d.issue_date ?? "");
      setName(d.counterparty_name ?? "");
      setNum(d.invoice_number ?? "");
      setIrpfPct(d.irpf_pct ?? "");
      setIrpfCuota(d.irpf_cuota ?? "");
      setLines(
        d.tax_lines.length
          ? d.tax_lines.map((l) => ({ iva_pct: l.iva_pct ?? "", base: l.base ?? "", cuota: l.cuota ?? "" }))
          : [{ iva_pct: "21", base: "", cuota: "" }]
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    }
  }
  useEffect(() => { load(); }, [id]);

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await apiJson(`/invoices/${id}/confirm`, "POST", {
        responsibility_accepted: accepted,
        invoice_number: num || null,
        issue_date: date || null,
        counterparty_name: name || null,
        counterparty_cif: cif || null,
        total: total || null,
        tax_lines: lines
          .filter((l) => l.base && l.iva_pct && l.cuota)
          .map((l) => ({ iva_pct: l.iva_pct, base: l.base, cuota: l.cuota })),
        irpf_pct: irpfPct || null,
        irpf_cuota: irpfCuota || null,
      });
      nav("/historial");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al confirmar");
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <p className="mt-10 text-center text-white/50">{error || "Cargando…"}</p>;

  if (data.status === "processing")
    return (
      <div className="mt-16 text-center">
        <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-2 border-brand border-t-transparent" />
        <p className="text-white/70">Leyendo la factura… esto tarda unos segundos.</p>
      </div>
    );

  const cifStatus = data.counterparty_cif_status;
  const alreadyConfirmed = data.status === "confirmed";
  const cannotConfirm = data.confirm_blocked || cifStatus === "invalid" || cifStatus === "not_found";

  return (
    <div className="mx-auto max-w-md space-y-4">
      <h1 className="text-xl font-semibold">Revisa y confirma</h1>

      {/* Identidad propia INYECTADA — nunca editable ni leída del papel (§11.8.1) */}
      <div className="card text-sm text-white/60">
        Tu empresa: <span className="text-white">{data.own_name}</span> · CIF{" "}
        <span className="text-white">{data.own_cif}</span>
        {data.own_cif_as_read_ok === false && (
          <p className="mt-2 rounded-lg bg-red-500/15 p-2 text-red-300">
            ⚠️ El CIF que aparece en la foto no coincide con tu empresa. ¿Seguro que es tu factura?
          </p>
        )}
      </div>

      {/* Veredicto del CIF de la contraparte (§11.8) */}
      {cifStatus === "invalid" && (
        <div className="rounded-xl border-2 border-red-500 bg-red-500/15 p-4 font-semibold text-red-200">
          ✕ CIF INVÁLIDO: el número no es un identificador fiscal correcto. Corrígelo mirando la factura.
        </div>
      )}
      {cifStatus === "not_found" && (
        <div className="rounded-xl border-2 border-red-500 bg-red-500/15 p-4 font-semibold text-red-200">
          ✕ Este CIF no consta en el censo. No se puede guardar una factura de un emisor inexistente.
        </div>
      )}
      {cifStatus === "valid" && data.counterparty_name_match === "mismatch" && (
        <div className="rounded-xl bg-amber-500/15 p-3 text-sm text-amber-200">
          ⚠️ El CIF existe pero pertenece a «{data.counterparty_official_name}», no a «{data.counterparty_name}».
          Comprueba que el CIF es el del emisor real.
        </div>
      )}
      {cifStatus === "unverified" && (
        <div className="rounded-xl bg-white/5 p-3 text-sm text-white/60">
          ℹ️ No se pudo verificar el CIF en fuentes externas: revísalo tú con especial atención.
        </div>
      )}

      {/* LOS 3 CAMPOS SIEMPRE VISIBLES (regla 12) */}
      <div className="card space-y-3">
        <div>
          <label className="label">Importe total (€)</label>
          <input className={`input ${flagClass(data.field_flags.total)}`} inputMode="decimal"
            value={total} onChange={(e) => setTotal(e.target.value)} />
        </div>
        <div>
          <label className="label">
            CIF de {data.type === "received" ? "el proveedor" : "tu cliente"}
          </label>
          <input className={`input ${flagClass(data.field_flags.counterparty_cif)}`}
            value={cif} onChange={(e) => setCif(e.target.value.toUpperCase())} />
        </div>
        <div>
          <label className="label">Fecha de la factura</label>
          <input className={`input ${flagClass(data.field_flags.issue_date)}`} type="date"
            value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
      </div>

      {/* Resto plegado (regla 12) */}
      <button className="w-full text-sm text-white/50 hover:text-white" onClick={() => setShowDetails(!showDetails)}>
        {showDetails ? "▲ Ocultar detalles" : "▼ Ver todos los campos"}
      </button>
      {showDetails && (
        <div className="card space-y-3">
          <div>
            <label className="label">Nombre de la contraparte</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="label">Nº de factura</label>
            <input className="input" value={num} onChange={(e) => setNum(e.target.value)} />
          </div>
          <div>
            <label className="label">Tramos de IVA</label>
            {lines.map((l, i) => (
              <div key={i} className="mb-2 grid grid-cols-3 gap-2">
                <input className="input" placeholder="% IVA" inputMode="decimal" value={l.iva_pct}
                  onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, iva_pct: e.target.value } : x)))} />
                <input className="input" placeholder="Base" inputMode="decimal" value={l.base}
                  onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, base: e.target.value } : x)))} />
                <input className="input" placeholder="Cuota" inputMode="decimal" value={l.cuota}
                  onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, cuota: e.target.value } : x)))} />
              </div>
            ))}
            <button className="text-sm text-brand" onClick={() => setLines([...lines, { iva_pct: "", base: "", cuota: "" }])}>
              + Añadir tramo
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="label">IRPF %</label>
              <input className="input" inputMode="decimal" value={irpfPct} onChange={(e) => setIrpfPct(e.target.value)} />
            </div>
            <div>
              <label className="label">IRPF cuota (€)</label>
              <input className="input" inputMode="decimal" value={irpfCuota} onChange={(e) => setIrpfCuota(e.target.value)} />
            </div>
          </div>
        </div>
      )}

      {/* AVISO ROJO GRANDE de responsabilidad (regla 7-8, innegociable) */}
      {!alreadyConfirmed && (
        <>
          <div className="rounded-xl border-2 border-red-500/70 bg-red-500/10 p-4">
            <p className="font-bold text-red-300">⚠️ ATENCIÓN: comprueba los datos con la factura en la mano.</p>
            <p className="mt-1 text-sm text-red-200/80">
              Estos datos van directos a tu contabilidad fiscal. Un dato mal confirmado es
              responsabilidad de quien confirma.
            </p>
            <label className="mt-3 flex items-start gap-2 text-sm text-white/90">
              <input type="checkbox" className="mt-1 h-4 w-4 accent-[rgb(var(--color-primary))]"
                checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />
              He comprobado que los datos coinciden con la factura y asumo la responsabilidad de esta confirmación.
            </label>
          </div>

          {error && <p className="rounded-lg bg-red-500/15 p-3 text-sm text-red-300">{error}</p>}

          <button className="btn-primary w-full py-4 text-lg" onClick={confirm}
            disabled={busy || !accepted || cannotConfirm}>
            {cannotConfirm ? "Confirmación bloqueada" : busy ? "Guardando…" : "Confirmar y guardar"}
          </button>
          {data.confirm_blocked_reason && (
            <p className="text-center text-sm text-red-300">{data.confirm_blocked_reason}</p>
          )}
        </>
      )}
      {alreadyConfirmed && (
        <p className="rounded-xl bg-emerald-500/15 p-4 text-center text-emerald-300">
          ✓ Factura confirmada y enviada a tu asesoría.
        </p>
      )}
    </div>
  );
}
