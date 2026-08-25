FROM python:3.12-slim

WORKDIR /opt/dagster/app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DAGSTER_HOME=/dagster_home

RUN python -m pip install --upgrade pip && \
    python -m pip install dagster dagster-webserver python-dotenv pandas clickhouse-connect openpyxl holidays

COPY dagster_app ./dagster_app
COPY .env .env
COPY dagster_home /dagster_home

RUN mkdir -p /dagster_home /var/lib/dagster /var/lib/dagster/compute_logs /var/lib/dagster/artifacts

EXPOSE 3000

CMD ["dagster", "dev", "-m", "dagster_app", "-h", "0.0.0.0", "-p", "3000"]
