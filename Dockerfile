FROM python:3.12-slim

RUN apt-get update && apt-get install -y cron && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY .env.example .env

ENV PYTHONPATH=/app/src/pipeline

RUN echo "0 3 * * * cd /app && python src/pipeline/run_pipeline.py >> /app/pipeline.log 2>&1" > /etc/cron.d/parislens-cron
RUN chmod 0644 /etc/cron.d/parislens-cron
RUN crontab /etc/cron.d/parislens-cron

CMD ["sh", "-c", "python src/database/init_db.py && python src/pipeline/run_pipeline.py && cron -f"]