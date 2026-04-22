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

#Open the dashboard;
echo "Opening dashboard..."
open http://localhost:8501 