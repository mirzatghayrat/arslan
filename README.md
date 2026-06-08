# Arslan

An open-source Meta-Agent that helps non-technical users build domain-specific AI agents through conversation.

## Run with Docker

```bash
cp .env.example .env   # optionally set ARSLAN_API_TOKEN and ARSLAN_SECRET_KEY
docker compose up --build
```

Open http://localhost:8741. The API is under `/api/v1`, WebSocket endpoints under `/ws`.
