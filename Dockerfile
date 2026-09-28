# ---- build the React UI ----
FROM node:22-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

# ---- Python app: agent + web API + built UI ----
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY vanguard ./vanguard
COPY config ./config
RUN pip install --no-cache-dir .
COPY --from=ui /ui/dist ./ui/dist
ENV VANGUARD_DB=/app/data/vanguard.db \
    VANGUARD_OUTPUT=/app/output \
    VANGUARD_NOTION_CONFIG=/app/data/notion.json \
    VANGUARD_UI_DIST=/app/ui/dist
VOLUME ["/app/data", "/app/output"]
EXPOSE 8080
CMD ["vanguard", "serve", "--port", "8080"]
