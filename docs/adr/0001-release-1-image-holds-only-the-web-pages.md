# ADR-0001: The Release 1 image holds only the web pages

- Status: Accepted
- Date: 2026-11-21
- Source: code comments, moved here by the comment clean-up

## Context

Release 1 puts the evaluation pages on Render. The agent needs model clients, keys and the local data folder. None of these may reach a public image.

## Decision

The Dockerfile builds only the web service. It installs the `web` dependency group from pyproject.toml and no other group. .dockerignore lets in only the files that the image needs, so `.env`, `data/` and `.venv` never reach the build context. The container reads Render's `PORT` through the shell form of `CMD`.

### Where this applies

Each entry gives the file, the symbol and the line of code that the reason was attached to. The reason under it is in its original words.

- `.dockerignore` › `*`
  - Send only what the image needs, so .env, data/ and .venv never reach a build.
- `Dockerfile` › `FROM python:3.12.13-slim-trixie AS build`
  - The Release 1 web pages only: no agent, no model client and no keys.
- `Dockerfile` › `CMD ["sh", "-c", "exec uvicorn fpl.web.app:app --host 0.0.0.0 --por...`
  - Render sets PORT; the shell form lets the command read it.
- `pyproject.toml` › `web = [`
  - Only what the web service needs; the Docker image installs this group without the agent.

## Consequences

- The deployed service has no agent features.
- A new runtime dependency of the web pages must go into the `web` group, or the image fails when it starts.
- A new file that the image needs must be added to .dockerignore as an exception.
