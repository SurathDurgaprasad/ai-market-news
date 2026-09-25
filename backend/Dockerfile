FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code, CLI and the curated source registry. Local data, logs,
# caches and any .env file are excluded by .dockerignore.
COPY . .

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/data /app/logs /app/image_cache \
    && chown -R app:app /app/data /app/logs /app/image_cache
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
