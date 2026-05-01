# Claude Instructions for Oceans of NYC

## Python environment
The project's python environment is managed with uv. 
Use `uv run python ...` to execute python commands

## Database Schema

Before making any changes involving the database (models, migrations, queries), use the Neon MCP to check the current schema:

- Use the `neon` MCP tools to inspect table structures, columns, and relationships
- The primary project is `oceans-of-nyc` (or similar) on Neon — list projects to find it
- Always verify the live schema matches `database/models.py` before writing migrations or queries
- Use `describe_table_schema` or equivalent MCP tools to get column types, constraints, and foreign keys

## Project Overview

- Python/FastAPI backend with SQLAlchemy models in `database/models.py`
- PostgreSQL database hosted on Neon
