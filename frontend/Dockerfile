FROM nginx:alpine

# Přepiš defaultní konfiguraci vlastním nginx.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Zkopíruj všechny statické soubory
COPY . /usr/share/nginx/html

EXPOSE 80
