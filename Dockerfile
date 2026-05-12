# Multi-stage Dockerfile: builds frontend and runs FastAPI backend

# --- Frontend build stage ---
FROM node:18-alpine AS frontend
WORKDIR /app/temp_frontend
COPY temp_frontend/package*.json ./
COPY temp_frontend/pnpm-lock.yaml* ./ || true
RUN npm ci --silent
COPY temp_frontend/ .
RUN npm run build

# --- Backend runtime stage ---
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System deps for common packages
RUN apt-get update && apt-get install -y build-essential ffmpeg git --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Copy built frontend into a folder the backend can serve
RUN mkdir -p web/frontend_dist
COPY --from=frontend /app/temp_frontend/dist web/frontend_dist

# Expose the port Uvicorn will run on
EXPOSE 8000

# Default command
# Copy startup script and make executable
COPY scripts/start.sh /app/scripts/start.sh
RUN chmod +x /app/scripts/start.sh

# Entrypoint runs the startup script (will download model if MODEL_URL set)
ENTRYPOINT ["/app/scripts/start.sh"]
