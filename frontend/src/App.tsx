import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import AdminCompanies from "./pages/AdminCompanies";
import AdminInvoices from "./pages/AdminInvoices";
import Capture from "./pages/Capture";
import History from "./pages/History";
import Login from "./pages/Login";
import PlatformPanel from "./pages/PlatformPanel";
import Review from "./pages/Review";

function Protected({ children }: { children: JSX.Element }) {
  const { session } = useAuth();
  return session ? children : <Navigate to="/login" replace />;
}

function Nav() {
  const { session, branding, logout } = useAuth();
  const loc = useLocation();
  if (!session || loc.pathname === "/login") return null;
  const isAdmin = session.role === "tenant_admin";
  const tab = (to: string, label: string) => (
    <Link
      to={to}
      className={`rounded-lg px-3 py-2 text-sm font-medium ${
        loc.pathname === to ? "bg-brand text-black" : "text-white/70 hover:text-white"
      }`}
    >
      {label}
    </Link>
  );
  return (
    <header className="sticky top-0 z-10 border-b border-white/10 bg-surface/95 backdrop-blur">
      <div className="mx-auto flex max-w-4xl items-center gap-2 px-4 py-3">
        {branding?.logo_url ? (
          <img src={branding.logo_url} alt="" className="h-7 w-7 rounded" />
        ) : (
          <div className="h-7 w-7 rounded-lg bg-brand" />
        )}
        <span className="mr-3 font-semibold">{branding?.app_name ?? "Autoken"}</span>
        {tab("/", "Capturar")}
        {tab("/historial", "Historial")}
        {isAdmin && tab("/admin/facturas", "Panel")}
        {isAdmin && tab("/admin/empresas", "Empresas")}
        <button onClick={logout} className="ml-auto text-sm text-white/50 hover:text-white">
          Salir
        </button>
      </div>
    </header>
  );
}

export default function App() {
  const { brandingError } = useAuth();
  const isPlatform = window.location.pathname.startsWith("/plataforma");
  if (brandingError && !isPlatform)
    return (
      <main className="grid h-full place-items-center p-6 text-center">
        <div className="card max-w-md">
          <h1 className="mb-2 text-xl font-semibold">Asesoría no encontrada</h1>
          <p className="text-white/60">
            Accede desde la dirección de tu asesoría (p. ej. <code>setex.autoken.es</code>) o añade{" "}
            <code>?tenant=slug</code> a la URL.
          </p>
        </div>
      </main>
    );
  return (
    <div className="min-h-full">
      <Nav />
      <main className="mx-auto max-w-4xl p-4 pb-16">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Protected><Capture /></Protected>} />
          <Route path="/historial" element={<Protected><History /></Protected>} />
          <Route path="/factura/:id" element={<Protected><Review /></Protected>} />
          <Route path="/admin/facturas" element={<Protected><AdminInvoices /></Protected>} />
          <Route path="/admin/empresas" element={<Protected><AdminCompanies /></Protected>} />
          <Route path="/plataforma" element={<PlatformPanel />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
