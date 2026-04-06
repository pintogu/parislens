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

## Section 3 - API 

### 3.1 Endpoints
The API exposes three endpoints: 
| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Returns whether the API and model are operational |
| `/estimate` | POST | Takes an apartment profile and returns a predicted price in euros |
| `/arrondissements` | GET | Returns the gold daily dataset statistics |

### 3.2 Design decisions 

The API runs in its own container, separate from the pipeline and the model training. This ensures any part of the system can be restarted or updated independently. Model can be retrained without touching the API, and the API can be redeployed without re-running the pipeline. 

The model is loaded once when the API starts rather than on every request. Reloading it on each call would add latency that compounds quickly under any real usage. 

If the model file is missing at startup, for example because the pipeline has not run yet, the API still starts and returns a clear error on `/estimate` instead of refusing to start entirely. This way `/health` stays reachable and the dashboard can show "estimates currently unavailable" rather than going completely blank. 

Longitude and latitude default to central Paris when not provided. Since arrondissement is always required and carries most of the location signal in the model, this has minimal impact on the estimate. A more precise improvement would be to default to the center of the given arrondissement rather than a single central point. 

Logging follows the same approach as the pipeline: the Python's built-in logging module with timestamps on every request. 

The `/arrondissements` endpoint fetchs the data from "gold_daily_stats" directly to return live average prices per m² and number of listings per arrondissement per date.

### 3.3 Testing

We check three things: that `/health` responds and confirms the API is reachable, that `/estimate` returns a clear error when the model is not available rather than crashing. Tests run automatically on every push via GitHub Actions. 

### 3.4 Known limitations

- No authentication or rate limiting. Anyone can call the API and there is nothing stopping a caller from sending unlimited requests. In production this would be a cost and a reliability concern and thus both would need to be addressed before any public deployment. 
- The model file must be present at startup. If the pipeline has not run yet, `/estimate` will be unavailable until the model is generated. 

## Section 4 - Monitoring Dashboard 

### 4.1 Overview
The project now also includes a Streamlit dashboard that allows you to monitor the pipeline and the model running in 
the backround. It automatically connects to the backend database (PostgreSQL) to verify scraper runs and pings the 
'/health' endpoind of the API to check if it is responding succesfully. 

### 4.2 How to run
For simplicity of use, we created a start.sh script that starts the full stack and opens the dashboard automatically. 
**To use it, simply give the script permission to run:**
```bash
chmod +x start.sh
```
**Then run the script:**
```
./start.sh
```
Explanation of the script:

The `start.sh` script automates the entire setup process from scratch by executing the following steps in order:
1. **Environment Setup:** Automatically duplicates the `.env.example` file into `.env` to securely set up your database credentials.
2. **Container Orchestration:** Uses `docker-compose` to download, build, and run the Postgres database, API, Pipeline, and Dashboard in the background.
3. **Initial Scrape:** Waits for the database to boot, then forces the pipeline to scrape today's data so the dashboard isn't empty.
4. **Launch:** Automatically opens the Streamlit frontend in your default browser.

### 4.3 Running manually 

**Start the full stack:**
```bash
docker-compose up --build
```
This starts the API after the pipeline has run and the model is available. 
The API loads the model on startup and begins accepting requests at http://localhost:8000. 
Interactive documentation is available at http://localhost:8000/docs.

**Access the dashboard through your browser, by navigating to:**
```
http://localhost:8501
```

### 4.3 What it shows

#### **API health**
Shows the result from the '/health' endpoint to check it the data was ingested successfully 


#### **Plots**
1. Plot of average price per m² by arrondissement
2. Plot of number of listings by arrondissement

#### **Summary statistics**
1. Total number of listings for all arrondissements in the date range (depending on the filters)
2. Average price per m² for all arrondissements in the date range (depending on the filters)

#### **Filters**
The plots and summary statistics can be filtered by the filters shown in the left panel. These filters
apply to all plots plus stats. The filters are:
- Date range: we usually just had one day data so it was difficult to see how it would display with one month data
- Arrondissement: it is possible to select which arrondissements we want to gather data from
