from dotenv import load_dotenv
load_dotenv()

import os
import hmac
import hashlib
import json
import datetime
import time
import jwt
from fastapi import FastAPI, Header, HTTPException, Request
from openai import AsyncOpenAI
from azure.cosmos.aio import CosmosClient
import httpx
from github import GithubIntegration
from fastapi.middleware.cors import CORSMiddleware
import uuid 

app = FastAPI()

origins = [
    "http://localhost:5173",
    "https://62ef-76-132-154-233.ngrok-free.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME")
COSMOS_COMMENTS_CONTAINER = os.getenv("COSMOS_COMMENTS_CONTAINER")
COSMOS_CHECK_RESULTS_CONTAINER = os.getenv("COSMOS_CHECK_RESULTS_CONTAINER")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
cosmos_client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
database = cosmos_client.get_database_client(COSMOS_DB_NAME)
graph_container = database.get_container_client(COSMOS_GRAPH_CONTAINER)
comments_container = database.get_container_client(COSMOS_COMMENTS_CONTAINER)
check_results_container = database.get_container_client(COSMOS_CHECK_RESULTS_CONTAINER)

def verify(signature: str, body: bytes) -> bool:
    sha_name, sig = signature.split('=')
    mac = hmac.new(WEBHOOK_SECRET, msg=body, digestmod=hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), sig)

@app.get("/pr-summaries")
async def get_pr_summaries():
    client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
    try:
        database = client.get_database_client(COSMOS_DB_NAME)
        container = database.get_container_client(COSMOS_GRAPH_CONTAINER)

        summaries = []
        async for item in container.query_items(
            query="SELECT c.pr_id, c.summary FROM c"
        ):
            summaries.append(item)
        
        return summaries
    finally:
        await client.close()

def generate_jwt():
    with open(GITHUB_PRIVATE_KEY_PATH, "rb") as pem_file:
        private_key = pem_file.read()
    payload = {"iat": int(time.time()) - 60, "exp": int(time.time()) + 600, "iss": GITHUB_APP_ID}
    return jwt.encode(payload, private_key, algorithm="RS256")

async def get_installation_access_token(owner, repo):
    jwt_token = generate_jwt()
    headers = {"Authorization": f"Bearer {jwt_token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient() as client:
        install_res = await client.get(f"https://api.github.com/repos/{owner}/{repo}/installation", headers=headers)
        install_res.raise_for_status()
        installation_id = install_res.json()["id"]
        token_res = await client.post(f"https://api.github.com/app/installations/{installation_id}/access_tokens", headers=headers)
        token_res.raise_for_status()
        return token_res.json()["token"]

async def fetch_pr_diff(owner, repo, pr_number):
    token = await get_installation_access_token(owner, repo)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        pr_res = await client.get(f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}", headers=headers)
        pr_res.raise_for_status()
        diff_url = pr_res.json()["diff_url"]
        diff_res = await client.get(diff_url, headers=headers)
        diff_res.raise_for_status()
        return diff_res.text

async def summarize_diff(diff):
    response = await openai_client.chat.completions.create(
        model=OPENAI_MODEL_NAME,
        messages=[
            {"role": "system", "content": "Summarize this Git diff concisely."},
            {"role": "user", "content": diff},
        ]
    )
    return response.choices[0].message.content

async def embed_summary(text):
    embedding = await openai_client.embeddings.create(input=text, model=OPENAI_EMBEDDING_MODEL)
    return embedding.data[0].embedding

async def store_pr_summary(pr_id, summary, embedding):
    item = {"id": f"pr-{pr_id}", "pr_id": pr_id, "summary": summary, "embedding": embedding, "created_at": datetime.datetime.utcnow().isoformat()}
    await graph_container.upsert_item(item)

@app.post("/store-comment")
async def store_review_comment(comment: str):
    new_comment = {
        "id": str(uuid.uuid4()),
        "comment": comment,
        "created_at": datetime.datetime.utcnow().isoformat()
    }
    await comments_container.create_item(new_comment)
    return {"status": "stored comment successfully"}

@app.get("/review-comments")
async def get_review_comments():
    comments = []
    async for item in comments_container.query_items(
        "SELECT c.comment FROM c WHERE IS_DEFINED(c.comment)"):
        comments.append(item["comment"])
    return comments

async def analyze_pr_against_comments(diff):
    comments = []
    async for item in comments_container.query_items(
        "SELECT c.comment FROM c WHERE IS_DEFINED(c.comment)"
    ):
        comments.append(item["comment"])

    prompt_context = "\n".join(comments)
    print("Prompt context:\n", prompt_context)

    response = await openai_client.chat.completions.create(
        model=OPENAI_MODEL_NAME,
        messages=[
            {"role": "system", "content": f"You are reviewing code changes against the following rules:\n{prompt_context}\nClearly list any violations along with explanations."},
            {"role": "user", "content": diff},
        ]
    )
    analysis = response.choices[0].message.content
    return analysis

async def analyze_check_failure(diff, check_logs, check_name, openai_client, OPENAI_MODEL_NAME):
    prompt_content = f"""
Given the following code diff:

```diff
{diff}
```

And the logs from the failing GitHub Action check '{check_name}':

```
{check_logs}
```

Analyze both carefully, explain the exact reason for the check failure, and suggest clear and specific changes to fix the problem. Mention line numbers from the provided diff when relevant.

Your explanation should include:
1. The specific issue identified from the check logs.
2. A detailed explanation relating the logs to the diff.
3. Actionable recommendations for how the issue can be resolved directly in the code, including exact line numbers if applicable.

Ensure your response is clear, precise, and immediately actionable for the developer.
"""

    response = await openai_client.chat.completions.create(
        model=OPENAI_MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are an expert code reviewer and CI troubleshooting assistant."},
            {"role": "user", "content": prompt_content}
        ]
    )

    return response.choices[0].message.content

