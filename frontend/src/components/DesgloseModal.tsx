import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, apiGet, apiJson } from "../api/client";

/** Un tramo tal como se edita en el modal (todo string para el input). */
interface Line {
  iva_pct: string;
  base: string;
  cuota: string;
}

/** Subconjunto de ReviewOut que necesita el modal. */
interface ReviewOut {
  id: string;
  invoice_number: string | null;
  issue_date: string | null;
  total: string | null;
  own_name: string;
  own_cif: string;
  irpf_cuota: string | null;
  tax_lines: { iva_pct: string | null; base: string | null; cuota: string | null }[];
}

const IVA_OPTIONS = ["21", "10", "4", "0"];
const TOL = 0.02;

/** Parsea un importe (acepta coma o punto). Devuelve NaN si no es válido. */
function num(s: string | null | undefined): number {
  if (s == null) return NaN;
  const t = String(s).trim().replace(",", ".");
  if (t === "") return NaN;
  return parseFloat(t);
}

/** Formatea a moneda española con coma decimal (2 decimales). */
function fmt(n: number): string {
  return n.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Convierte ISO YYYY-MM-DD a dd/mm/aaaa; si no puede, devuelve el original. */
function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
}

/** Normaliza a string con PUNTO decimal para enviar al backend. */
function toDot(s: string): string {
  return s.trim().replace(",", ".");
}

