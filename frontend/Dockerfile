# syntax=docker/dockerfile:1.7
# ---- build the static SPA ----
FROM node:20-alpine AS build
WORKDIR /app
# Install deps first (cached unless package manifests change).
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

# ---- serve with nginx (non-root, port 8080) ----
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Make nginx runnable by an unprivileged user: pid + temp under writable paths.
RUN sed -i 's#pid .*#pid /tmp/nginx.pid;#' /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx
USER nginx
EXPOSE 8080
# Custom entrypoint writes runtime config.js from env, then starts nginx. We use
# our own entrypoint (not /docker-entrypoint.d) because the stock nginx entrypoint
# only runs those hooks as root, and we run unprivileged.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
