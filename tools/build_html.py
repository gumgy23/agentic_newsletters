"""
HTML builder — assembles content JSON + chart PNGs into a self-contained branded HTML newsletter.
All images are base64-embedded. Also outputs a plain-text fallback.
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import html2text
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape

load_dotenv()

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
TEMPLATE_NAME = "newsletter.html.j2"


def b64_encode_file(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def append_utm(url: str, utm_source: str, utm_medium: str,
               utm_campaign: str, utm_content: str) -> str:
    if not url or not url.startswith("http"):
        return url
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    params.update({
        "utm_source": [utm_source],
        "utm_medium": [utm_medium],
        "utm_campaign": [utm_campaign],
        "utm_content": [utm_content],
    })
    new_query = urllib.parse.urlencode(params, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def split_paragraphs(text: str) -> list[str]:
    """Split body text into paragraphs on double-newline or single newline."""
    paras = [p.strip() for p in re.split(r"\n{2,}|\n", text) if p.strip()]
    return paras if paras else [text]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def main():
    parser = argparse.ArgumentParser(description="Build branded HTML newsletter from content JSON.")
    parser.add_argument("--content", required=True, help="Path to content JSON")
    parser.add_argument("--charts-dir", default=".tmp/charts", dest="charts_dir")
    parser.add_argument("--logo", default="brand_assets/Logo Nexnusa ai.png",
                        help="Path to full logo PNG")
    parser.add_argument("--icon", default="brand_assets/icon nexnusa.png",
                        help="Path to icon-only PNG")
    parser.add_argument("--template-dir", default=TEMPLATE_DIR, dest="template_dir")
    parser.add_argument("--output", default="")
    parser.add_argument("--utm-source", default="newsletter", dest="utm_source")
    parser.add_argument("--utm-medium", default="email", dest="utm_medium")
    parser.add_argument("--utm-campaign", default="", dest="utm_campaign")
    parser.add_argument("--unsubscribe-url", default="https://nexnusa.com/unsubscribe",
                        dest="unsubscribe_url")
    args = parser.parse_args()

    if not os.path.exists(args.content):
        print(json.dumps({"status": "error", "code": 1,
                          "message": f"Content file not found: {args.content}"}))
        sys.exit(1)

    with open(args.content, encoding="utf-8") as f:
        content = json.load(f)

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    output_path = args.output or f".tmp/newsletter_{date_str}.html"
    txt_path = output_path.replace(".html", ".txt")
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    # ── Logo base64 ────────────────────────────────────────────────────────
    logo_b64 = b64_encode_file(args.logo) if os.path.exists(args.logo) else ""
    icon_path = args.icon if os.path.exists(args.icon) else args.logo
    icon_b64 = b64_encode_file(icon_path) if os.path.exists(icon_path) else logo_b64

    # ── Chart files: map id → {b64, title, caption} ───────────────────────
    chart_map: dict[str, dict] = {}
    if os.path.isdir(args.charts_dir):
        for spec in content.get("chart_specs", []):
            cid = spec.get("id", "")
            png_path = os.path.join(args.charts_dir, f"{cid}.png")
            if os.path.exists(png_path):
                chart_map[cid] = {
                    "b64": b64_encode_file(png_path),
                    "title": spec.get("title", ""),
                    "caption": spec.get("caption", ""),
                    "insert_after_section": spec.get("insert_after_section", 999),
                }
            else:
                print(f"[warn] chart PNG not found: {png_path}", file=sys.stderr)

    # ── Build sections with attached charts ────────────────────────────────
    raw_sections = content.get("content", {}).get("sections", [])
    sections = []
    used_chart_ids: set[str] = set()

    for i, sec in enumerate(raw_sections):
        chart = None
        for spec in content.get("chart_specs", []):
            if spec.get("insert_after_section") == i and spec["id"] in chart_map:
                chart = chart_map[spec["id"]]
                used_chart_ids.add(spec["id"])
                break
        sections.append({
            "heading": sec.get("heading", ""),
            "body_paragraphs": split_paragraphs(sec.get("body", "")),
            "callout": sec.get("callout", ""),
            "chart": chart,
        })

    orphan_charts = [v for k, v in chart_map.items() if k not in used_chart_ids]

    # ── UTM campaign slug ──────────────────────────────────────────────────
    utm_campaign = args.utm_campaign or slug(content.get("content", {}).get("title", "newsletter"))
    issue_number = content.get("meta", {}).get("issue_number", 1)

    # ── CTA with UTM ──────────────────────────────────────────────────────
    cta_raw = content.get("content", {}).get("cta", {})
    cta = {
        "text": cta_raw.get("text", "Read more"),
        "url": append_utm(cta_raw.get("url", "https://nexnusa.com"),
                          args.utm_source, args.utm_medium, utm_campaign, "cta"),
        "context": cta_raw.get("context", ""),
    }

    # ── Template vars ──────────────────────────────────────────────────────
    newsletter_name = os.getenv("NEWSLETTER_NAME", "NexNusa AI Insights")
    date_formatted = datetime.now(timezone.utc).strftime("%B %-d, %Y") if os.name != "nt" \
        else datetime.now(timezone.utc).strftime("%B %d, %Y").replace(" 0", " ")

    intro_text = content.get("content", {}).get("intro", "")
    intro_paragraphs = split_paragraphs(intro_text)

    template_vars = {
        "newsletter_name": newsletter_name,
        "issue_number": issue_number,
        "date_formatted": date_formatted,
        "title": content.get("content", {}).get("title", ""),
        "intro_paragraphs": intro_paragraphs,
        "sections": sections,
        "orphan_charts": orphan_charts,
        "takeaways": content.get("content", {}).get("takeaways", []),
        "cta": cta,
        "preview_text": content.get("email", {}).get("preview_text", ""),
        "unsubscribe_url": args.unsubscribe_url,
        "social_links": [],
        "logo_b64": logo_b64,
        "icon_b64": icon_b64,
    }

    # ── Render HTML ────────────────────────────────────────────────────────
    env = Environment(
        loader=FileSystemLoader(args.template_dir),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template(TEMPLATE_NAME)
    html_out = template.render(**template_vars)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    # ── Plain-text fallback ────────────────────────────────────────────────
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.body_width = 80
    plain_text = converter.handle(html_out)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(plain_text)

    size_kb = os.path.getsize(output_path) / 1024
    if size_kb > 100:
        print(f"[warn] HTML file is {size_kb:.0f} KB — Gmail clips messages over 102 KB. "
              "Consider removing a chart or shortening sections.", file=sys.stderr)

    print(json.dumps({
        "status": "ok",
        "html_path": output_path,
        "txt_path": txt_path,
        "size_kb": round(size_kb, 1),
        "charts_embedded": len(used_chart_ids),
        "orphan_charts": len(orphan_charts),
    }))


if __name__ == "__main__":
    main()
