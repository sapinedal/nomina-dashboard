FROM nginx:1.25-alpine

# Copiar los archivos estáticos del frontend
COPY ./frontend /usr/share/nginx/html

# Copiar la configuración personalizada de Nginx
COPY ./nginx/nginx.conf /etc/nginx/nginx.conf

EXPOSE 80
