import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import anthropic
import requests

# --- Configuration ---

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
TARGET_GITHUB_USERNAME = os.environ.get("TARGET_GITHUB_USERNAME", "HayatoShimada")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
NOTION_LOG_DATABASE_ID = os.environ.get("NOTION_LOG_DATABASE_ID", "")

missing_vars = []
if not ANTHROPIC_API_KEY:
    missing_vars.append("ANTHROPIC_API_KEY")
if not NOTION_TOKEN:
    missing_vars.append("NOTION_TOKEN")
if not NOTION_DATABASE_ID:
    missing_vars.append("NOTION_DATABASE_ID")

if missing_vars:
    raise ValueError(f"Required environment variables are missing or empty: {', '.join(missing_vars)}")

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime("%Y-%m-%d")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

# --- Prompt ---

def load_system_prompt() -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), "prompt.md")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("prompt.md not found. Using fallback prompt.")
        return "You are a personal development assistant."

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

    match = re.search(r"```json\s*(.*?)(?:\s*```|$)", full_text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON code block found in response: {full_text[:500]}")
    
    json_str = match.group(1).strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # If it's cut off, try basic repairing or just fail with better precision
        raise ValueError(f"Failed to parse JSON (maybe truncated?). Error: {e}\nRaw JSON: {json_str[:500]}...")


def generate_digest(
    github_activity: str,
    pending_requests: list[dict],
    rating_feedback: str,
    system_prompt: str,
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
        max_tokens=8192,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        messages=messages,
    )

    # Handle pause_turn (partial response that needs continuation)
    while response.stop_reason in ("pause_turn", "max_tokens"):
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": "Please continue."})
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=8192,
            system=system_prompt,
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


def post_to_notion(digest_data: dict, pending_requests: list[dict]) -> str:
    """Create all Notion pages for the digest and update request statuses. Returns digest page ID."""
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
            
    return digest_page_id


# --- Logging and Notifications ---


def log_execution(status: str, duration_sec: float, digest_id: str | None = None) -> None:
    """Log the execution status to the Notion log database."""
    if not NOTION_LOG_DATABASE_ID:
        return
        
    try:
        props = {
            "Title": {"title": [{"text": {"content": f"Execution {TODAY}"}}]},
            "Status": {"status": {"name": status}},
            "Duration": {"number": round(duration_sec, 2)},
            "Date": {"date": {"start": TODAY}},
        }
        if digest_id:
            props["Digest"] = {"relation": [{"id": digest_id}]}

        body = {
            "parent": {"database_id": NOTION_LOG_DATABASE_ID},
            "properties": props,
        }

        resp = requests.post(
            f"{NOTION_BASE_URL}/pages",
            headers=_notion_headers(),
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        logger.info("Execution logged successfully.")
    except requests.exceptions.HTTPError as e:
        logger.warning(f"Failed to log execution HTTPError: {e.response.text}")
    except Exception as e:
        logger.warning("Failed to log execution: %s", e)


def send_webhook_notification(digest_url: str) -> None:
    """Send a notification to the configured webhook (e.g., Discord or Slack)."""
    if not WEBHOOK_URL:
        return

    try:
        message = {
            "content": f"🚀 今日のDaily Dev Digestが生成されました！\n{digest_url}",
        }
        resp = requests.post(WEBHOOK_URL, json=message, timeout=10)
        resp.raise_for_status()
        logger.info("Webhook notification sent.")
    except Exception as e:
        logger.warning("Failed to send webhook notification: %s", e)


# --- Main ---

def main():
    start_time = datetime.now()
    status = "Failed"
    digest_id = None
    
    try:
        logger.info("Starting Daily Dev Digest for %s", TODAY)

        github_activity = fetch_github_activity(TARGET_GITHUB_USERNAME)
        logger.info("GitHub activity fetched")

        pending_requests = query_notion_requests()
        logger.info("Found %d pending requests", len(pending_requests))

        rating_feedback = query_notion_ratings()
        logger.info("Rating feedback analyzed")
        
        system_prompt = load_system_prompt()

        digest_data = generate_digest(github_activity, pending_requests, rating_feedback, system_prompt)
        logger.info("Digest generated by Claude")

        digest_id = post_to_notion(digest_data, pending_requests)
        logger.info("Daily Dev Digest completed successfully")
        
        digest_url = f"https://notion.so/{digest_id.replace('-', '')}"
        send_webhook_notification(digest_url)
        status = "Success"
        
    except Exception as e:
        logger.error("Error during Daily Dev Digest: %s", e)
        raise
    finally:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        log_execution(status, duration, digest_id)


if __name__ == "__main__":
    main()
