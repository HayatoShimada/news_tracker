import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import anthropic
import requests

# --- Configuration ---

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
TARGET_GITHUB_USERNAME = os.environ.get("TARGET_GITHUB_USERNAME", "HayatoShimada")

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime("%Y-%m-%d")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

# --- Claude system prompt ---

SYSTEM_PROMPT = """\
You are a personal development assistant that creates a daily digest for a software developer.
Analyze the developer's recent GitHub activity, answer their pending requests,
and provide actionable suggestions.

## Output Format

Respond with a single JSON code block (```json ... ```) containing exactly this structure:

{
  "digest_summary": "3-5 paragraph summary in Japanese of today's development situation and recommendations.",
  "learning": [
    {"title": "学習テーマ", "description": "1-2文の説明", "tags": ["tag1", "tag2"]}
  ],
  "news": [
    {"title": "ニュース見出し", "description": "1-2文の要約（ソースURL付き）", "tags": ["tag1"]}
  ],
  "action": [
    {"title": "アクション", "description": "具体的な内容", "priority": "High|Medium|Low", "tags": ["tag1"]}
  ],
  "idea": [
    {"title": "アイデア", "description": "概要と価値", "tags": ["tag1"]}
  ],
  "request_answers": [
    {"request_id": "page-id", "answer_summary": "回答の要約"}
  ]
}

## Constraints

- learning: exactly 3 items. Directly relevant to the developer's current projects.
- news: exactly 3 items. Use web search to find real, current tech news. Include actual URLs. Do NOT fabricate.
- action: 3 to 5 items. Each must have a priority. Concrete and achievable today.
- idea: 1 to 2 items.
- request_answers: one entry per pending request. Empty array if no requests.
- All text content in Japanese. Tags in lowercase English.

## Rating Feedback

The developer rates past suggestions (★1-5).
- Increase suggestions similar to ★4-5 items.
- Decrease or avoid suggestions similar to ★1-2 items.

## Web Search

Use web search to find:
1. Real, current tech news relevant to the developer's activity.
2. Information to answer pending requests.
"""


# --- GitHub ---


def fetch_github_activity(username: str) -> str:
    """Fetch recent GitHub activity and return a human-readable summary."""
    try:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

        resp = requests.get(
            f"https://api.github.com/users/{username}/events/public",
            headers=headers,
            params={"per_page": 100},
            timeout=30,
        )
        resp.raise_for_status()
        events = resp.json()

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        lines = []

        for event in events:
            created_at = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
            if created_at < cutoff:
                continue

            repo = event.get("repo", {}).get("name", "unknown")
            etype = event["type"]
            payload = event.get("payload", {})

            if etype == "PushEvent":
                commits = payload.get("commits", [])
                msgs = [c["message"].split("\n")[0] for c in commits[:3]]
                lines.append(f"- Push to {repo}: {len(commits)} commit(s) — {', '.join(msgs)}")
            elif etype == "PullRequestEvent":
                pr = payload.get("pull_request", {})
                lines.append(f"- PR {payload.get('action', '')}: {pr.get('title', '')} ({repo})")
            elif etype == "IssuesEvent":
                issue = payload.get("issue", {})
                lines.append(f"- Issue {payload.get('action', '')}: {issue.get('title', '')} ({repo})")
            elif etype == "CreateEvent":
                ref_type = payload.get("ref_type", "")
                ref = payload.get("ref", "")
                lines.append(f"- Created {ref_type} {ref} in {repo}")
            elif etype in ("WatchEvent", "ForkEvent"):
                lines.append(f"- {etype.replace('Event', '')}: {repo}")
            else:
                lines.append(f"- {etype}: {repo}")

        if not lines:
            return "No GitHub activity in the last 24 hours."

        return "\n".join(lines)

    except Exception as e:
        logger.warning("Failed to fetch GitHub activity: %s", e)
        return "GitHub activity could not be retrieved."


# --- Notion read ---


