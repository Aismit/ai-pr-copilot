# 🚀 GitHub PR Copilot Bot Setup Guide

A step-by-step guide to download, configure, and run the GitHub PR Copilot bot locally using Docker.

---

## 📦 Prerequisites

- [Docker](https://www.docker.com/products/docker-desktop/) installed and running
- Git installed
- Python 3.12 (optional, for local development without Docker)

---

## 📥 Downloading the Bot

Clone this repository to your local environment:

```bash
git clone <YOUR_REPO_URL>
cd ai-pr
```

---

## ⚙️ Configure Environment Variables

Create an `.env` file at the root of your cloned repo (`ai-pr/.env`) with the following keys:

```env
GITHUB_WEBHOOK_SECRET=<your-github-webhook-secret>
GITHUB_APP_ID=<your-github-app-id>
GITHUB_PRIVATE_KEY_PATH=./ai-pr-copilot-dev.2025-04-20.private-key.pem

OPENAI_API_KEY=<your-openai-api-key>
OPENAI_MODEL_NAME=gpt-4o
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

COSMOS_ENDPOINT=<your-cosmos-db-endpoint>
COSMOS_KEY=<your-cosmos-db-key>
COSMOS_DB_NAME=<your-cosmos-db-name>
COSMOS_GRAPH_CONTAINER=<your-cosmos-container-name>

GITHUB_REPO_OWNER=<your-github-username-or-org>
GITHUB_REPO_NAME=<your-repo-name>
```

Make sure your private key `.pem` file is placed in the `backend/app/` directory.

---

## 🐳 Docker Setup and Execution

### 1. Build the Docker Image
Navigate to the backend directory:

```bash
cd backend
```

Build the Docker image:

```bash
docker build -t ai-pr-copilot .
```

### 2. Run the Docker Container

Run the container, mapping port `8000`:

```bash
docker run -p 8000:8000 --env-file ../.env ai-pr-copilot
```

### 3. Verify the API

Navigate to your browser and verify the API is up:

```bash
http://localhost:8000/pr-summaries
```

You should see JSON data containing PR summaries.

---

## 💻 Running the Frontend

### Install dependencies

From the frontend directory:

```bash
cd frontend
npm install
```

### Update API URLs

In `frontend/src/App.tsx`, ensure your API endpoints point to your local backend:

```jsx
useEffect(() => {
  fetch('http://localhost:8000/pr-summaries')
    .then(res => res.json())
    .then(data => setPrSummaries(data))
    .catch(err => console.error(err));
}, []);
```

### Start the Frontend

Run your frontend application:

```bash
npm run dev
```

Navigate to `http://localhost:5173` in your browser to use the PR Copilot Dashboard.

---

## 🔧 Additional Configuration (Optional)

### Ngrok for Public URLs

If you need public URLs (for webhook testing):

1. Install [Ngrok](https://ngrok.com/)
2. Run:

```bash
ngrok http 8000
```

Copy the generated URL for webhook configuration on GitHub.

---

## 🧪 Testing the Integration

- Open or update a PR on your GitHub repository to trigger webhooks.
- Check the frontend dashboard for updates.
- Approve or reject PRs from the dashboard.

---

## 🎉 Congratulations!

Your GitHub PR Copilot Bot is now set up and running!

For troubleshooting, ensure:
- Your Docker containers are running correctly (`docker ps`).
- Your environment variables are set correctly.
- API endpoints are reachable.

