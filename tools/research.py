"""
Research tool — fetches sources and data points via Tavily API.
Outputs a JSON file consumed by write_content.py.
"""
import argparse
import json
import os
import ssl
import sys
from datetime import datetime, timezone

# Windows dev machines often lack trusted CA certs for corporate proxies.
ssl._create_default_https_context = ssl._create_unverified_context  # noqa: SIM117

from dotenv import load_dotenv
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from tavily import TavilyClient


def _make_session() -> requests.Session:
    s = requests.Session()
    s.verify = False
    return s

load_dotenv()


def fetch(client: TavilyClient, query: str, depth: str, max_results: int, days: int) -> list:
    kwargs = {"query": query, "search_depth": depth, "max_results": max_results,
              "include_raw_content": True}
    if days:
        kwargs["days"] = days
    resp = client.search(**kwargs)
    return resp.get("results", [])


def normalise(results: list) -> list:
    out = []
    seen = set()
    for r in results:
        url = r.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        raw = r.get("raw_content") or r.get("content") or ""
        out.append({
            "url": url,
            "title": r.get("title", ""),
            "published_date": r.get("published_date", ""),
            "snippet": r.get("content", "")[:300],
            "raw_content": raw[:3000],
        })
    return out


def extract_data_points(results: list) -> list:
    """Pull structured numeric facts from raw content (best-effort heuristic)."""
    import re
    data_points = []
    pattern = re.compile(
        r'(\d[\d,\.]*\s*(?:%|percent|billion|million|trillion|x|times|fold))'
        r'[^\.\n]{0,120}',
        re.IGNORECASE,
    )
    seen_values = set()
    for r in results:
        for m in pattern.finditer(r.get("raw_content", "")):
            text = m.group(0).strip(" ,;")
            value = m.group(1).strip()
            if value in seen_values or len(text) < 15:
                continue
            seen_values.add(value)
            data_points.append({
                "value": value,
                "context": text,
                "source_url": r["url"],
            })
            if len(data_points) >= 20:
                return data_points
    return data_points


def main():
    parser = argparse.ArgumentParser(description="Research a topic via Tavily API.")
    parser.add_argument("--topic", required=True, help="Newsletter topic to research")
    parser.add_argument("--depth", default="advanced", choices=["basic", "advanced"],
                        help="Tavily search depth (advanced uses ~5 credits)")
    parser.add_argument("--max-results", type=int, default=8, dest="max_results")
    parser.add_argument("--days-back", type=int, default=30, dest="days_back",
                        help="Only return sources published within N days (0 = no filter)")
    parser.add_argument("--output", default="",
                        help="Output JSON path (auto-generated if omitted)")
    args = parser.parse_args()

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        print(json.dumps({"status": "error", "code": 1, "message": "TAVILY_API_KEY not set in .env"}))
        sys.exit(1)

    client = TavilyClient(api_key=api_key, session=_make_session())
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    output_path = args.output or f".tmp/research_{date_str}.json"
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    try:
        results = fetch(client, args.topic, args.depth, args.max_results, args.days_back)
    except Exception as e:
        print(json.dumps({"status": "error", "code": 2, "message": f"Tavily API error: {e}"}))
        sys.exit(2)

    if len(results) < 3 and args.days_back > 0 and args.days_back < 90:
        try:
            results = fetch(client, args.topic, args.depth, args.max_results, 90)
        except Exception:
            pass

    sources = normalise(results)
    if not sources:
        print(json.dumps({"status": "error", "code": 3, "message": "Zero results returned for topic"}))
        sys.exit(3)

    try:
        stats_results = fetch(client, f"{args.topic} statistics data numbers", "basic", 5, 0)
        all_results = results + stats_results
    except Exception:
        all_results = results

    data_points = extract_data_points(normalise(all_results))

    payload = {
        "topic": args.topic,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(sources),
        "sources": sources,
        "data_points": data_points,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(json.dumps({"status": "ok", "output_path": output_path, "source_count": len(sources),
                      "data_points_found": len(data_points)}))


if __name__ == "__main__":
    main()
