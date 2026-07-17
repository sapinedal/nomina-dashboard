"""
Prueba del algoritmo de lectura de excel_processor.py con el archivo real.
Ejecutar con: python inspect_excel.py
"""
import re
import pandas as pd

path = "\\\\192.168.0.13\\fs_sumimedical\\SUBGERENCIA ADMINISTRATIVA Y FINANCIERA\\DIRECCIÓN ADMINISTRATIVA\\NOVEDADES NOMINA\\CONSOLIDADO\\CONSOLIDADO NOVEDADES ADMINISTRATIVAS MAYO  2026.xlsx"

# ── MISMA LÓGICA QUE excel_processor.py ─────────────────────────────────────

HEADER_KEYWORDS = ["identificaci", "cedula", "cédula", "nombres y", "apellido", "sede", "cargo", "tipo novedad"]

_COL_CEDULA = ['identificaci', 'cédula', 'cedula', 'documento', 'c.c']
_COL_NOMBRE = ['nombres y apellidos', 'nombres y', 'nombre y', 'apellidos y nombres']
_COL_SEDE   = ['sede', 'área', 'dependencia']
_COL_FI     = ['fecha inicio', 'fecha_inicio', 'inicio novedad', 'fehca inicio', 'fecha inico']
_COL_FF     = ['fecha fin', 'fecha final', 'fehca fin', 'fehca final', 'fin novedad', 'final novedad']
_COL_OBS    = ['observaci']
_COL_SKIP   = ['no.', 'n°', 'salario', 'bloque de hora', 'horas laboradas',
               'fecha de aprobaci', 'versión', 'version', 'código', 'codigo']

def find_header_row(xl, sheet, max_scan=15):
    df_raw = xl.parse(sheet, header=None, nrows=max_scan, dtype=str)
    for i, row in df_raw.iterrows():
        txt = ' '.join(
            str(v).lower().strip().replace('fehca', 'fecha')
            for v in row.values if str(v) not in ('nan', 'None', '')
        )
        if any(kw in txt for kw in HEADER_KEYWORDS):
            return i
    return 0

def classify_col(col):
    c = str(col).lower().strip().replace('fehca', 'fecha')
    if any(p in c for p in _COL_CEDULA):   return 'cedula'
    if any(p in c for p in _COL_NOMBRE):   return 'nombre_empleado'
    if any(p in c for p in _COL_SEDE):     return 'sede'
    if re.search(r'\barea\b', c):           return 'sede'
    if any(p in c for p in _COL_FI):       return 'fecha_inicio'
    if any(p in c for p in _COL_FF):       return 'fecha_fin'
    if any(p in c for p in _COL_OBS):      return 'observaciones'
    if any(p in c for p in _COL_SKIP):     return '__skip'
    if c.startswith('unnamed') or c in ('nan', 'no', 'n°', 'num', '#', ''):
        return '__skip'
    return None  # novedad

# ── PRUEBA ───────────────────────────────────────────────────────────────────

xl = pd.ExcelFile(path)
print(f"Hojas encontradas: {len(xl.sheet_names)}")
sheet = xl.sheet_names[0]
print(f"Analizando hoja: '{sheet}'\n")

header_row = find_header_row(xl, sheet)
print(f"Fila de encabezado: {header_row}")

df = xl.parse(sheet, header=header_row, dtype=str)
df = df.dropna(how='all')
print(f"Filas de datos: {len(df)}, Columnas: {len(df.columns)}\n")

identity_rename = {}
novedad_cols = []
skip_cols = []

for col in df.columns:
    cls = classify_col(str(col))
    if cls == '__skip':
        skip_cols.append(col)
    elif cls is not None:
        if cls not in identity_rename.values():
            identity_rename[col] = cls
        else:
            skip_cols.append(col)
    else:
        novedad_cols.append(col)

print("=== COLUMNAS DE IDENTIDAD ===")
for orig, std in identity_rename.items():
    print(f"  '{orig}' => '{std}'")

print(f"\n=== COLUMNAS DE NOVEDAD ({len(novedad_cols)}) ===")
for c in novedad_cols:
    print(f"  '{c}'")

print(f"\n=== COLUMNAS IGNORADAS ({len(skip_cols)}) ===")
for c in skip_cols:
    print(f"  '{c}'")

if not novedad_cols:
    print("\n⚠️  NO SE ENCONTRARON COLUMNAS DE NOVEDAD - revisar clasificación")
    exit(1)

# Renombrar y melt
df = df.drop(columns=skip_cols, errors='ignore')
df = df.rename(columns=identity_rename)
id_vars = [c for c in identity_rename.values() if c in df.columns]
novedad_present = [c for c in novedad_cols if c in df.columns]

print(f"\nid_vars para melt: {id_vars}")
print(f"value_vars (primeros 5): {novedad_present[:5]}")

df_long = df.melt(
    id_vars=id_vars,
    value_vars=novedad_present,
    var_name='tipo_novedad',
    value_name='valor_novedad',
)
print(f"\nTotal filas tras melt: {len(df_long)}")

null_vals = {'nan', 'none', ''}
df_long = df_long[
    df_long['valor_novedad'].notna() &
    (~df_long['valor_novedad'].astype(str).str.strip().str.lower().isin(null_vals))
]
print(f"Filas con novedad no nula: {len(df_long)}")

mask = pd.Series(False, index=df_long.index)
if 'cedula' in df_long.columns:
    mask |= df_long['cedula'].notna() & (~df_long['cedula'].astype(str).str.lower().isin(null_vals))
if 'nombre_empleado' in df_long.columns:
    mask |= df_long['nombre_empleado'].notna() & (~df_long['nombre_empleado'].astype(str).str.lower().isin(null_vals))
df_long = df_long[mask]
print(f"Filas con empleado identificado: {len(df_long)}")

if len(df_long) > 0:
    print("\n=== PRIMERAS 10 FILAS DEL RESULTADO ===")
    cols = ['cedula', 'nombre_empleado', 'sede', 'tipo_novedad', 'valor_novedad', 'fecha_inicio', 'fecha_fin', 'observaciones']
    cols = [c for c in cols if c in df_long.columns]
    print(df_long[cols].head(10).to_string())
    print(f"\n✅  ÉXITO — {len(df_long)} registros procesados en la hoja '{sheet}'")
else:
    print("\n❌  0 registros — revisar datos de la hoja")
