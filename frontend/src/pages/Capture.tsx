import { useRef, useState, type ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import { apiUpload } from "../api/client";

/** Varianza del Laplaciano sobre canvas: detector de foto borrosa en cliente.
 * Umbral empírico; si es borrosa se avisa ANTES de gastar OCR (plan §3.6-2). */
async function blurScore(file: File): Promise<number | null> {
  if (!file.type.startsWith("image/")) return null;
  const bmp = await createImageBitmap(file, { resizeWidth: 640 });
  const canvas = document.createElement("canvas");
  canvas.width = bmp.width;
  canvas.height = bmp.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(bmp, 0, 0);
  const { data, width, height } = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const gray = new Float32Array(width * height);
  for (let i = 0; i < width * height; i++) {
    gray[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
  }
  let sum = 0, sumSq = 0, n = 0;
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x;
      const lap = -4 * gray[i] + gray[i - 1] + gray[i + 1] + gray[i - width] + gray[i + width];
      sum += lap; sumSq += lap * lap; n++;
    }
  }
  const mean = sum / n;
  return sumSq / n - mean * mean;
}

export default function Capture() {
  const nav = useNavigate();
  const [type, setType] = useState<"received" | "issued" | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [blurWarn, setBlurWarn] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const cameraRef = useRef<HTMLInputElement>(null);
  const galleryRef = useRef<HTMLInputElement>(null);

  async function onPick(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setError("");
    setBlurWarn(false);
    setFile(f);
    setPreview(f.type.startsWith("image/") ? URL.createObjectURL(f) : null);
    const score = await blurScore(f);
    if (score !== null && score < 60) setBlurWarn(true);
  }

  async function onUpload() {
    if (!file || !type) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await apiUpload<{ invoice_id: string }>(`/invoices/upload?type=${type}`, form);
      nav(`/factura/${res.invoice_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al subir");
    } finally {
      setBusy(false);
    }
  }

  // Paso 1 · Selector previo OBLIGATORIO (regla de negocio 1)
  if (!type)
    return (
      <div className="mx-auto mt-10 max-w-sm space-y-4">
        <h1 className="text-center text-xl font-semibold">¿Qué factura vas a subir?</h1>
        <button className="btn-primary w-full py-6 text-lg" onClick={() => setType("received")}>
          📥 Factura RECIBIDA
          <span className="block text-sm font-normal opacity-70">de un proveedor (gasto)</span>
        </button>
        <button className="btn-ghost w-full py-6 text-lg" onClick={() => setType("issued")}>
          📤 Factura EMITIDA
          <span className="block text-sm font-normal opacity-60">a un cliente (ingreso)</span>
        </button>
      </div>
    );

  return (
    <div className="mx-auto mt-6 max-w-sm space-y-4">
      <button className="text-sm text-white/50" onClick={() => { setType(null); setFile(null); setPreview(null); }}>
        ← Cambiar tipo
      </button>
      <h1 className="text-xl font-semibold">
        Factura {type === "received" ? "recibida 📥" : "emitida 📤"}
      </h1>

      <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={onPick} />
      <input ref={galleryRef} type="file" accept="image/*,application/pdf" className="hidden" onChange={onPick} />

      {!file ? (
        <div className="space-y-3">
          <button className="btn-primary w-full py-6 text-lg" onClick={() => cameraRef.current?.click()}>
            📷 Hacer foto
          </button>
          <button className="btn-ghost w-full" onClick={() => galleryRef.current?.click()}>
            Subir PDF o imagen
          </button>
        </div>
      ) : (
        <div className="card space-y-3">
          {preview ? (
            <img src={preview} alt="previsualización" className="max-h-96 w-full rounded-xl object-contain" />
          ) : (
            <p className="text-white/70">📄 {file.name}</p>
          )}
          {blurWarn && (
            <p className="rounded-lg bg-amber-500/15 p-3 text-sm text-amber-300">
              ⚠️ La foto parece borrosa. Repite la captura con buena luz para evitar errores de lectura.
            </p>
          )}
          {error && <p className="rounded-lg bg-red-500/15 p-3 text-sm text-red-300">{error}</p>}
          <div className="flex gap-2">
            <button className="btn-ghost flex-1" onClick={() => { setFile(null); setPreview(null); setBlurWarn(false); }}>
              Repetir
            </button>
            <button className="btn-primary flex-1" onClick={onUpload} disabled={busy}>
              {busy ? "Subiendo…" : "Usar esta"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
