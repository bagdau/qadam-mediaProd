# syntax=docker/dockerfile:1.7

# ---------- deps (cached layer) ----------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ---------- development target: Vite dev server with HMR ----------
FROM node:22-alpine AS dev
WORKDIR /app
ENV NODE_ENV=development
RUN chown node:node /app
COPY --chown=node:node --from=deps /app/node_modules ./node_modules
COPY --chown=node:node . .
USER node
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---------- build ----------
FROM deps AS build
COPY . .
RUN npm run build

# ---------- production: static files behind unprivileged nginx ----------
FROM nginxinc/nginx-unprivileged:1.27-alpine AS production
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -q --spider http://127.0.0.1:8080/healthz || exit 1
