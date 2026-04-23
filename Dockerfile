FROM python:3.12-slim-bookworm

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g; s|http://security.debian.org|https://security.debian.org|g' /etc/apt/sources.list.d/debian.sources \
	&& apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
	&& apt-get install -y --no-install-recommends libgomp1 netcat-openbsd \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY .env.example .env
COPY run_job.sh ./run_job.sh

ENV PYTHONPATH=/app/src/pipeline

# Create directory for model artifacts
RUN mkdir -p /app/model_artifacts
RUN chmod +x run_job.sh

CMD ["./run_job.sh", "pipeline"]