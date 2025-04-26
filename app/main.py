from dotenv import load_dotenv
load_dotenv()

import os
import hmac
import hashlib
import json
import datetime
import time
import jwt  # PyJWT
from fastapi import FastAPI, Header, HTTPException, Request
from openai import AsyncOpenAI
from azure.cosmos.aio import CosmosClient
import httpx

# Initialize FastAPI app
app = FastAPI()

# Environment variables
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET").encode()
GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
GITHUB_PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-4o")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT")
COSMOS_KEY = os.getenv("COSMOS_KEY")
COSMOS_DB_NAME = os.getenv("COSMOS_DB_NAME")
COSMOS_GRAPH_CONTAINER = os.getenv("COSMOS_GRAPH_CONTAINER")

# OpenAI client
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# CosmosDB client
cosmos_client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
database = cosmos_client.get_database_client(COSMOS_DB_NAME)
graph_container = database.get_container_client(COSMOS_GRAPH_CONTAINER)

# Verify webhook signature
def verify(signature: str, body: bytes) -> bool:
    sha_name, sig = signature.split('=')
    mac = hmac.new(WEBHOOK_SECRET, msg=body, digestmod=hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), sig)

# Generate GitHub App JWT
def generate_jwt():
    with open(GITHUB_PRIVATE_KEY_PATH, "rb") as pem_file:
        private_key = pem_file.read()

    payload = {
        "iat": int(time.time()) - 60,
        "exp": int(time.time()) + (10 * 60),  # JWT valid for 10 mins
        "iss": GITHUB_APP_ID
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")
    return token

# Get GitHub App installation token
async def get_installation_access_token(owner, repo):
    jwt_token = generate_jwt()
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
    }
    async with httpx.AsyncClient() as client:
        # Fetch installation ID
        install_res = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/installation",
            headers=headers
        )
        install_res.raise_for_status()
        installation_id = install_res.json()["id"]

        # Get installation token
        token_res = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers=headers
        )
        token_res.raise_for_status()
        return token_res.json()["token"]

# Fetch PR diff from GitHub
async def fetch_pr_diff(owner, repo, pr_number):
    token = await get_installation_access_token(owner, repo)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(follow_redirects=True) as client:  # <-- add follow_redirects=True
        pr_res = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=headers
        )
        pr_res.raise_for_status()
        pr_data = pr_res.json()
        diff_url = pr_data["diff_url"]

        diff_res = await client.get(diff_url, headers=headers, follow_redirects=True)  # <-- here as well
        diff_res.raise_for_status()
        return diff_res.text

# Summarize PR diff via OpenAI
async def summarize_diff(diff):
    response = await openai_client.chat.completions.create(
        model=OPENAI_MODEL_NAME,
        messages=[
            {"role": "system", "content": "Summarize this Git diff concisely."},
            {"role": "user", "content": diff},
        ]
    )
    return response.choices[0].message.content

# Generate embeddings from summary via OpenAI
async def embed_summary(text):
    embedding = await openai_client.embeddings.create(
        input=text,
        model=OPENAI_EMBEDDING_MODEL
    )
    return embedding.data[0].embedding

# Store PR summary and embedding in CosmosDB
async def store_pr_summary(pr_id, summary, embedding):
    item = {
        "id": f"pr-{pr_id}",
        "pr_id": pr_id,
        "summary": summary,
        "embedding": embedding,
        "created_at": datetime.datetime.utcnow().isoformat()
    }
    await graph_container.upsert_item(item)

# Webhook endpoint
@app.post("/webhook")
async def github_webhook(request: Request, x_hub_signature_256: str = Header(None)):
    body = await request.body()

    if not verify(x_hub_signature_256, body):
        raise HTTPException(status_code=401, detail="Bad signature")

    payload = json.loads(body)
    action = payload.get("action")
    pr = payload.get("pull_request")

    if pr and action in ["opened", "synchronize"]:
        owner = pr["base"]["repo"]["owner"]["login"]
        repo = pr["base"]["repo"]["name"]
        pr_number = pr["number"]

        try:
            diff = await fetch_pr_diff(owner, repo, pr_number)
            summary = await summarize_diff(diff)
            embedding = await embed_summary(summary)
            await store_pr_summary(pr_number, summary, embedding)

            print(f"Processed and stored PR#{pr_number} successfully.")

        except Exception as e:
            print(f"Error processing PR#{pr_number}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok"}
