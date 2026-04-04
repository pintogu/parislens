import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="ParisLens API", version="1.0.0")

MODEL_PATH = os.getenv("MODEL_PATH", "model_artifacts/lgb_model_latest.joblib")

# Loaded once the API starts, not on every request, to keep response times low
if not os.path.exists(MODEL_PATH):
    logger.error("Model file not found at %s — /estimate will be unavailable", MODEL_PATH)
    model = None
else:
    model = joblib.load(MODEL_PATH)
    logger.info("Model loaded successfully from %s", MODEL_PATH)

class EstimateRequest(BaseModel):
    surface_m2: float
    rooms: int
    arrondissement: int
    longitude: float = 2.3488 # default to central Paris; sufficient for our Paris-only scope
    latitude: float = 48.8534
    month: int = None
    year: int = None
    
class EstimateResponse(BaseModel):
    estimated_price: float
    estimated_price_per_m2: float
    arrondissement: int
    surface_m2: float

@app.get("/health")
def health():
    # A failed model load should not take the whole API down.
    # This lets the dashboard report partial outage rather than a total one
    model_status = "loaded" if model is not None else "unavailable"
    logger.info("Health check — model status: %s", model_status)
    return {"status": "ok", "model": model_status}

@app.post("/estimate")
def estimate(req: EstimateRequest):
    if model is None:
        logger.error("Estimate requested but model is not loaded")
        raise HTTPException(status_code=503, detail="Model not available")

    now = datetime.now()
    month = req.month or now.month
    year = req.year or now.year

    # Order must match the feature order used in train_model.py
    features = np.array([[
        req.surface_m2,
        req.rooms,
        req.longitude,
        req.latitude,
        req.arrondissement,
        month,
        year,
    ]])

    log_price = model.predict(features)[0]
    total_price = float(np.exp(log_price))  # Model outputs log(price) — reversed here to return euros
    price_per_m2 = total_price / req.surface_m2

    logger.info(
        "Estimate: arr=%s surface=%.1f rooms=%d → €%.0f",
        req.arrondissement, req.surface_m2, req.rooms, total_price
    )

    return EstimateResponse(
        estimated_price_eur=round(total_price, 2),
        estimated_price_per_m2=round(price_per_m2, 2),
        arrondissement=req.arrondissement,
        surface_m2=req.surface_m2,
    )


@app.get("/arrondissements")
def arrondissements():
    # Minimal implementation — a future version would query gold_daily_stats for live per-arrondissement averages
    logger.info("Arrondissements endpoint called")
    return {
        "note": "Per-arrondissement stats are available in the gold_daily_stats table in Postgres",
        "arrondissements": list(range(75001, 75021))
    }
