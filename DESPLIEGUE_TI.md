# NominaBoard — Guía de despliegue para TI

Documento para el área de TI: cómo dejar el dashboard **NominaBoard** corriendo de forma
permanente, accesible en la red local, **sin depender de que un usuario inicie sesión**.

---

## 1. Contexto actual

- **App:** FastAPI + uvicorn (Python), sirve en el **puerto 8000**.
- **Ruta del proyecto:** `C:\Users\edilson.alvarez\Documents\Grabaciones de sonido\nomina-dashboard`
- **Entorno Python:** `nomina-dashboard\.venv`
- **Comando de arranque correcto:**
  ```
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
  ```
  > El `--host 0.0.0.0` es **obligatorio**. Sin él, uvicorn escucha solo en
  > `127.0.0.1` y las demás máquinas reciben `ERR_CONNECTION_TIMED_OUT`.
- **Acceso:** `http://<IP_DEL_SERVIDOR>:8000/login.html`
- **Firewall:** ya existe la regla inbound **"NominaBoard Puerto 8000"** (Allow). Verificar
  que siga habilitada.

### Estado a reemplazar
Hoy arranca al **iniciar sesión** del usuario `edilson.alvarez` mediante:
- `nomina-dashboard\autostart_server.bat`
- `…\Startup\NominaBoard.vbs` (carpeta de Inicio)

Para un despliegue de servidor, reemplazar esto por **una** de las dos opciones siguientes.
Si se adopta una de ellas, **eliminar** `NominaBoard.vbs` de la carpeta de Inicio para no
tener dos instancias compitiendo por el puerto 8000.

---

## 2. Requisitos previos

1. **IP fija** para la máquina servidor (hoy es `192.168.108.39` por Wi-Fi y puede cambiar).
   Idealmente conexión por cable y reserva DHCP o IP estática.
2. La máquina debe permanecer **encendida**.
3. Confirmar la regla de firewall del puerto 8000 (inbound, TCP, Allow).

---

## 3. Opción A — Tarea Programada (rápida, sin software extra)

Crea una tarea que arranca el servidor **al encender el equipo**, corra o no haya sesión
iniciada. Requiere las credenciales de una cuenta con permiso de "Iniciar sesión como
proceso por lotes".

### Pasos (PowerShell **como Administrador**)

```powershell
$proyecto = "C:\Users\edilson.alvarez\Documents\Grabaciones de sonido\nomina-dashboard"
$py       = "$proyecto\.venv\Scripts\python.exe"

$accion  = New-ScheduledTaskAction -Execute $py `
    -Argument "-m uvicorn app.main:app --host 0.0.0.0 --port 8000" `
    -WorkingDirectory "$proyecto\backend"

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

# Ejecutar aunque no haya sesión iniciada (pide usuario + contraseña de la cuenta):
Register-ScheduledTask -TaskName "NominaBoard" -Action $accion -Trigger $trigger `
    -Settings $settings -RunLevel Highest -User "SUMIMEDICAL\<usuario>" -Password "<contraseña>"
```

> Reemplazar `SUMIMEDICAL\<usuario>` y `<contraseña>` por una cuenta de servicio.
> **No** versionar este comando con la contraseña real.

### Notas
- `-AtStartup` + cuenta con contraseña = corre sin que nadie inicie sesión.
- Si la cuenta de servicio necesita leer el recurso de red del ETL
  (`\\192.168.0.13\fs_sumimedical\…`), las credenciales de ese share están en
  `backend\.env.local` (`NETWORK_SHARE_USER` / `NETWORK_SHARE_PASSWORD`), así que el ETL no
  depende de la identidad de Windows. Aun así, la cuenta de servicio debe poder ejecutar
  Python y acceder a la carpeta del proyecto.
- Verificar: `Get-ScheduledTask -TaskName NominaBoard` y luego abrir el navegador en
  `http://<IP>:8000/login.html`.

---

## 4. Opción B — Servicio real de Windows con NSSM (recomendado)

Un servicio de Windows arranca antes del login, se reinicia solo si se cae y se gestiona
desde `services.msc`. Se usa **NSSM** (Non-Sucking Service Manager, gratuito).

### Pasos
1. Descargar NSSM desde https://nssm.cc y copiar `nssm.exe` a, por ejemplo, `C:\nssm\`.
2. En **CMD/PowerShell como Administrador**:
   ```
   C:\nssm\nssm.exe install NominaBoard
   ```
3. En la ventana de NSSM configurar:
   - **Path:** `C:\Users\edilson.alvarez\Documents\Grabaciones de sonido\nomina-dashboard\.venv\Scripts\python.exe`
   - **Startup directory:** `C:\Users\edilson.alvarez\Documents\Grabaciones de sonido\nomina-dashboard\backend`
   - **Arguments:** `-m uvicorn app.main:app --host 0.0.0.0 --port 8000`
   - Pestaña **I/O** → redirigir stdout/stderr a un log, p. ej.
     `…\nomina-dashboard\logs\service_out.log` y `service_err.log`.
   - Pestaña **Log on** → cuenta de servicio si necesita el recurso de red.
4. Iniciar el servicio:
   ```
   C:\nssm\nssm.exe start NominaBoard
   ```
5. Dejarlo en automático (ya queda así por defecto). Gestión posterior desde `services.msc`.

### Ventajas sobre la Opción A
- Reinicio automático ante caídas.
- No requiere trigger de arranque ni manejo de la contraseña en un script.
- Logs centralizados.

---

## 5. Verificación final (desde otra máquina de la red)

1. `http://<IP_DEL_SERVIDOR>:8000/login.html` debe cargar el login.
2. Si no carga:
   - Confirmar que el proceso escucha en `0.0.0.0`:
     `Get-NetTCPConnection -LocalPort 8000 -State Listen` → `LocalAddress` debe ser `0.0.0.0`.
   - Confirmar regla de firewall inbound del puerto 8000.
   - Confirmar IP del servidor con `ipconfig`.

---

## 6. Seguridad

- `backend\.env.local` contiene credenciales (recurso de red y semilla admin). **No** subir a
  control de versiones ni compartir.
- Restringir el acceso al puerto 8000 a la red interna (no exponer a Internet).
