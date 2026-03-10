FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY init_db.py .
COPY run_pipeline.py .
COPY bronze_to_silver.py .
COPY silver_to_gold.py .
COPY load_dvf.py .

# Create tables first, then run the pipeline
CMD ["sh", "-c", "python init_db.py && python run_pipeline.py"]
