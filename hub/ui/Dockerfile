# Build from the repository root so LICENSE/NOTICE can be included:
#   docker build -f hub/ui/Dockerfile .
#
# ---------- build ----------
FROM node:24-alpine AS build
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10.34.7 --activate

COPY hub/ui/package.json hub/ui/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY hub/ui/ ./

ARG VITE_API_BASE=/api
ARG VITE_API_ENDPOINT=
ARG VITE_GITHUB_REPO=unikii/dsentry
ENV VITE_API_BASE=$VITE_API_BASE \
    VITE_API_ENDPOINT=$VITE_API_ENDPOINT \
    VITE_GITHUB_REPO=$VITE_GITHUB_REPO

RUN pnpm run build

# ---------- serve ----------
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY hub/ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY LICENSE NOTICE /usr/share/doc/dsentry/
EXPOSE 80