def _notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def query_notion_requests() -> list[dict]:
    """Fetch pending request items (Type=request, Status=Not Started) from Notion."""
    try:
        body = {
            "filter": {
                "and": [
                    {"property": "Type", "multi_select": {"contains": "request"}},
                    {"property": "Status", "status": {"equals": "Not Started"}},
                ]
            }
        }
        results = []
        has_more = True
        start_cursor = None

        while has_more:
            if start_cursor:
                body["start_cursor"] = start_cursor
            resp = requests.post(
                f"{NOTION_BASE_URL}/databases/{NOTION_DATABASE_ID}/query",
                headers=_notion_headers(),
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            for page in data.get("results", []):
                title_prop = page.get("properties", {}).get("Title", {}).get("title", [])
                title = title_prop[0]["plain_text"] if title_prop else ""
                date_prop = page.get("properties", {}).get("Date", {}).get("date")
                date = date_prop["start"] if date_prop else ""
                results.append({"id": page["id"], "title": title, "date": date})

            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

        return results

    except Exception as e:
        logger.warning("Failed to query Notion requests: %s", e)
        return []


def query_notion_ratings() -> str:
    """Analyze past ratings to determine user preferences."""
    try:
        body = {
            "filter": {
                "and": [
                    {"property": "Rating", "multi_select": {"is_not_empty": True}},
                    {"property": "Source", "multi_select": {"contains": "claude"}},
                ]
            },
            "sorts": [{"property": "Date", "direction": "descending"}],
            "page_size": 50,
        }
        resp = requests.post(
            f"{NOTION_BASE_URL}/databases/{NOTION_DATABASE_ID}/query",
            headers=_notion_headers(),
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("results", [])

        if not pages:
            return "No rating feedback available yet."

        # Analyze rating distribution and tag preferences
        rating_counts = defaultdict(int)
        tag_ratings = defaultdict(list)

        for page in pages:
            props = page.get("properties", {})
            rating_sel = props.get("Rating", {}).get("multi_select", [])
            rating_name = rating_sel[0]["name"] if rating_sel else ""
            if not rating_name:
                continue
            # Extract numeric rating from "★3" format
            stars = int(rating_name.replace("★", ""))
            rating_counts[stars] += 1

            tags = [t["name"] for t in props.get("Tags", {}).get("multi_select", [])]
            for tag in tags:
                tag_ratings[tag].append(stars)

        total = sum(rating_counts.values())
        avg = sum(k * v for k, v in rating_counts.items()) / total if total else 0

        lines = [f"Overall: {avg:.1f}/5 ({total} rated items)"]

        # Find high and low rated tags
        for tag, ratings in sorted(tag_ratings.items()):
            tag_avg = sum(ratings) / len(ratings)
            if tag_avg >= 4.0:
                lines.append(f"  Highly rated: '{tag}' (avg {tag_avg:.1f})")
            elif tag_avg <= 2.0:
                lines.append(f"  Poorly rated: '{tag}' (avg {tag_avg:.1f})")

        return "\n".join(lines)

    except Exception as e:
        logger.warning("Failed to query Notion ratings: %s", e)
        return "No rating feedback available yet."


# --- Claude API ---


def extract_json_from_response(response) -> dict:
    """Extract JSON from Claude's response content blocks."""
    text_parts = []
    for block in response.content:
        if hasattr(block, "text"):
            text_parts.append(block.text)
    full_text = "".join(text_parts)

    match = re.search(r"```json\s*(.*?)\s*```", full_text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON code block found in response: {full_text[:500]}")
    return json.loads(match.group(1))


def generate_digest(
    github_activity: str,
    pending_requests: list[dict],
    rating_feedback: str,
) -> dict:
    """Call Claude API with web search to generate digest content."""
    client = anthropic.Anthropic()

    # Build user message
    parts = [f"## Today's GitHub Activity\n{github_activity}"]

    if pending_requests:
        req_lines = [f"- [{r['title']}] (id: {r['id']})" for r in pending_requests]
        parts.append(f"## Pending Requests\n" + "\n".join(req_lines))
    else:
        parts.append("## Pending Requests\nNo pending requests.")

    parts.append(f"## Rating Feedback\n{rating_feedback}")

    user_message = "\n\n".join(parts)

    # Call Claude with web search
    messages = [{"role": "user", "content": user_message}]

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        messages=messages,
    )

    # Handle pause_turn (partial response that needs continuation)
    while response.stop_reason == "pause_turn":
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": "Please continue."})
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=messages,
        )

    return extract_json_from_response(response)


# --- Notion write ---


def build_notion_properties(
    title: str,
    item_type: str,
    priority: str | None = None,
    tags: list[str] | None = None,
    parent_digest_id: str | None = None,
) -> dict:
    """Build Notion page properties dict from item data."""
    props = {
        "Title": {"title": [{"text": {"content": title}}]},
        "Type": {"multi_select": [{"name": item_type}]},
        "Status": {"status": {"name": "Not Started"}},
        "Date": {"date": {"start": TODAY}},
        "Source": {"multi_select": [{"name": "claude"}]},
    }
    if priority:
        props["Priority"] = {"multi_select": [{"name": priority}]}
    if tags:
        props["Tags"] = {"multi_select": [{"name": t} for t in tags]}
    if parent_digest_id:
        props["Parent Digest"] = {"relation": [{"id": parent_digest_id}]}
    return props


def create_notion_page(
    properties: dict, children: list[dict] | None = None
) -> str:
    """Create a page in the Notion database. Returns the page ID."""
    body: dict = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
    }
    if children:
        body["children"] = children

    resp = requests.post(
        f"{NOTION_BASE_URL}/pages",
        headers=_notion_headers(),
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def update_notion_page_status(page_id: str, status: str) -> None:
    """Update the Status property of a Notion page."""
    resp = requests.patch(
        f"{NOTION_BASE_URL}/pages/{page_id}",
        headers=_notion_headers(),
        json={"properties": {"Status": {"status": {"name": status}}}},
        timeout=30,
    )
    resp.raise_for_status()


def _text_to_notion_blocks(text: str) -> list[dict]:
    """Convert a text string into Notion paragraph blocks."""
    blocks = []
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": paragraph}}]
                },
            }
        )
    return blocks


