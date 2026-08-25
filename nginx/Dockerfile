FROM nginx:1.25-alpine

COPY ./frontend /usr/share/nginx/html
COPY ./nginx/nginx.conf /etc/nginx/nginx.conf

# Certificados montados en runtime vía volumen (ver docker-compose).
RUN mkdir -p /etc/nginx/certs

EXPOSE 80 443
