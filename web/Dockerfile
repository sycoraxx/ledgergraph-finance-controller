FROM node:22-bookworm-slim

WORKDIR /app
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN pnpm run build

EXPOSE 3000
CMD ["pnpm", "run", "start", "--", "--host", "0.0.0.0", "--port", "3000"]
