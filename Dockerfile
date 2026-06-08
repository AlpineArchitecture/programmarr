# ── Stage 1: build React frontend ─────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ ./

# Override outDir so built assets land in a known location within this stage
RUN npx vite build --outDir /build/dist --emptyOutDir


# ── Stage 2: Python runtime ────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend source
COPY backend/ ./backend/

# Pipeline scripts and prompt template
COPY export.py create.py channel_engine.py channel_blocks.py generate_no_ai.py generate_from_collections.py \
     fetch_images.py sync_plex.py PROMPT.md ./

# Built React app → served as static files by FastAPI
COPY --from=frontend-build /build/dist ./backend/static/

ENV PROGRAMMARR_DATA=/data
ENV PROGRAMMARR_SCRIPTS=/app

EXPOSE 7979

WORKDIR /app/backend
CMD ["python", "main.py"]
