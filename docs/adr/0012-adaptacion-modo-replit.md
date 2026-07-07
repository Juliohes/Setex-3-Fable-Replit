# ADR-0012 — Adaptación de la arquitectura a "modo Replit"

**Fecha:** 2026-07-03 · **Estado:** Aceptada · **Sustituye parcialmente a:** topología VPS Hostinger del Plan Maestro v1.2 (§4)

## Contexto
Decisión de negocio: abandonar el VPS de Hostinger y alojar Autoken Facturas v2 en Replit.
Replit no ejecuta Docker Compose ni servicios auxiliares propios (Redis, MinIO, ClamAV,
Caddy). Ofrece: Reserved VM / Autoscale deployments, PostgreSQL gestionado (Neon),
App Storage (objetos, respaldado en GCS), Secrets y dominios personalizados con TLS
automático.

## Decisiones

| Pieza del plan v1.2 | Modo Replit | Justificación |
|---|---|---|
| Docker Compose + Caddy | **Reserved VM, 1 proceso** (uvicorn) que sirve API + frontend estático + worker embebido (tarea asyncio) | Replit gestiona TLS/proxy; Reserved VM permite proceso persistente (el worker OCR lo exige; Autoscale lo mataría) |
| PostgreSQL 16 en contenedor | **PostgreSQL de Replit (Neon)** | RLS soportado. Neon usa pooling en modo transacción ⇒ el contexto de tenant DEBE ser `set_config(..., is_local=true)` por transacción. Es exactamente la corrección ARQ-1: la única opción segura aquí. |
| Redis + arq | **Cola sobre Postgres** (`jobs`, `FOR UPDATE SKIP LOCKED`) | Menos piezas y misma semántica at-least-once. Idempotencia real por `jobs.idempotency_key` UNIQUE + `UNIQUE(invoice_id, engine)` (ARQ-2). Con 51 empresas el volumen es trivial para Postgres. |
| MinIO (bucket por tenant, URLs firmadas) | **Storage protocol** → `LocalStorage` (dev) / `ReplitObjectStorage` (prod), prefijo por tenant. Descarga SIEMPRE vía endpoint autenticado que primero lee la factura bajo RLS | Sin URLs firmadas no hay URLs que filtrar; el control de acceso queda unificado en RLS. |
| ClamAV | **Controles compensatorios**: magic-bytes (MIME real), límite de tamaño, tipos cerrados (PDF/JPEG/PNG) | ClamAV no puede correr en Replit. Riesgo residual aceptado y documentado: los ficheros nunca se ejecutan, solo se leen con parsers. |
| Wildcard `*.autoken.es` en Caddy | **Dominios conectados a Replit por subdominio + fallback `X-Tenant-Slug`** | Replit verifica dominios individualmente (TXT/CNAME); el wildcard genérico no está garantizado. Cada asesoría nueva ⇒ conectar `slug.autoken.es` en el panel de Replit (2 min). En el dominio `*.replit.app` se usa `?tenant=slug` (el frontend lo persiste). |
| Rate limit en proxy | **Limitador en memoria** (1 proceso) | Suficiente en Reserved VM; si se escala a N réplicas, migrar a limitador sobre Postgres. |
| Alembic desde el día 1 | **Bootstrap idempotente al arranque** (`AUTO_MIGRATE=1`: create_all + RLS) **+ Alembic cableado** para todo cambio posterior | Encaja con el flujo Replit (deploy = git push). El RLS vive en un helper único junto al esquema (BD-12). |
| AEAT censal con certificado | **Deshabilitado por defecto** (`AEAT_CENSAL_ENABLED=0`) | El certificado electrónico del titular NO debe subirse a una plataforma sin residencia UE contractual. Ver "Riesgos". |

## Riesgos aceptados (para decisión del negocio)
1. **Residencia de datos (GDPR):** los despliegues de Replit corren en Google Cloud
   con región por defecto en EE. UU. Se tratan datos fiscales de empresas españolas.
   Transferencia internacional amparable en el EU-US Data Privacy Framework
   (Google LLC está certificada), pero exige mención expresa en el contrato de
   encargo de tratamiento y en la política de privacidad. Alternativa de menor
   riesgo si el negocio lo exige: mantener Replit como plataforma de desarrollo y
   desplegar la MISMA imagen en un proveedor UE (el código no cambia: 12-factor).
2. **Un solo rol de BD:** Replit/Neon entrega un único rol propietario. `FORCE ROW
   LEVEL SECURITY` hace que las políticas apliquen también al propietario, pero un
   atacante con la connection string podría deshabilitar RLS. Mitigación: la
   connection string vive solo en Secrets; el audit_log encadenado por hashes hace
   el borrado detectable.
3. **Antivirus:** sin ClamAV. Mitigado por validación estricta de tipo/magia/tamaño
   y porque los ficheros jamás se sirven para ejecución.
