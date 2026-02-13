# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Daily Dev Digest** — A Python tool that analyzes GitHub development activity daily and posts actionable insights (learning topics, related news, action items, project ideas) to a Notion database. Runs on GitHub Actions (8:00 JST daily).

## Architecture

```
GitHub API  →  fetch_github_activity()     dev activity (past 24h)
Notion API  →  query_notion_requests()     pending user requests
              query_notion_ratings()       past rating feedback
     ↓
Claude API  →  generate_digest()           AI analysis (Sonnet + web search)
     ↓
Notion API  →  post_to_notion()            create digest + individual items
     ↓
GitHub Actions  →  cron 23:00 UTC (08:00 JST)
```

Single-file architecture: `daily_digest.py` (9 functions)

Notion DB uses a single database with Type property (`digest`/`learning`/`news`/`action`/`idea`/`request`) to distinguish item kinds. Items link to their daily digest page via self-relation (`Parent Digest`). Users rate items (`Rating: ★1-★5`) to improve future suggestions.

Dependencies: `anthropic` (Claude API + web search), `requests` (GitHub + Notion HTTP calls)

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally (requires .env file with API keys)
cp .env.example .env   # then edit with your keys
export $(cat .env | xargs) && python daily_digest.py
```

## Required Environment Variables

- `ANTHROPIC_API_KEY` — Claude API key
- `NOTION_TOKEN` — Notion integration token
- `NOTION_DATABASE_ID` — Target Notion database ID
- `GITHUB_TOKEN` (optional) — GitHub PAT for higher rate limits
- `TARGET_GITHUB_USERNAME` — GitHub username to track (default: HayatoShimada)

## Language

Design docs and comments are in Japanese. Code and variable names are in English.
