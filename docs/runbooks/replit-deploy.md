# Runbook — Desplegar Autoken Facturas v2 en Replit

## 1. Crear el Repl
1. Replit → **Create Repl → Import from GitHub** (o subir este zip descomprimido).
2. Replit detecta `.replit` (módulos python-3.12, nodejs-20).

## 2. Base de datos
1. Panel izquierdo → **PostgreSQL** → *Create a database*.
2. Replit inyecta `DATABASE_URL` automáticamente. No hay que tocar nada:
   la app convierte el driver y aplica TLS de Neon sola.

## 3. Secrets (candado 🔒 en el panel)
| Clave | Valor |
|---|---|
| `JWT_SECRET` | `python -c "import secrets;print(secrets.token_urlsafe(64))"` |
| `APP_ENV` | `production` |
| `PLATFORM_ADMIN_EMAILS` | `juliohesuni@gmail.com,albertomurimarti@gmail.com` |
| `STORAGE_BACKEND` | `replit` (y crear **App Storage** en el panel) |
| `MISTRAL_API_KEY` | (opcional: activa el motor Mistral) |
| `AZURE_DOCINTEL_ENDPOINT` / `AZURE_DOCINTEL_KEY` | (opcional: activa Azure) |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` | (opcional: emails) |

Sin claves OCR la app funciona igualmente: PDF con texto se lee gratis
(motor `pdf_native`) y las fotos pasan a entrada manual verificada.

## 4. Seed inicial (una vez)
En la **Shell** del Repl:
```bash
pip install -e ./backend && python scripts/seed.py
```
Imprime las contraseñas iniciales de `platform_admin` y de los tenants
`setex` y `tuti` (demo). Guardarlas y cambiarlas en el primer acceso.
El primer login de plataforma devuelve la URI TOTP: añadirla a Google
Authenticator y volver a entrar con el código (2FA obligatorio).

## 5. Desplegar
1. **Deploy → Reserved VM** (⚠️ no Autoscale: el worker OCR necesita proceso vivo).
2. Build y run ya están definidos en `.replit` (`build.sh` / `run.sh`).
3. Primer arranque: `AUTO_MIGRATE=1` crea tablas y políticas RLS.

## 6. Dominios
1. En Deployments → **Settings → Link a domain**: añadir `setex.autoken.es`
   (CNAME + TXT que indica Replit) y `panel.autoken.es` si se quiere separar.
2. Cada asesoría nueva ⇒ conectar su `slug.autoken.es` (2 minutos).
3. Mientras tanto, todo funciona en `https://<repl>.replit.app/?tenant=setex`.

## 7. Comprobación post-deploy
```bash
curl https://setex.autoken.es/api/v1/health
curl https://setex.autoken.es/api/v1/branding
```
Login de plataforma en `https://<dominio>/plataforma`.

## 8. Operación
- Logs: pestaña *Deployments → Logs* (JSON estructurado con correlation id).
- Backups BD: Replit/Neon hace point-in-time recovery; adicionalmente
  `pg_dump "$DATABASE_URL" > backup.sql` desde la Shell (programable).
- Suspender una asesoría: panel de plataforma → Suspender (corta login y API).
