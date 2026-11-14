# Imagen de la API (FastAPI) y del servicio de bootstrap.
FROM python:3.12.8-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements/app.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY pyproject.toml /app/
COPY src /app/src
COPY tests /app/tests
RUN pip install --no-cache-dir --no-deps /app

RUN useradd --create-home --uid 1000 app \
 && mkdir -p /cache_modelo && chown app /cache_modelo
USER app

EXPOSE 8000
# keep-alive largo: evita cortar conexiones que un cliente reutiliza tras unos segundos
CMD ["uvicorn", "novamercado.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "75"]