def post_to_notion(digest_data: dict, pending_requests: list[dict]) -> None:
    """Create all Notion pages for the digest and update request statuses."""
    # 1. Create digest page
    digest_props = build_notion_properties(f"{TODAY} Daily Digest", "digest")
    digest_children = _text_to_notion_blocks(digest_data["digest_summary"])
    digest_page_id = create_notion_page(digest_props, digest_children)
    logger.info("Created digest page: %s", digest_page_id)

    # 2. Create individual items
    item_count = 0
    for item_type in ("learning", "news", "action", "idea"):
        for item in digest_data.get(item_type, []):
            props = build_notion_properties(
                title=item["title"],
                item_type=item_type,
                priority=item.get("priority"),
                tags=item.get("tags"),
                parent_digest_id=digest_page_id,
            )
            # Add description as page body
            children = _text_to_notion_blocks(item.get("description", ""))
            create_notion_page(props, children)
            item_count += 1

    logger.info("Created %d individual items", item_count)

    # 3. Update answered requests
    for answer in digest_data.get("request_answers", []):
        request_id = answer.get("request_id", "")
        if request_id:
            update_notion_page_status(request_id, "Done")
            logger.info("Marked request %s as Done", request_id)


# --- Main ---


def main():
    logger.info("Starting Daily Dev Digest for %s", TODAY)

    github_activity = fetch_github_activity(TARGET_GITHUB_USERNAME)
    logger.info("GitHub activity fetched")

    pending_requests = query_notion_requests()
    logger.info("Found %d pending requests", len(pending_requests))

    rating_feedback = query_notion_ratings()
    logger.info("Rating feedback analyzed")

    digest_data = generate_digest(github_activity, pending_requests, rating_feedback)
    logger.info("Digest generated by Claude")

    post_to_notion(digest_data, pending_requests)
    logger.info("Daily Dev Digest completed successfully")


if __name__ == "__main__":
    main()
