import psycopg2
import os
import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path

from sklearn.model_selection import KFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import lightgbm as lgb
from sqlalchemy import create_engine

from logger import get_logger

load_dotenv()
logger = get_logger("parislens")

# Create artifacts directory if it doesn't exist
ARTIFACTS_DIR = Path("/app/model_artifacts")
ARTIFACTS_DIR.mkdir(exist_ok=True)


def get_features():
    num_features = ["surface_m2", "rooms", "longitude", "latitude", "month", "year"]
    cat_features = ["arrondissement"]
    return num_features, cat_features


def build_lgb_pipeline(num_features, cat_features):
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", "passthrough", num_features),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cat_features),
        ]
    )
    preprocessor.set_output(transform="pandas")
    
    model = Pipeline([
        ("prep", preprocessor),
        ("model", lgb.LGBMRegressor(
            n_estimators=500,
            learning_rate=0.05,
            num_leaves=31,
            random_state=42,
            verbose=-1
        ))
    ])
    
    return model


def prepare_data(df_raw):
    df = df_raw.copy()
    
    # log-transform for stability
    y = np.log(df["price_eur"])
    
    df["month"] = df["scraped_at"].dt.month
    df["year"] = df["scraped_at"].dt.year
    
    X = df.drop(columns=[
        "price_eur",
        "price_per_m2",
        "id",
        "bronze_id",
        "scraped_at",
    ])
    
    return X, y


def remove_silver_duplicates(df_raw):
    df = df_raw.copy()

    if df.empty:
        return df

    df["scraped_at"] = pd.to_datetime(df["scraped_at"], errors="coerce")

    dedupe_columns = [
        "price_eur",
        "surface_m2",
        "price_per_m2",
        "arrondissement",
        "rooms",
        "longitude",
        "latitude"
    ]

    before_count = len(df)
    df = df.sort_values("scraped_at", ascending=False, na_position="last") # keep the latest
    df = df.drop_duplicates(subset=dedupe_columns, keep="first").reset_index(drop=True)
    removed_count = before_count - len(df)

    logger.info(f"Deduplication removed {removed_count} rows from silver_listings")
    return df


def train_and_evaluate(model, X, y):
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    
    # Cross-validation scores
    scores = cross_val_score(
        model,
        X,
        y,
        scoring="neg_root_mean_squared_error",
        cv=kf
    )
    
    cv_rmse = -scores.mean()
    cv_std = scores.std()
    
    logger.info(f"Cross-validation RMSE: {cv_rmse:.4f} ± {cv_std:.4f}")
    
    # Final training on full dataset
    model.fit(X, y)
    
    # In-sample metrics
    y_pred = model.predict(X)
    train_rmse = np.sqrt(mean_squared_error(y, y_pred))
    train_mae = mean_absolute_error(y, y_pred)
    train_r2 = r2_score(y, y_pred)
    
    logger.info(f"Training RMSE: {train_rmse:.4f}, MAE: {train_mae:.4f}, R²: {train_r2:.4f}")
    
    return model, {
        "cv_rmse": cv_rmse,
        "cv_std": cv_std,
        "train_rmse": train_rmse,
        "train_mae": train_mae,
        "train_r2": train_r2
    }


def save_model(model, metrics, num_features, cat_features):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = ARTIFACTS_DIR / f"lgb_model_{timestamp}.joblib"
    metadata_path = ARTIFACTS_DIR / "model_metadata.joblib"
    
    joblib.dump(model, model_path)
    logger.info(f"Model saved to {model_path}")
    
    metadata = {
        "timestamp": timestamp,
        "model_path": str(model_path),
        "num_features": num_features,
        "cat_features": cat_features,
        "metrics": metrics,
        "created_at": datetime.now().isoformat()
    }
    joblib.dump(metadata, metadata_path)
    logger.info(f"Metadata saved to {metadata_path}")
    
    latest_link = ARTIFACTS_DIR / "lgb_model_latest.joblib"
    if latest_link.exists():
        latest_link.unlink()
    latest_link.symlink_to(model_path)
    
    return str(model_path)


def log_training_run(conn, model_path, metrics, rows_used):
    cur = conn.cursor()
    try:
        cur.execute("""
                INSERT INTO model_runs 
                    (model_path, cv_rmse, train_rmse, train_mae, train_r2, rows_used, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
                model_path,
                float(metrics["cv_rmse"]),
                float(metrics["train_rmse"]),
                float(metrics["train_mae"]),
                float(metrics["train_r2"]),
                int(rows_used),
                "success"
        ))
        conn.commit()
        logger.info("Training run logged to database")
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to log training run: {e}", exc_info=True)
        raise
    finally:
        cur.close()


def train_model():
    logger.info("=" * 60)
    logger.info("Starting model training pipeline")
    logger.info("=" * 60)
    
    # Connect to database
    engine = create_engine(os.environ.get("DATABASE_URL"))
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    
    try:
        logger.info("Loading silver_listings from database...")
        df_silver = pd.read_sql("SELECT * FROM silver_listings;", engine)
        logger.info(f"Loaded {len(df_silver)} rows for training")

        df_silver = remove_silver_duplicates(df_silver)
        logger.info(f"{len(df_silver)} rows remaining after deduplication")
        
        if len(df_silver) < 100:
            logger.warning("Very few rows in silver_listings, training may not be stable")
        
        num_features, cat_features = get_features()
        
        logger.info("Preparing data...")
        X, y = prepare_data(df_silver)
        logger.info(f"Features shape: {X.shape}, Target shape: {y.shape}")
        
        logger.info("Building LightGBM pipeline...")
        model = build_lgb_pipeline(num_features, cat_features)
        
        logger.info("Training model with cross-validation...")
        model, metrics = train_and_evaluate(model, X, y)
        
        logger.info("Saving model artifact...")
        model_path = save_model(model, metrics, num_features, cat_features)
        
        logger.info("Logging training run to database...")
        log_training_run(conn, model_path, metrics, len(df_silver))
        
        logger.info("=" * 60)
        logger.info("Model training pipeline completed successfully!")
        logger.info(f"Model saved to: {model_path}")
        logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"Model training failed: {e}", exc_info=True)
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO model_runs (status, rows_used)
                VALUES (%s, %s)
            """, ("failed", 0))
            conn.commit()
        except Exception as db_error:
            logger.error(f"Failed to log failure to database: {db_error}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        train_model()
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        exit(1)
