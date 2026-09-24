FROM nginx:1.27-alpine

# Hash-based routing (#/overview, #/settings) means every route is just
# index.html + client-side JS — no server-side rewrite rules needed.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY css /usr/share/nginx/html/css
COPY js /usr/share/nginx/html/js

EXPOSE 80
