# Contributing / Local Setup

## Prerequisites

- Docker & Docker Compose
- Node.js 18+ (for frontend development outside Docker)
- Python 3.11+ (for backend development outside Docker)

## Quick Start

1. **Clone the repo:**
   ```bash
   git clone <repo-url>
   cd investing_companion
   ```

2. **Create your environment file:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your local settings. See the file for required variables.

3. **Start all services:**
   ```bash
   docker compose up -d
   ```

4. **Run database migrations:**
   ```bash
   docker compose exec api alembic upgrade head
   ```

5. **Seed demo data (optional):**
   ```bash
   docker compose exec api python -m scripts.seed_demo_data
   ```

6. **Access the app:**
   - Frontend: http://localhost:3000
   - API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

## Development Without Docker

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Running Tests

```bash
# Backend (requires a running test database)
cd backend && pytest --cov=app

# Frontend
cd frontend && npm test
```

## Code Style

- **Python**: Type hints everywhere, Pydantic schemas, async I/O, service layer pattern
- **TypeScript**: Strict mode, functional components, TanStack Query for server state
- **Commits**: Conventional commits (`feat:`, `fix:`, `docs:`, etc.)

## Deploying to Your Own NAS

See [docs/deployment/SYNOLOGY.md](./deployment/SYNOLOGY.md) for a full Synology NAS deployment guide. The general steps:

1. Configure SSH access to your NAS
2. Copy `.env.production.example` to `.env.production` on the NAS and fill in your values
3. Use `scripts/deploy-synology.sh` or deploy manually with `docker-compose`

## Claude Code Agents

This project includes Claude Code agent configurations in `.claude/agents/` (gitignored). If you use Claude Code, you can create your own agent configs there. See the [Claude Code docs](https://docs.anthropic.com/en/docs/claude-code) for details.

## Project Structure

See [CLAUDE.md](../CLAUDE.md) at the repo root for a full overview of the directory structure, tech stack, and conventions.
