# Airflow con un entorno virtual de ML separado (/opt/venv-ml) para no mezclar
# las dependencias del modelo con las restricciones de versiones de Airflow.
FROM apache/airflow:2.10.4-python3.12

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && python -m venv /opt/venv-ml \
 && chown -R airflow:root /opt/venv-ml

USER airflow
COPY requirements/ml.txt /tmp/ml.txt
RUN /opt/venv-ml/bin/pip install --no-cache-dir -r /tmp/ml.txt

COPY --chown=airflow:root pyproject.toml /opt/novamercado/
COPY --chown=airflow:root src /opt/novamercado/src
RUN /opt/venv-ml/bin/pip install --no-cache-dir --no-deps /opt/novamercado \
 && mkdir -p /opt/airflow/trabajo
