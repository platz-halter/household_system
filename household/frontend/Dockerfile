FROM nginx:1.27-alpine

# Clean path-based routing (/home, /board, ...) still means every
# route is index.html + client-side JS — nginx.conf's SPA fallback
# (try_files ... /index.html) is the one rule that makes a direct
# load/refresh of a deep route work without a 404.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY manifest.json /usr/share/nginx/html/manifest.json
COPY sw.js /usr/share/nginx/html/sw.js
COPY css /usr/share/nginx/html/css
COPY js /usr/share/nginx/html/js
COPY icons /usr/share/nginx/html/icons

EXPOSE 80
