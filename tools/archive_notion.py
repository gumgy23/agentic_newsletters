"""
Notion archiver — creates a page in the newsletter database for topic history and searchable archive.
Uses the Notion REST API directly for reliable scripted access.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import ssl
ssl._create_default_https_context = ssl._create_unverified_context  # noqa
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import requests

_orig_send = requests.Session.send
def _patched_send(self, request, **kwargs):
    kwargs.setdefault("verify", False)
    return _orig_send(self, request, **kwargs)
requests.Session.send = _patched_send

from dotenv import load_dotenv

load_dotenv()

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"


def notion_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def rich_text(content: str) -> list:
    return [{"type": "text", "text": {"content": content[:2000]}}]


def paragraph_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text(text[:2000])},
    }


def heading_block(text: str, level: int = 2) -> dict:
    h_type = f"heading_{level}"
    return {
        "object": "block",
        "type": h_type,
        h_type: {"rich_text": rich_text(text)},
    }


def bullet_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text[:2000])},
    }


def create_page(api_key: str, database_id: str, content: dict,
                subject: str, sent_count: int, issue_number: int) -> dict:
    c = content.get("content", {})
    meta = content.get("meta", {})
    email = content.get("email", {})
    sources = content.get("sources_used", [])
    takeaways = c.get("takeaways", [])
    sections = c.get("sections", [])
    topic = meta.get("topic", content.get("topic", "Unknown"))
    title = c.get("title", topic)

    # Build page children blocks
    children = []

    intro = c.get("intro", "")
    if intro:
        children.append(heading_block("Introduction", 2))
        for para in (intro.split("\n\n") or [intro]):
            if para.strip():
                children.append(paragraph_block(para.strip()))

    for sec in sections:
        if sec.get("heading"):
            children.append(heading_block(sec["heading"], 3))
        if sec.get("body"):
            children.append(paragraph_block(sec["body"][:2000]))

    if takeaways:
        children.append(heading_block("Key Takeaways", 2))
        for item in takeaways:
            children.append(bullet_block(item))

    if sources:
        children.append(heading_block("Sources", 2))
        for url in sources[:10]:
            children.append(bullet_block(url))

    # Page properties
    properties = {
        "Title": {"title": rich_text(title)},
        "Topic": {"rich_text": rich_text(topic)},
        "Subject Line": {"rich_text": rich_text(subject[:200])},
        "Issue": {"number": issue_number},
        "Date": {"date": {"start": datetime.now(timezone.utc).date().isoformat()}},
        "Status": {"select": {"name": "Sent"}},
        "Subscribers Reached": {"number": sent_count},
        "Key Takeaways": {"rich_text": rich_text(" | ".join(takeaways))},
        "Sources": {"rich_text": rich_text(", ".join(sources[:5]))},
    }

    payload = {
        "parent": {"database_id": database_id},
        "properties": properties,
        "children": children[:100],
    }

    resp = requests.post(f"{NOTION_BASE}/pages", headers=notion_headers(api_key),
                         json=payload, timeout=30, verify=False)
    return resp


def main():
    parser = argparse.ArgumentParser(description="Archive newsletter to Notion database.")
    parser.add_argument("--content", required=True, help="Path to content JSON")
    parser.add_argument("--html", required=True, help="Path to rendered HTML (for size info)")
    parser.add_argument("--sent-count", type=int, default=0, dest="sent_count")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--issue-number", type=int, required=True, dest="issue_number")
    args = parser.parse_args()

    api_key = os.getenv("NOTION_API_KEY")
    database_id = os.getenv("NOTION_DATABASE_ID")

    if not api_key or not database_id:
        print(json.dumps({"status": "skip",
                          "message": "NOTION_API_KEY or NOTION_DATABASE_ID not set — skipping archive"}))
        sys.exit(0)

    if not os.path.exists(args.content):
        print(json.dumps({"status": "error", "code": 1,
                          "message": f"Content file not found: {args.content}"}))
        sys.exit(1)

    with open(args.content, encoding="utf-8") as f:
        content = json.load(f)

    resp = create_page(api_key, database_id, content, args.subject,
                       args.sent_count, args.issue_number)

    if resp.status_code == 200:
        page = resp.json()
        print(json.dumps({
            "status": "ok",
            "notion_page_url": page.get("url", ""),
            "notion_page_id": page.get("id", ""),
        }))
    elif resp.status_code == 400:
        data = resp.json()
        # Handle case where database doesn't have all expected properties
        # by retrying with minimal properties
        minimal_payload = {
            "parent": {"database_id": database_id},
            "properties": {
                "Title": {"title": [{"type": "text", "text": {
                    "content": content.get("content", {}).get("title", args.subject)
                }}]}
            },
        }
        retry = requests.post(f"{NOTION_BASE}/pages", headers=notion_headers(api_key),
                              json=minimal_payload, timeout=30, verify=False)
        if retry.status_code == 200:
            page = retry.json()
            print(json.dumps({
                "status": "ok",
                "message": "Archived with minimal properties — add matching columns to your Notion database for full archival.",
                "notion_page_url": page.get("url", ""),
                "notion_page_id": page.get("id", ""),
            }))
        else:
            print(json.dumps({"status": "skip",
                              "message": f"Notion database schema mismatch (HTTP {resp.status_code}): {data.get('message', '')[:200]}. "
                              "Set up the database with the required columns (Title, Topic, Subject Line, Issue, Date, Status, Subscribers Reached, Key Takeaways, Sources) and ensure the integration has access."}))
            sys.exit(0)
    else:
        print(json.dumps({"status": "error", "code": 2,
                          "message": f"Notion API error {resp.status_code}: {resp.text[:300]}"}))
        sys.exit(2)


if __name__ == "__main__":
    main()
