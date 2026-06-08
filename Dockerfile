# Stage 1: Build the React frontend
FROM node:20-alpine AS frontend
WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: Python runtime serving API + static SPA
FROM python:3.11-slim
WORKDIR /app

COPY pyproject.toml ./
COPY arslan/ ./arslan/
RUN pip install --no-cache-dir -e ".[server]"

COPY server/ ./server/
COPY alembic.ini ./
COPY --from=frontend /app/web/dist ./server/static/

EXPOSE 8741
CMD ["sh", "-c", "alembic upgrade head && uvicorn server.main:app --host 0.0.0.0 --port 8741 --ws-ping-interval 20 --ws-ping-timeout 20"]
