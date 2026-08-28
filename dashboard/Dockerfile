FROM node:22.18.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run typecheck && npm run test && npm run build

FROM node:22.18.0-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    DASHBOARD_BIND=0.0.0.0 \
    DASHBOARD_CONTAINER_MODE=true \
    DASHBOARD_PORT=8080 \
    DASHBOARD_STATIC_ROOT=/app/dist/web
COPY --from=build --chown=node:node /app/src ./src
COPY --from=build --chown=node:node /app/dist ./dist
USER node
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD node -e "fetch('http://127.0.0.1:8080/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"
CMD ["node", "--experimental-strip-types", "src/server/index.ts"]
