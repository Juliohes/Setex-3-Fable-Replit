# Autoken Facturas v2 — SaaS multi-asesoría (modo Replit)

Plataforma de digitalización de facturas con OCR/IA para asesorías fiscales.
Cada asesoría (tenant) tiene su marca, sus empresas cliente y sus usuarios;
los autónomos fotografían facturas, la IA extrae los datos, un sistema
determinista los verifica (CIF con dígito de control, cuadre de IVA por tramo,
censo AEAT/VIES) y el humano confirma con responsabilidad explícita.

## Arquitectura (ADR-0012)
- **1 proceso** (Replit Reserved VM): FastAPI + worker OCR asyncio + frontend estático.
- **PostgreSQL (Neon)** con **RLS FORCE fail-closed** de dos niveles (tenant y empresa),
  contexto por transacción con `set_config(..., true)` — seguro con pooling.
- **Cola de jobs sobre Postgres** (`FOR UPDATE SKIP LOCKED`) con idempotencia
  por hash de fichero: sin Redis.
- **Motores OCR conectables** (Strategy): `pdf_native` (gratis), Mistral, Azure
  Document Intelligence. Árbitro por campo puro + regla anti-alucinación (null).
- **Cadena de verificación del CIF de contraparte**: estructura → supplier master
  → caché global → VIES/AEAT (con timeout: un tercero caído nunca bloquea).
- **Audit log** append-only con cadena de hashes por tenant.
- **Frontend** React + Vite + Tailwind, theming por tenant vía CSS variables.

## Desarrollo local
```bash
# Backend (requiere PostgreSQL local)
pip install -e "./backend[dev]"
export DATABASE_URL=postgresql+asyncpg://autoken:autoken@localhost:5432/autoken
export JWT_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(32))")
python scripts/seed.py
uvicorn --app-dir backend/src main:app --reload

# Frontend
cd frontend && npm install && npm run dev   # http://localhost:5173/?tenant=setex

# Tests (39, incluido el gate RLS concurrente)
cd backend && TEST_DATABASE_URL=$DATABASE_URL python -m pytest
```

## Despliegue
Ver `docs/runbooks/replit-deploy.md`.

## Estructura
```
backend/src/
  shared/       config fail-loud · db (SET LOCAL) · bootstrap RLS · eventos · middlewares
  tenancy/      tenants + branding + resolución por host/cabecera
  identity/     usuarios · membresías · refresh rotativo · registro con aprobación
  companies/    CRUD + import Excel
  invoice_intake/  subida segura · revisión · confirmación bloqueante · storage
  ocr/          verificación determinista · árbitro · motores · cadena CIF
  jobs/         cola Postgres + worker OCR
  reporting/    panel + export Excel
  platform_admin/  panel Julio/Alberto (2FA TOTP) · alta tenants · métricas
  security/     auth · rbac · rate limit · audit hash-chain
frontend/src/   Login · Capture (cámara+nitidez) · Review (3 campos+bloqueos) ·
                History · AdminInvoices · AdminCompanies · PlatformPanel
docs/adr/0012   decisiones del modo Replit
```