async def handle_check_failure(pr_number, failing_sha, check_run):
    token = await get_installation_access_token(GITHUB_REPO_OWNER, GITHUB_REPO_NAME)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    async with httpx.AsyncClient() as client:
        check_run_res = await client.get(
            f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/check-runs/{check_run['id']}",
            headers=headers
        )
        check_run_res.raise_for_status()
        check_run_data = check_run_res.json()

        check_output = check_run_data.get('output', {})
        full_logs = f"{check_output.get('summary', '')}\n\n{check_output.get('text', '')}"

        commits_res = await client.get(
            f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/pulls/{pr_number}/commits",
            headers=headers
        )
        commits_res.raise_for_status()
        commits = commits_res.json()

        successful_sha = None
        for commit in reversed(commits):
            commit_sha = commit["sha"]
            query = f"SELECT * FROM c WHERE c.commit_sha = '{commit_sha}' AND c.conclusion = 'success'"
            items = [item async for item in check_results_container.query_items(query)]
            if items:
                successful_sha = commit_sha
                break

        if successful_sha:
            diff_url = f"https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/compare/{successful_sha}...{failing_sha}"
        else:
            base_branch = (await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/pulls/{pr_number}",
                headers=headers
            )).json()["base"]["ref"]
            diff_url = f"https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/compare/{base_branch}...{failing_sha}"

        diff_res = await client.get(diff_url + ".diff", headers=headers)
        diff_res.raise_for_status()
        diff_content = diff_res.text

        analysis = await analyze_check_failure(diff_content, full_logs, check_run["name"])

        message = f"""
🚨 **CI Check Failure**: {check_run["name"]}

A recent commit (`{failing_sha[:7]}`) introduced failures in your CI checks.

### Analysis and Suggested Fixes:
{analysis}

Please carefully review [this diff]({diff_url}) and the [full check details here]({check_run["html_url"]}) to resolve the issue.
"""

        review_res = await client.post(
            f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/pulls/{pr_number}/reviews",
            json={"event": "REQUEST_CHANGES", "body": message},
            headers=headers
        )
        review_res.raise_for_status()

@app.post("/webhook")
async def github_webhook(request: Request, x_hub_signature_256: str = Header(None)):
    body = await request.body()
    if not verify(x_hub_signature_256, body):
        raise HTTPException(status_code=401, detail="Bad signature")

    payload = json.loads(body)
    event_type = request.headers.get("X-GitHub-Event")

    if event_type == "check_run":
        check_run = payload.get("check_run", {})
        conclusion = check_run.get("conclusion")
        commit_sha = check_run.get("head_sha")
        pr_numbers = [pr["number"] for pr in check_run.get("pull_requests", [])]

        for pr_number in pr_numbers:
            item = {
                "id": str(uuid.uuid4()),
                "check_run_id": check_run["id"],
                "check_name": check_run["name"],
                "status": check_run["status"],
                "conclusion": conclusion,
                "commit_sha": commit_sha,
                "pr_number": pr_number,
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "details_url": check_run["html_url"]
            }
            await check_results_container.upsert_item(item)

            if conclusion == "failure":
                await handle_check_failure(pr_number, commit_sha, check_run)

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
            analysis = await analyze_pr_against_comments(diff)

            if "violation" in analysis.lower() or "too long" in analysis.lower():
                token = await get_installation_access_token(owner, repo)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json"
                }
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                        json={"event": "REQUEST_CHANGES", "body": analysis},
                        headers=headers
                    )
                    response.raise_for_status()

                status = "Rejected PR due to violations"
            else:
                status = "No violations detected"

            return {
                "status": status,
                "analysis": analysis,
                "summary": summary
            }

        except Exception as e:
            print(f"Error processing PR#{pr_number}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok"}


@app.post("/pr/{pr_id}/approve")
async def approve_pr(pr_id: int):
    token = await get_installation_access_token(GITHUB_REPO_OWNER, GITHUB_REPO_NAME)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/pulls/{pr_id}/reviews",
            json={"event": "APPROVE"},
            headers=headers
        )
    return {"status": f"Approved PR #{pr_id}"}

@app.post("/pr/{pr_id}/reject")
async def reject_pr(pr_id: int):
    token = await get_installation_access_token(GITHUB_REPO_OWNER, GITHUB_REPO_NAME)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/pulls/{pr_id}/reviews",
            json={"event": "REQUEST_CHANGES", "body": "Changes needed."},
            headers=headers
        )
    return {"status": f"Rejected PR #{pr_id}"}