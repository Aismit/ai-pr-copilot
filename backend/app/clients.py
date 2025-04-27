import os
from dotenv import load_dotenv
from openai import AsyncOpenAI
from azure.cosmos.aio import CosmosClient

load_dotenv()

openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

cosmos_client = CosmosClient(
    os.getenv("COSMOS_ENDPOINT"), 
    credential=os.getenv("COSMOS_KEY")
)

database = cosmos_client.get_database_client(os.getenv("COSMOS_DB_NAME"))
graph_container = database.get_container_client(os.getenv("COSMOS_GRAPH_CONTAINER"))
comments_container = database.get_container_client(os.getenv("COSMOS_COMMENTS_CONTAINER"))