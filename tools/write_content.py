"""
Content writer — sends research JSON to Claude API and produces structured newsletter content.
Outputs a JSON file consumed by generate_charts.py and build_html.py.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

import httpx
import anthropic
from dotenv import load_dotenv

load_dotenv()

SPAM_TRIGGERS = [
    r"\bfree\b", r"\bact now\b", r"\bguarantee\b", r"\bwinner\b",
    r"\bclick here\b", r"\bearn money\b", r"\bmake money fast\b",
    r"\blimited time offer\b", r"\bunsubscribe\b", r"\bno cost\b",
    r"\b100%\s*free\b", r"\bargent\b", r"\bexclusive deal\b",
]

SYSTEM_PROMPT = """You are an expert newsletter editor for NexNusa AI, a technology company helping Indonesian businesses grow with AI. Your newsletters are sharp, credible, and useful — written in Bahasa Indonesia for professionals who want signal, not noise.

Your task is to produce a complete newsletter in valid JSON format. Follow the schema exactly. Output ONLY the JSON object — no markdown fences, no explanations, nothing before or after the JSON.

Schema:
{
  "meta": {
    "topic": "<string>",
    "issue_number": <int>,
    "generated_at": "<ISO 8601 string>",
    "word_count_estimate": <int>,
    "tone": "<string>"
  },
  "email": {
    "subject_lines": ["<direct/clear>", "<curiosity-gap>", "<data-led>"],
    "preview_text": "<90 char max teaser that complements the subject — do NOT repeat it>"
  },
  "content": {
    "title": "<newsletter title, punchy, max 12 words>",
    "intro": "<2-3 paragraphs that open with a hook. Write in plain text — no markdown.>",
    "sections": [
      {
        "heading": "<section heading>",
        "body": "<body text, 150-250 words, plain text>",
        "callout": "<a single insight or pull-quote to highlight, max 40 words>"
      }
    ],
    "takeaways": ["<actionable takeaway 1>", "<actionable takeaway 2>", "<actionable takeaway 3>"],
    "cta": {
      "text": "<button label, max 5 words>",
      "url": "https://nexnusa.com",
      "context": "<one sentence before the button explaining why to click>"
    }
  },
  "chart_specs": [
    {
      "id": "chart_0",
      "type": "<bar|line|donut|comparison>",
      "title": "<chart title>",
      "x_label": "<x axis label>",
      "y_label": "<y axis label>",
      "data": {
        "labels": ["<label1>", "<label2>"],
        "values": [<number1>, <number2>]
      },
      "caption": "<Source: ...>",
      "insert_after_section": <0-based index of section after which to show this chart>
    }
  ],
  "spam_flags": [],
  "sources_used": ["<url1>", "<url2>"]
}

Rules:
- Language: Write ALL user-facing text fields in Bahasa Indonesia. This includes title, intro, section headings, body, callouts, takeaways, CTA, subject lines, preview text, and chart titles/labels/captions. Do NOT write any of these in English.
- subject_lines: exactly 3 items. First is direct/clear. Second is curiosity-gap. Third leads with a data point.
- preview_text: max 90 characters. Must feel different from all 3 subject lines.
- sections: 3-5 sections based on requested length.
- chart_specs: include 1-3 charts ONLY if the research contains real numeric data worth visualising. If no good data exists, set chart_specs to [].
- For donut charts: values must sum to 100.
- For line charts: labels must be time periods (months, years, quarters).
- spam_flags: always set to [] — the caller checks content separately.
- sources_used: list the URLs from the research that you actually used.
- All text fields: plain text only, no markdown, no HTML."""


def check_spam(text: str) -> list[str]:
    flags = []
    for pattern in SPAM_TRIGGERS:
        if re.search(pattern, text, re.IGNORECASE):
            flags.append(pattern.strip(r"\b"))
    return flags


def build_user_prompt(research: dict, topic: str, tone: str, length: str,
                      audience: str, context: str, issue_number: int) -> str:
    length_map = {"short": "3 sections, ~600 words total",
                  "medium": "4 sections, ~900 words total",
                  "long": "5 sections, ~1300 words total"}
    length_instruction = length_map.get(length, length_map["medium"])

    sources_summary = "\n".join(
        f"- [{s['title']}]({s['url']})\n  {s['snippet']}\n  Full: {s['raw_content'][:800]}"
        for s in research.get("sources", [])[:8]
    )
    data_points_summary = "\n".join(
        f"- {dp['value']}: {dp['context']} (source: {dp['source_url']})"
        for dp in research.get("data_points", [])[:15]
    )

    return f"""Write a newsletter about: {topic}

Issue number: {issue_number}
Tone: {tone}
Length: {length_instruction}
Audience: {audience}
Editorial direction: {context if context else "No special direction — be balanced and practical."}

--- RESEARCH SOURCES ---
{sources_summary}

--- DATA POINTS (use these to build chart_specs) ---
{data_points_summary if data_points_summary else "No numeric data found — set chart_specs to []."}

Now produce the JSON newsletter content. Output ONLY the JSON."""


def main():
    parser = argparse.ArgumentParser(description="Write newsletter content via Claude API.")
    parser.add_argument("--research", required=True, help="Path to research JSON")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--tone", default="professional",
                        choices=["professional", "casual", "analytical", "inspirational"])
    parser.add_argument("--length", default="medium", choices=["short", "medium", "long"])
    parser.add_argument("--audience", default="business professionals in Indonesia")
    parser.add_argument("--context", default="")
    parser.add_argument("--issue-number", type=int, default=1, dest="issue_number")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print(json.dumps({"status": "error", "code": 1, "message": "ANTHROPIC_API_KEY not set"}))
        sys.exit(1)

    if not os.path.exists(args.research):
        print(json.dumps({"status": "error", "code": 4, "message": f"Research file not found: {args.research}"}))
        sys.exit(4)

    with open(args.research, encoding="utf-8") as f:
        research = json.load(f)

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    output_path = args.output or f".tmp/content_{date_str}.json"
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=api_key, http_client=httpx.Client(verify=False))

    user_prompt = build_user_prompt(
        research, args.topic, args.tone, args.length,
        args.audience, args.context, args.issue_number,
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.APIError as e:
        print(json.dumps({"status": "error", "code": 2, "message": f"Claude API error: {e}"}))
        sys.exit(2)

    raw = response.content[0].text.strip()

    # Strip markdown fences if model wrapped the JSON anyway
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    try:
        content = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "code": 3,
                          "message": f"JSON parse failed: {e}", "raw_response": raw[:500]}))
        sys.exit(3)

    # Spam check across all text fields
    all_text = " ".join([
        content.get("content", {}).get("title", ""),
        content.get("content", {}).get("intro", ""),
        " ".join(s.get("body", "") for s in content.get("content", {}).get("sections", [])),
        " ".join(content.get("email", {}).get("subject_lines", [])),
    ])
    content["spam_flags"] = check_spam(all_text)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)

    result = {
        "status": "ok",
        "output_path": output_path,
        "title": content.get("content", {}).get("title", ""),
        "subject_lines": content.get("email", {}).get("subject_lines", []),
        "chart_count": len(content.get("chart_specs", [])),
        "spam_flags": content.get("spam_flags", []),
        "model": model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
