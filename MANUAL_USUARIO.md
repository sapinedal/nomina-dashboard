# NóminaBoard — Manual de Usuario

## ¿Qué es NóminaBoard?

NóminaBoard es un sistema web que consolida y visualiza automáticamente las
novedades de nómina desde los archivos Excel almacenados en la carpeta
compartida de red. Los tableros se actualizan cada mes sin intervención manual.

---

## 1. Acceso al sistema

Abrir el navegador y navegar a: **http://[ip-del-servidor]**

Ingresar usuario y contraseña asignados por el Administrador.

**Perfiles disponibles:**

| Perfil | Qué puede hacer |
|---|---|
| **Administrador** | Acceso total: tableros, historial, usuarios, ejecutar carga |
| **Analista** | Ver tableros, exportar Excel y PDF |
| **Consulta** | Solo visualización de tableros e historial |

---

## 2. Tablero principal

Al iniciar sesión se muestra el **Tablero de Novedades de Nómina** con:

### Indicadores KPI (parte superior)
- **Total Novedades**: número total de registros con los filtros activos
- **Empleados**: cantidad de empleados únicos con novedades
- **Áreas**: número de áreas distintas
- **Tipos Novedad**: tipos de novedad únicos
- **Valor Total**: suma del campo Valor de todos los registros
- **Prom. Días**: promedio de días por novedad

### Gráficas
| Gráfica | Descripción |
|---|---|
| Novedades por Tipo | Barras con los tipos de novedad más frecuentes |
| Novedades por Área | Barras horizontales con áreas de mayor actividad |
| Tendencia Mensual | Línea doble: cantidad y valor total por mes |
| Valor por Área | Barras horizontales con el valor acumulado por área |

### Tabla de detalle
Muestra los registros individuales con: Cédula, Nombre, Área, Cargo,
Tipo de Novedad, Fechas, Días, Valor, Período y Archivo de origen.

- **Ordenar**: hacer clic en el encabezado de cualquier columna marcada con ↑↓
- **Paginar**: usar los botones Anterior / Siguiente en la parte inferior

---

## 3. Uso de filtros

La barra de filtros está en la parte superior del tablero:

| Filtro | Descripción |
|---|---|
| **Desde / Hasta** | Rango de fechas de inicio de novedad |
| **Período** | Mes en formato YYYY-MM (ej: 2025-01) |
| **Área** | Área o dependencia (lista desplegable) |
| **Tipo de Novedad** | Tipo de novedad (lista desplegable) |

1. Seleccionar los valores deseados
2. Hacer clic en **Filtrar**
3. Todos los KPIs, gráficas y la tabla se actualizan simultáneamente
4. Para quitar los filtros, hacer clic en **✕** (limpiar)

---

## 4. Exportación de datos

*(Disponible para Administradores y Analistas)*

En la barra superior del tablero:

- **Excel**: descarga un archivo `.xlsx` con todos los registros que coincidan
  con los filtros activos, con formato de encabezados y columnas ajustadas.
- **PDF**: descarga un resumen ejecutivo en `.pdf` con KPIs y hasta 500
  registros de la tabla.

---

## 5. Historial de ejecuciones

Ir a **Historial** en el menú lateral.

Muestra las últimas 20 ejecuciones del proceso de carga con:
- Fecha y hora de inicio/fin
- Duración
- Tipo (programado / manual)
- Estado (Completado / Fallido / Parcial)
- Archivos procesados y registros insertados

**Ver detalle**: hacer clic en el ícono 👁 de cualquier fila para ver:
- Resumen de métricas de esa ejecución
- Lista de cada archivo procesado con sus hojas, registros y posibles errores

---

## 6. Administración de usuarios

*(Solo Administradores — menú "Usuarios")*

### Crear usuario
1. Hacer clic en **Nuevo Usuario**
2. Completar: usuario, nombre, correo, rol y contraseña
3. Hacer clic en **Guardar**

### Editar usuario
1. Hacer clic en el ícono ✏️ junto al usuario
2. Modificar los campos necesarios
3. Para cambiar la contraseña, ingresar la nueva en el campo correspondiente
4. Hacer clic en **Guardar**

### Desactivar usuario
Editar el usuario y desmarcar **Usuario activo**.

### Roles disponibles
- **Consulta**: visualización únicamente
- **Analista**: visualización + exportación
- **Administrador**: acceso total

---

## 7. Ejecución manual del proceso ETL

*(Solo Administradores)*

Para cargar los datos inmediatamente sin esperar el día 30:

1. En el menú lateral, hacer clic en **Ejecutar ETL**
2. Confirmar en el diálogo de confirmación
3. El proceso se ejecuta en segundo plano (puede tardar varios minutos
   dependiendo del número y tamaño de los archivos)
4. Al finalizar, el tablero se actualizará automáticamente
5. Verificar el resultado en **Historial**

---

## 8. Comportamiento automático mensual

El sistema ejecuta automáticamente el proceso de carga cada mes:
- **Cuándo**: día 30 de cada mes a las 23:00 horas (hora Colombia)
- **Qué hace**: lee todos los archivos Excel de la carpeta compartida,
  procesa cada hoja, valida los datos y actualiza la base de datos
- **Resultado**: al día siguiente los tableros reflejan los datos del mes cerrado

---

## 9. Preguntas frecuentes

**¿Qué archivos se procesan?**
Solo archivos con extensiones `.xlsx`, `.xls` y `.xlsm`. Los archivos
temporales (que empiezan con `~$`) son ignorados automáticamente.

**¿Qué pasa si un archivo tiene columnas diferentes?**
El sistema normaliza automáticamente los nombres de columnas y adapta la
estructura. Las columnas no reconocidas se guardan en un campo adicional
para trazabilidad.

**¿Puedo ver de qué archivo viene cada registro?**
Sí. La columna **Archivo** en la tabla muestra el nombre del archivo
Excel de origen de cada registro.

**¿Los datos se duplican si el ETL se ejecuta varias veces?**
Cada ejecución ETL inserta los registros nuevamente. Se recomienda limpiar
la tabla antes de recargar todo el histórico (contactar al Administrador).

**¿Qué significa "Período"?**
Es el mes al que corresponde la novedad, en formato `YYYY-MM` (ej: `2025-01`).
Se infiere automáticamente de la fecha de inicio o del nombre del archivo.

---

## 10. Soporte

Para soporte técnico o reporte de errores, contactar al área de Sistemas
con la siguiente información:
- Fecha y hora del problema
- Mensaje de error visible en pantalla (captura de pantalla)
- Usuario con el que inició sesión
- Acción que estaba realizando
