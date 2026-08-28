# Build the bundle, then serve it from a web server that knows nothing about node.
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
# Static files plus SPA fallback: every route renders index.html, and Caddy in
# front of this one handles TLS and /api.
RUN printf ':80 {\n\troot * /srv\n\tencode gzip\n\ttry_files {path} /index.html\n\tfile_server\n}\n' > /etc/caddy/Caddyfile
EXPOSE 80
