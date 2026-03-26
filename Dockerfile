FROM python:3.12-slim

# Install cron
RUN apt-get update && apt-get install -y cron && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the whole src folder instead of individual files
COPY src/ ./src/
COPY .env.example .env

# Add cron job to run pipeline every day at 3am
RUN echo "0 3 * * * cd /app && python src/pipeline/run_pipeline.py >> /app/pipeline.log 2>&1" > /etc/cron.d/parislens-cron
RUN chmod 0644 /etc/cron.d/parislens-cron
RUN crontab /etc/cron.d/parislens-cron

# Create tables first, then start cron in foreground
CMD ["sh", "-c", "python src/database/init_db.py && python src/pipeline/run_pipeline.py && cron -f"]