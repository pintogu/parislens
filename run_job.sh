#!/bin/sh
set -eu

JOB="${1:-pipeline}"

case "$JOB" in
  init-db)
    python src/database/init_db.py
    ;;
  pipeline)
    python src/pipeline/run_pipeline.py
    ;;
  train)
    python src/model/train_model.py
    ;;
  full)
    python src/database/init_db.py
    python src/pipeline/run_pipeline.py
    python src/model/train_model.py
    ;;
  *)
    echo "Unknown job: $JOB"
    echo "Supported jobs: init-db | pipeline | train | full"
    exit 1
    ;;
esac
