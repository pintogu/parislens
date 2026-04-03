FROM python:3.12-slim

RUN apt-get update && apt-get install -y cron libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY .env.example .env

ENV PYTHONPATH=/app/src/pipeline

# Create directory for model artifacts
RUN mkdir -p /app/model_artifacts

# Cron job for data pipeline (3am daily)
RUN echo "0 3 * * * cd /app && python src/pipeline/run_pipeline.py >> /app/pipeline.log 2>&1" > /etc/cron.d/parislens-cron

# Cron job for model training (1st of month at 4am)
RUN echo "0 4 1 * * cd /app && python src/model/train_model.py >> /app/model_training.log 2>&1" >> /etc/cron.d/parislens-cron

RUN chmod 0644 /etc/cron.d/parislens-cron
RUN crontab /etc/cron.d/parislens-cron

CMD ["sh", "-c", "python src/database/init_db.py && python src/pipeline/run_pipeline.py && python src/model/train_model.py && cron -f"]