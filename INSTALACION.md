# NóminaBoard — Guía de Instalación y Despliegue

## Requisitos previos

| Componente | Versión mínima |
|---|---|
| Docker Desktop | 4.x |
| Docker Compose | 2.x |
| Windows 10/11 o Windows Server 2019+ | — |
| Acceso a `\\192.168.0.13\fs_sumimedical\...` | — |

---

## 1. Clonar / copiar el proyecto

```
nomina-dashboard\
├── backend\
├── frontend\
├── sql\
├── nginx\
├── docker-compose.yml
└── .env.example
```

---

## 2. Configurar variables de entorno

```powershell
copy .env.example .env
notepad .env
```

Valores **obligatorios** a modificar:

```env
SECRET_KEY=genera_una_clave_larga_y_aleatoria_aqui
POSTGRES_PASSWORD=contrasena_muy_segura
DATABASE_URL=postgresql://nomina_user:contrasena_muy_segura@db:5432/nomina_dashboard
NETWORK_SHARE_PATH=\\\\192.168.0.13\\fs_sumimedical\\SUBGERENCIA ADMINISTRATIVA Y FINANCIERA\\DIRECCIÓN ADMINISTRATIVA\\NOVEDADES NOMINA\\CONSOLIDADO
NETWORK_SHARE_USER=tu_usuario_de_red
NETWORK_SHARE_PASSWORD=tu_contrasena_de_red
NETWORK_SHARE_DOMAIN=SUMIMEDICAL
```

> **Generar SECRET_KEY segura (PowerShell):**
> ```powershell
> python -c "import secrets; print(secrets.token_hex(32))"
> ```

---

## 3. Montar la carpeta de red en Windows (antes de Docker)

El contenedor Docker en Windows necesita que la carpeta compartida esté
mapeada como unidad de red o montada. La forma más simple:

```powershell
# Mapear la carpeta compartida como unidad Z:
net use Z: "\\192.168.0.13\fs_sumimedical" /user:SUMIMEDICAL\tu_usuario tu_contrasena /persistent:yes
```

Luego en `docker-compose.yml`, añadir el volumen bajo el servicio `backend`:

```yaml
volumes:
  - Z:\SUBGERENCIA ADMINISTRATIVA Y FINANCIERA\DIRECCIÓN ADMINISTRATIVA\NOVEDADES NOMINA\CONSOLIDADO:/mnt/nomina_share:ro
```

Y en `.env`:
```env
NETWORK_SHARE_PATH=/mnt/nomina_share
```

---

## 4. Construir e iniciar los contenedores

```powershell
# Primera vez (construye imágenes + inicializa BD)
docker compose up -d --build

# Ver logs en tiempo real
docker compose logs -f backend

# Verificar que todos los servicios están OK
docker compose ps
```

**Servicios desplegados:**

| Servicio | Puerto | URL |
|---|---|---|
| Frontend (Nginx) | 80 | http://localhost |
| Backend (FastAPI) | 8000 | http://localhost:8000 |
| PostgreSQL | 5432 | localhost:5432 |
| Redis | 6379 | interno |

---

## 5. Primer acceso

Abrir el navegador en: **http://localhost**

Credenciales iniciales:

| Usuario | Contraseña | Rol |
|---|---|---|
| `admin` | `Admin2024!` | Administrador |
| `analista` | `Admin2024!` | Analista |
| `consultor` | `Admin2024!` | Consulta |

> **IMPORTANTE:** Cambiar todas las contraseñas después del primer inicio de sesión.

---

## 6. Documentación de la API

Swagger UI disponible en: **http://localhost:8000/api/docs**
ReDoc disponible en: **http://localhost:8000/api/redoc**

---

## 7. Programador automático

El sistema ejecuta el ETL automáticamente el **día 30 de cada mes a las 23:00**
hora Colombia (America/Bogota) usando APScheduler integrado en FastAPI.

Para cambiar la programación, editar en `.env`:
```env
SCHEDULER_DAY=30
SCHEDULER_HOUR=23
SCHEDULER_MINUTE=0
```

Para ejecutar manualmente: Panel Admin → **Ejecutar ETL** (requiere rol Administrador).

---

## 8. Comandos de mantenimiento

```powershell
# Detener servicios
docker compose down

# Ver logs del backend
docker compose logs backend --tail=100

# Reiniciar solo el backend
docker compose restart backend

# Backup de la base de datos
docker exec nomina_db pg_dump -U nomina_user nomina_dashboard > backup_$(Get-Date -Format "yyyyMMdd").sql

# Restaurar backup
Get-Content backup_20241230.sql | docker exec -i nomina_db psql -U nomina_user nomina_dashboard

# Actualizar imágenes
docker compose pull
docker compose up -d --build
```

---

## 9. Estructura de logs

Los logs se guardan en `./logs/nomina_dashboard.log` (formato JSON estructurado).

```powershell
# Ver logs en tiempo real
Get-Content .\logs\nomina_dashboard.log -Wait
```

---

## 10. Solución de problemas comunes

| Problema | Causa probable | Solución |
|---|---|---|
| No se puede acceder a la carpeta de red | Credenciales incorrectas o sin permisos | Verificar `net use` y credenciales en `.env` |
| Error 401 en la API | Token expirado o inválido | Cerrar sesión y volver a entrar |
| Base de datos no inicializa | Puerto 5432 en uso | Cambiar `POSTGRES_PORT` en docker-compose.yml |
| ETL no procesa archivos | Archivos con extensión incorrecta o temporales | Verificar que los archivos sean `.xlsx`, `.xls` o `.xlsm` |
| Contenedor backend en `Restarting` | Error de configuración o BD no disponible | `docker compose logs backend` para ver el error |
