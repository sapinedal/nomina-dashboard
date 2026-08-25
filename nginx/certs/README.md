# TLS — NóminaBoard (DEF-0001)
#
# Colocar certificados confiables por CA pública:
#   fullchain.pem
#   privkey.pem
#
# Let's Encrypt (ejemplo):
#   certbot certonly --webroot -w /usr/share/nginx/html -d nomina.clinicavictoriana.com
#   cp /etc/letsencrypt/live/nomina.clinicavictoriana.com/fullchain.pem ./fullchain.pem
#   cp /etc/letsencrypt/live/nomina.clinicavictoriana.com/privkey.pem ./privkey.pem
#
# NO versionar privkey.pem.
