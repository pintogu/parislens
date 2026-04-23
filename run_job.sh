#!/bin/sh
set -eu

JOB="${1:-pipeline}"

wait_for_db() {
  HOST="${DB_HOST:-postgres}"
  PORT="${DB_PORT:-5432}"

  echo "Waiting for database at $HOST:$PORT..."

  until nc -z "$HOST" "$PORT"; do
    echo "Database not ready yet, retrying..."
    sleep 1
  done

  echo "Database is ready."
}

run_init_db() {
  echo "Initializing database..."
  python src/database/init_db.py
}

run_pipeline() {
  echo "Running pipeline..."
  python src/pipeline/run_pipeline.py
}

run_train() {
  echo "Training model..."
  python src/model/train_model.py
}

echo "Running job: $JOB"

case "$JOB" in
  init-db)
    wait_for_db
    run_init_db
    ;;
  pipeline)
    wait_for_db
    run_pipeline
    ;;
  train)
    wait_for_db
    run_train
    ;;
  full)
    wait_for_db
    run_init_db
    run_pipeline
    run_train
    ;;
  *)
    echo "Unknown job: $JOB"
    echo "Supported jobs: init-db | pipeline | train | full"
    exit 1
    ;;
esac

echo "Job '$JOB' completed successfully."