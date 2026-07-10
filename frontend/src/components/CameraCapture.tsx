import { useCallback, useEffect, useRef, useState } from "react";

/** Cámara en vivo dentro de la app (getUserMedia), fiable en móvil frente al
 * truco `<input capture>` que muchos navegadores ignoran y mandan a la galería.
 * Si no hay permiso/soporte, avisa y ofrece el respaldo (input de archivo). */
export default function CameraCapture({
  onCapture,
  onClose,
  onFallback,
}: {
  onCapture: (file: File) => void;
  onClose: () => void;
  onFallback: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [facing, setFacing] = useState<"environment" | "user">("environment");
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function start() {
      setReady(false);
      setError(null);
      stop();
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("Este navegador no permite abrir la cámara.");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: facing } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {});
        }
        setReady(true);
      } catch {
        setError("No se pudo acceder a la cámara. Revisa el permiso del navegador.");
      }
    }
    start();
    return () => {
      cancelled = true;
      stop();
    };
  }, [facing, stop]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function close() {
    stop();
    onClose();
  }

  function shoot() {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        stop();
        onCapture(new File([blob], `factura-${Date.now()}.jpg`, { type: "image/jpeg" }));
      },
      "image/jpeg",
      0.92,
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black">
      <div className="flex items-center justify-between p-3 text-white">
        <button className="text-sm text-white/70" onClick={close}>
          ✕ Cerrar
        </button>
        <span className="text-sm text-white/70">Encuadra la factura</span>
        <button
          className="text-sm text-white/70"
          onClick={() => setFacing((f) => (f === "environment" ? "user" : "environment"))}
        >
          ↺ Girar
        </button>
      </div>

      <div className="relative flex-1 overflow-hidden">
        <video
          ref={videoRef}
          playsInline
          muted
          autoPlay
          className="absolute inset-0 h-full w-full object-contain"
        />
        {!ready && !error && (
          <p className="absolute inset-0 grid place-items-center text-white/60">Abriendo cámara…</p>
        )}
        {error && (
          <div className="absolute inset-0 grid place-items-center p-6 text-center">
            <div className="card max-w-xs">
              <p className="text-white/80">{error}</p>
              <button
                className="btn-primary mt-4 w-full"
                onClick={() => {
                  stop();
                  onFallback();
                }}
              >
                Subir una foto desde el móvil
              </button>
            </div>
          </div>
        )}
      </div>

      {!error && (
        <div className="flex justify-center p-6">
          <button
            aria-label="Capturar"
            disabled={!ready}
            onClick={shoot}
            className="rounded-full border-4 border-white bg-white/20 p-2 disabled:opacity-40"
            style={{ height: "4.5rem", width: "4.5rem" }}
          >
            <span className="block h-full w-full rounded-full bg-white" />
          </button>
        </div>
      )}
    </div>
  );
}
