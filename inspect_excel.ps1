# Inspecciona el archivo Excel y muestra sus columnas reales
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

$script = @'
import pandas as pd
import sys

path = r"\\192.168.0.13\fs_sumimedical\SUBGERENCIA ADMINISTRATIVA Y FINANCIERA\DIRECCIÓN ADMINISTRATIVA\NOVEDADES NOMINA\CONSOLIDADO\CONSOLIDADO NOVEDADES ADMINISTRATIVAS MAYO  2026.xlsx"

try:
    xl = pd.ExcelFile(path)
    print("HOJAS ENCONTRADAS:", xl.sheet_names)
    for sheet in xl.sheet_names:
        try:
            df = xl.parse(sheet, nrows=5)
            if df.empty:
                print(f"\n[{sheet}] VACÍA")
                continue
            print(f"\n{'='*60}")
            print(f"HOJA: {sheet}  ({len(df)} filas muestra, {len(df.columns)} columnas)")
            print(f"COLUMNAS: {list(df.columns)}")
            print("MUESTRA:")
            for i, row in df.iterrows():
                non_null = {k:v for k,v in row.items() if str(v) not in ('nan','None','',) }
                print(f"  Fila {i}: {non_null}")
                if i >= 2:
                    break
        except Exception as e:
            print(f"\n[{sheet}] ERROR: {e}")
except Exception as e:
    print("ERROR ABRIENDO ARCHIVO:", e)
'@

& $python -c $script
