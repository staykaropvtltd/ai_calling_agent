FROM nginx:alpine

# Dev config (used by default in container)
COPY nginx.conf /etc/nginx/nginx.conf
# Prod config — docker-compose.prod.yml bind-mounts this over nginx.conf at runtime
COPY nginx.prod.conf /etc/nginx/nginx.prod.conf

COPY portal.html /usr/share/nginx/html/portal.html
