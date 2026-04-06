#Initiates the whole infastructure , more on README.
echo "Initiating Parislens Infastructure..."

#Create an env file as long as it doesn't exist yet.
if [ ! -f .env ]; then 
    echo "Creating new env. file..."
    cp .env.example .env  
fi 

#Initiate the docker containers, instead of running the command manually
echo "Initiating Docker containers...."
docker-compose up --build -d 

#Database must wake up first before the next scrape 
echo "Timeout for the database to start..."
sleep 7 

#Initiate first scrape 
echo "Initiating first scrape..."
docker-compose exec pipeline python src/pipeline/run_pipeline.py

#Open the dashboard;
echo "Opening dashboard..."
open http://localhost:8501 