# ============================================================
# Staykaro Admin Dashboard — Next.js (NH-06/07/08)
# 3-stage build (deps -> builder -> runner), non-root runtime user,
# matching the style of services/api/Dockerfile and services/worker/Dockerfile.
# ============================================================

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# npm ci requires a lockfile; falls back to install only if one hasn't been
# committed yet (first-time setup) — CI always has a lockfile by then.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Next.js inlines NEXT_PUBLIC_* variables into the client bundle at build
# time, not runtime — so this must be a build ARG, not just a compose env var.
ARG NEXT_PUBLIC_API_URL=http://localhost/api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN addgroup -S appuser && adduser -S appuser -G appuser

# `output: standalone` (next.config.js) produces a minimal server.js plus
# only the node_modules it actually needs — static assets must be copied in
# separately since standalone output doesn't include them by default.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 3000

# basePath (/admin) applies to every route the Next server handles,
# including local requests — the healthcheck path must include it too.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
  CMD wget -qO- http://localhost:3000/admin/api/health || exit 1

CMD ["node", "server.js"]
