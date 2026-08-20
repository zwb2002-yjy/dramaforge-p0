FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27.4-alpine

ARG DRAMAFORGE_VERSION=0.1.0
ARG DRAMAFORGE_SOURCE_COMMIT=local

LABEL org.opencontainers.image.title="DramaForge frontend" \
      org.opencontainers.image.version=$DRAMAFORGE_VERSION \
      org.opencontainers.image.revision=$DRAMAFORGE_SOURCE_COMMIT \
      org.opencontainers.image.source="https://github.com/zwb2002-yjy/DramaForge"

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/gateway-health || exit 1
