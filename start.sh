#!/bin/sh
set -eu

echo "Initiating Parislens Infrastructure..."

# Create .env if it doesn't exist
if [ ! -f .env ]; then 
  echo "Creating new .env file..."
  cp .env.example .env  
fi 

echo "Starting Docker containers..."
docker compose up --build -d 

echo "Opening dashboard..."
open http://localhost:8501