# ParisLens Property Price Estimator

ParisLens estimates apartment prices across Paris arrondissements
using real transaction data. Here we describe the process step by step, from the collection of raw data through to
the final model and the API.

---

## Section 1: Obtaining and Preparing the Data

### 1.1 Data Source

Our first approach was to scrape live listings from PAP.fr and
SeLoger using Playwright. Both sites are protected by Cloudflare,
which blocked automated access even with realistic browser headers
and randomised delays. 

We switched to the official **Demandes de Valeurs Foncières (DVF)**
dataset published by the French government:
[data.gouv.fr](https://www.data.gouv.fr/datasets/demandes-de-valeurs-foncieres).
It covers all property transactions in France and is updated
approximately once a year, around October.

The process always attempts to download the file for the current year
and, if it has not yet been published, automatically falls back to the previous year’s file,
thus avoiding manual updates.

### 1.2 What the data contains

Each row in the DVF dataset represents a real estate transaction.
The fields we use are:

| Field | Description |
|---|---|
| `valeur_fonciere` | Sale price in euros |
| `surface_reelle_bati` | Surface area in m² |
| `code_postal` | Postal code (used to derive arrondissement) |
| `date_mutation` | Transaction date |
| `type_local` | Property type (we keep Appartement only) |
| `nature_mutation` | Transaction type (we keep Vente only) |

### 1.3 Data we would like but don't have (so far)

The DVF is official and reliable, but it has gaps that limit
prediction accuracy. If we had access to richer data, we would
incorporate:

- **Current listing prices**: DVF only covers completed
  transactions, so there is always a lag of several months
- **Property condition** : renovated vs unrenovated flats in
  the same building can differ a lot in price
- **Floor level and elevator**: also significant price factor to take into account
- **DPE energy rating** : an increasingly important factor to bear in mind for the future 
- **Proximity to metro**: would require joining with RATP open data

### 1.4 Pipeline architecture

The pipeline follows an architecture with three layers:
```
DVF (data.gouv.fr)
       ↓
  download_and_load()   →  bronze_listings   (raw, unmodified)
       ↓
  bronze_to_silver()    →  silver_listings   (cleaned, validated)
       ↓
  silver_to_gold()      →  gold_daily_stats  (aggregated per arrondissement per day)
```

**Bronze** stores raw data as ingested with minimal transformation.
**Silver** cleans and validates, removing outliers, parsing fields,
flagging bad rows instead of dropping them directly.
**Gold** aggregates daily averages per arrondissement, which is what
our model and API will consume.

This separation means any layer can be reprocessed independently
without re downloading from the source.

### 1.5 Filters applied

- Apartment sales only
- Surface between 10m² and 500m²
- Price per m² between €3,000 and €40,000
- Duplicates removed per mutation ID

### 1.6 Scheduling

The process runs daily at 3:00 a.m. via a cron job within the Docker container.
The dataset is updated infrequently (once a year, as far as we can tell), so the daily runs serve more to
demonstrate the programming patterns than to collect new data.

Each run is logged in the `scraper_runs` table with its status
and the number of rows added; this is the first place we would look if
something appears to be wrong.

**Known limitations of this approach in production:**

- If the job crashes, nothing sends an alert. You need to check
  the logs or the `scraper_runs` table actively
- If the container is down at 3am the run is simply skipped,
  with no catch-up
- The crontab lives inside the container so if the container is
  rebuilt, the schedule resets. A dedicated scheduler like Airflow
  or Prefect would be more robust at scale, but so far we do not think is needed

### 1.7 Logging

All components of the automation process send logs both to the console and to a file called
`pipeline.log`, which is periodically rotated, using Python’s built-in `logging` module.
The logs are rotated once they reach 5 MB, with the last three files retained, to prevent
unlimited disk usage on a server running continuously.

A single module, `logger.py`, centralises this configuration, so that
all scripts in the automation process share the same format and behaviour.

### 1.8 How to run

**Start the full stack:**
```bash
docker-compose up --build
```
This starts PostgreSQL, creates the tables, runs the pipeline
once immediately, then hands off to cron.

**Run the pipeline manually:**
```bash
python src/pipeline/run_pipeline.py
```

**Environment variables**: copy `.env.example` to `.env` and
fill in your `DATABASE_URL`. Never commit `.env` to the repository.

### 1.9 Outputs of the data pipeline

At the end of the data pipeline, the following is available and ready
for the model and API to consume:

**`gold_daily_stats` table** wuth one row per arrondissement per day,
containing:

| Column | Description |
|---|---|
| `arrondissement` | Paris postal code (e.g. 75011) |
| `date` | Date of aggregation |
| `avg_price_per_m2` | Average price per m² for that day |
| `listing_count` | Number of transactions used to compute the average |
| `computed_at` | Timestamp of when the row was last updated |

This is the main table the model will train on and the API will query.

**`silver_listings` table** shows individual cleaned transactions, one
row per apartment sale. This is richer than gold and useful if the
model needs transaction-level features rather than aggregates.

**`scraper_runs` table** contains pipeline run history, useful for
monitoring and debugging.

All tables live in the PostgreSQL instance defined in
`docker-compose.yml`. To connect locally:
```bash
psql postgresql://admin:password@localhost:5432/parislens
```

---

## Section 2 — Price Prediction Model

### 2.1. Data used
For the price prediction modeling, we decided to use the silver dataset, as it had the cleanest features by listing. 


### 2.2. Model selection
As the modeling part is not the core of this project, we decided to try out two models (a simple Ridge regression and a LightGBM) and keep the one with better RMSE, which resulted to be the LightGBM one.

| Model    | RMSE   | Std Dev   |
|----------|--------|-----------|
| Ridge    | 0.3683 | ± 0.0101  |
| LightGBM | 0.2821 | ± 0.0090  |

## 2.3. Model requirements
Once we had a model, we had to figure out how to make it available for the API to consume in the next step. To do so, we created a train_model.py module that runs the model, evaluates it and then saves it as a joblib artifact, so the API endpoint that we create in the next step can access it and get a prediction, by providing the necessary features.

#### **Required Features**
- `surface_m2`  
- `rooms`  
- `longitude`  
- `latitude`  
- `arrondissement`  

#### **Optional Features**
If they are not provided, the current date will be extracted:
- `month`  
- `year`  

#### **Output**
- The model returns the **log of the price**
- To make it readable:

```python
price = exp(prediction)
```

#### **Artifact location**

```python
/app/model_artifacts/lgb_model_latest.joblib
```

## 2.4. Retraining pipeline
To make it more similar as to how it should work in a production environment, we decided to create a pipeline that generates the model artifact instead of just creating a model once. This pipeline has a cron job just like the data extraction one, but it runs once monthly. That way we get an updated version of the model in case the data has also been updated. 

### Current Behavior
- Evaluation metrics are printed
- Logs are saved in the database to review the metrics generated for the retrained versions of the model

### Future Work
- Add a layer that monitors the metrics and decides whether or not the new model is worth deploying, so as to not degrade performance unknowingly
- Trigger alerts in case:
  - performance degrades too much
  - the data used by the model from more recent periods is too different from the oldest one
- Decide whether it would be better to use a certain window of data to train and monitor drift

### 2.5. How to run

Just like with the data extraction pipeline, now we have a new command in the Dockerfile that trigger the training. So the same commands apply:

**Start the full stack:**
```bash
docker-compose up --build
```
After the data extraction, it runs the pipeline once immediately, and then hands off to cron.

**Run the pipeline manually:**
```bash
python src/model/train_model.py
```

*Section 3 — API (coming)*
