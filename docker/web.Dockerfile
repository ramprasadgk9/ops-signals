FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
RUN npm run build

FROM nginx:1.27-alpine

# Rendered to /etc/nginx/conf.d/default.conf by the image's envsubst step at startup.
COPY docker/nginx.web.conf /etc/nginx/templates/default.conf.template
ENV OPS_SIGNALS_BACKEND_URL="http://ops-signals-backend:8000/api/"
ENV OPS_SIGNALS_API_TOKEN=""
ENV OPS_SIGNALS_AUTH_MODE="none"
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
