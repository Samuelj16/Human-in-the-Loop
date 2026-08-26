# Backend image: API and worker share it, differing only in the start command.
FROM python:3.13-slim

# WeasyPrint renders PDFs through Pango/Cairo, which are system libraries
# rather than Python packages. Without these, PDF export degrades to a 503.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Dependencies first, so code edits do not invalidate the install layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Migrations own the schema in a real deployment; create_all is dev-only.
ENV AUTO_CREATE_SCHEMA=false

EXPOSE 8000

# Apply migrations, then serve. Railway overrides this for the worker service.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
