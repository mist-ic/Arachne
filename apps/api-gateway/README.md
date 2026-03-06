# API Gateway

FastAPI control plane — the single entry point for all client requests.

Submits jobs, starts Temporal workflows, serves job status and crawl history.

## Endpoints

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/jobs` | Submit a scrape job |
| `GET` | `/api/v1/jobs` | List all jobs |
| `GET` | `/api/v1/jobs/{id}` | Get job status |
| `GET` | `/api/v1/jobs/{id}/attempts` | Crawl attempt history |
| `DELETE` | `/api/v1/jobs/{id}` | Cancel a job |
| `GET` | `/api/v1/health` | Health check |
