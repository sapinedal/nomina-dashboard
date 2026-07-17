import sys
sys.path.insert(0, '.')
from app.database import SessionLocal
from app.services import dashboard_service as svc

db = SessionLocal()

a = svc.get_panel_ausentismo(db, {})
print("AUSENTISMO:")
print("  valor_total:", f"{a['total_valor_ausentismo']:,.0f}")
for t in a['valor_por_tipo']:
    print(f"  {t['tipo'][:35]:<35} dias={t['dias']:>7.1f}  valor={t['valor']:>14,.0f}  rem={t['remunerado']}")

h = svc.get_panel_horas_extras(db, {})
print("\nHORAS EXTRAS:")
print("  total_valor_pagado:", f"{h['total_valor_pagado']:,.0f}")
for t in h['valor_por_tipo']:
    print(f"  {t['tipo'][:40]:<40} h={t['horas']:>8.1f}  valor={t['valor']:>14,.0f}  x{t['factor']}")

print("\nTop 3 empleados:")
for e in h['top_empleados'][:3]:
    print(f"  {e['nombre'][:28]:<28} {e['horas']:.1f}h  {e['valor']:,.0f}")

db.close()