export default function DesgloseModal({
  invoiceId,
  onClose,
  onSaved,
}: {
  invoiceId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [meta, setMeta] = useState<ReviewOut | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const d = await apiGet<ReviewOut>(`/invoices/${invoiceId}`);
      setMeta(d);
      setLines(
        d.tax_lines.length
          ? d.tax_lines.map((l) => ({
              iva_pct: l.iva_pct ?? "21",
              base: l.base ?? "",
              cuota: l.cuota ?? "",
            }))
          : [{ iva_pct: "21", base: "", cuota: "" }]
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar la factura.");
    } finally {
      setLoading(false);
    }
  }, [invoiceId]);

  useEffect(() => {
    load();
  }, [load]);

  // Esc cierra el modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function updateLine(i: number, patch: Partial<Line>) {
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  }
  function addLine() {
    setLines((ls) => [...ls, { iva_pct: "21", base: "", cuota: "" }]);
  }
  function removeLine(i: number) {
    setLines((ls) => ls.filter((_, j) => j !== i));
  }

  // ── Cálculo del cuadre ──────────────────────────────────────────────
  const calc = useMemo(() => {
    const sumBase = lines.reduce((a, l) => a + (isNaN(num(l.base)) ? 0 : num(l.base)), 0);
    const sumCuota = lines.reduce((a, l) => a + (isNaN(num(l.cuota)) ? 0 : num(l.cuota)), 0);
    const irpf = meta && !isNaN(num(meta.irpf_cuota)) ? num(meta.irpf_cuota) : 0;
    const computedTotal = sumBase + sumCuota - irpf;
    const invoiceTotal = meta ? num(meta.total) : NaN;
    const hasInvoiceTotal = !isNaN(invoiceTotal);
    const diff = hasInvoiceTotal ? computedTotal - invoiceTotal : NaN;
    const totalOk = hasInvoiceTotal && Math.abs(diff) <= TOL;

    // Coherencia por tramo: cuota ≈ base·%/100 (±0,02).
    const lineOk = lines.map((l) => {
      const b = num(l.base);
      const p = num(l.iva_pct);
      const c = num(l.cuota);
      if (isNaN(b) || isNaN(p) || isNaN(c)) return false;
      return Math.abs(c - (b * p) / 100) <= TOL;
    });
    const allLinesOk = lineOk.every(Boolean);
    const anyEmpty = lines.some(
      (l) => isNaN(num(l.base)) || isNaN(num(l.cuota)) || !IVA_OPTIONS.includes(l.iva_pct)
    );

    return {
      sumBase,
      sumCuota,
      irpf,
      computedTotal,
      invoiceTotal,
      hasInvoiceTotal,
      diff,
      totalOk,
      lineOk,
      allLinesOk,
      anyEmpty,
    };
  }, [lines, meta]);

  const canSave =
    !saving &&
    lines.length > 0 &&
    !calc.anyEmpty &&
    calc.allLinesOk &&
    calc.hasInvoiceTotal &&
    calc.totalOk;

  async function save() {
    setSaving(true);
    setError("");
    try {
      await apiJson<ReviewOut>(`/invoices/${invoiceId}/tax-lines`, "PATCH", {
        tax_lines: lines.map((l) => ({
          iva_pct: l.iva_pct,
          base: toDot(l.base),
          cuota: toDot(l.cuota),
        })),
      });
      onSaved();
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "No se pudo guardar el desglose."
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-lg flex-col rounded-2xl border border-white/10 bg-surface shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {/* Cabecera */}
        <div className="flex items-start justify-between border-b border-white/10 p-4">
          <h2 className="text-lg font-semibold">
            Desglose IVA — Factura #{meta?.invoice_number ?? "—"}
          </h2>
          <button
            className="rounded-lg px-2 text-xl text-white/60 hover:text-white"
            onClick={onClose}
            aria-label="Cerrar"
          >
            ×
          </button>
        </div>

        {/* Resumen de la factura */}
        {meta && (
          <div className="border-b border-white/10 px-4 py-3 text-sm text-white/60">
            <span className="text-white">{meta.own_name}</span> · {meta.own_cif} ·{" "}
            {fmtDate(meta.issue_date)} · Total:{" "}
            <span className="text-white">
              {meta.total ? `${fmt(num(meta.total))} €` : "—"}
            </span>
          </div>
        )}

        {/* Cuerpo scrollable */}
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {loading && <p className="text-center text-white/50">Cargando…</p>}

          {!loading &&
            lines.map((l, i) => {
              const bad = !calc.lineOk[i];
              return (
                <div
                  key={i}
                  className={`card space-y-3 ${bad ? "border-red-400/70" : ""}`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wide text-white/50">
                      Tramo {i + 1}
                    </span>
                    <button
                      className="text-xs text-red-300 hover:text-red-200"
                      onClick={() => removeLine(i)}
                    >
                      × Eliminar tramo
                    </button>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <label className="label">IVA %</label>
                      <select
                        className="input"
                        value={l.iva_pct}
                        onChange={(e) => updateLine(i, { iva_pct: e.target.value })}
                      >
                        {IVA_OPTIONS.map((o) => (
                          <option key={o} value={o}>
                            {o}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="label">Base tramo (€)</label>
                      <input
                        className="input"
                        inputMode="decimal"
                        value={l.base}
                        onChange={(e) => updateLine(i, { base: e.target.value })}
                      />
                    </div>
                    <div>
                      <label className="label">Cuota tramo (€)</label>
                      <input
                        className={`input ${bad ? "border-red-400/70" : ""}`}
                        inputMode="decimal"
                        value={l.cuota}
                        onChange={(e) => updateLine(i, { cuota: e.target.value })}
                      />
                    </div>
                  </div>
                  {bad && (
                    <p className="text-xs text-red-300">
                      La cuota no coincide con base × {l.iva_pct || "?"}%.
                    </p>
                  )}
                </div>
              );
            })}

          {!loading && (
            <button className="text-sm text-brand hover:opacity-80" onClick={addLine}>
              + Añadir tramo
            </button>
          )}
        </div>

        {/* Resumen / cuadre + acciones */}
        {!loading && meta && (
          <div className="space-y-3 border-t border-white/10 p-4">
            <div className="space-y-1 text-sm text-white/70">
              <div className="flex justify-between">
                <span>Suma de bases</span>
                <span className="font-medium text-white">{fmt(calc.sumBase)} €</span>
              </div>
              <div className="flex justify-between">
                <span>Suma de cuotas (IVA)</span>
                <span className="font-medium text-white">{fmt(calc.sumCuota)} €</span>
              </div>
              {calc.irpf > 0 && (
                <div className="flex justify-between">
                  <span>IRPF retenido</span>
                  <span className="font-medium text-white">− {fmt(calc.irpf)} €</span>
                </div>
              )}
              <div className="flex justify-between border-t border-white/10 pt-1">
                <span>Total calculado</span>
                <span className="font-semibold text-white">{fmt(calc.computedTotal)} €</span>
              </div>
            </div>

            {/* Indicador de cuadre */}
            {!calc.hasInvoiceTotal ? (
              <div className="rounded-xl bg-amber-500/15 p-3 text-sm text-amber-200">
                ⚠️ La factura no tiene total; no se puede comprobar el cuadre.
              </div>
            ) : calc.totalOk ? (
              <div className="rounded-xl bg-emerald-500/15 p-3 text-center text-sm font-semibold text-emerald-300">
                ✓ Cuadra
              </div>
            ) : (
              <div className="rounded-xl bg-red-500/15 p-3 text-center text-sm font-semibold text-red-300">
                ✗ Descuadre de {fmt(Math.abs(calc.diff))} €
              </div>
            )}

            {!calc.anyEmpty && !calc.allLinesOk && (
              <p className="text-center text-xs text-red-300">
                Hay tramos cuya cuota no coincide con base × %.
              </p>
            )}

            {error && (
              <p className="rounded-lg bg-red-500/15 p-3 text-sm text-red-300">{error}</p>
            )}

            <div className="flex justify-end gap-2">
              <button className="btn-ghost" onClick={onClose}>
                Cancelar
              </button>
              <button className="btn-primary" onClick={save} disabled={!canSave}>
                {saving ? "Guardando…" : "Guardar"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
