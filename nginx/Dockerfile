FROM nginx:1.25-alpine

COPY ./frontend /usr/share/nginx/html
COPY ./nginx/nginx.conf /etc/nginx/nginx.conf

# Solo 80: el TLS lo termina el proxy de la plataforma. Para un host sin
# terminador delante, construir con nginx.standalone-tls.conf y montar
# los certificados en /etc/nginx/certs.
EXPOSE 80
