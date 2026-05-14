"""
Chart generator — submits chart specs to Nano Banana (kie.ai) and downloads the result PNGs.
Replaces the previous matplotlib renderer; same CLI interface and output format.
"""
import argparse
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

KIE_API_KEY = os.getenv("KIE_API_KEY", "")
CREATE_URL = "https://api.kie.ai/api/v1/jobs/createTask"
POLL_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"
MODEL = "google/nano-banana"
POLL_INTERVAL = 5    # seconds between status checks
MAX_WAIT = 300       # seconds before giving up on a single chart

STYLE = (
    "Style requirements: clean white background (#FFFFFF), primary color dark teal (#0D6E6E), "
    "accent mint green (#00E5A0), text color near-black (#111818), light gray grid lines (#D1D5D5), "
    "professional sans-serif font, minimal design for email newsletters, "
    "no decorative frames or drop shadows, all data labels clearly legible."
)


def _data_rows(labels: list, values: list) -> str:
    return "\n".join("  - {}: {}".format(l, v) for l, v in zip(labels, values))


def build_prompt(spec: dict) -> tuple:
    """Return (prompt_text, image_size) derived from a chart spec."""
    chart_type = spec.get("type", "bar")
    title      = spec.get("title", "Chart")
    x_label    = spec.get("x_label", "")
    y_label    = spec.get("y_label", "")
    data       = spec.get("data", {})
    labels     = data.get("labels", [])
    values     = data.get("values", [])
    caption    = spec.get("caption", "")

    if chart_type == "line":
        rows = _data_rows(labels, values)
        prompt = (
            "Create a professional line chart for a business email newsletter.\n"
            'Title: "{}"\nX-axis: {}\nY-axis: {}\nData points in order:\n{}\n{}\n'
            "Line color teal (#0D6E6E), circular markers filled mint green (#00E5A0), "
            "subtle fill under the line at 8% opacity. Show numeric labels above each point."
        ).format(title, x_label, y_label, rows, STYLE)
        image_size = "16:9"

    elif chart_type == "donut":
        total = sum(float(v) for v in values) if values else 1
        rows = "\n".join(
            "  - {}: {} ({:.0f}%)".format(l, v, float(v) / total * 100)
            for l, v in zip(labels, values)
        )
        prompt = (
            "Create a professional donut chart for a business email newsletter.\n"
            'Title: "{}"\nSegments:\n{}\n{}\n'
            "Segment colors in order: #0D6E6E, #00E5A0, #00A875, #0A2E2E, #3B82F6. "
            "Show percentage labels inside each segment. Clean legend below the chart."
        ).format(title, rows, STYLE)
        image_size = "1:1"

    elif chart_type == "comparison":
        if values and isinstance(values[0], dict):
            series_lines = "".join(
                "  Series '{}': {}\n".format(s["label"], list(zip(labels, s["values"])))
                for s in values
            )
            prompt = (
                "Create a professional grouped bar chart for a business email newsletter.\n"
                'Title: "{}"\nX-axis: {}\nY-axis: {}\nGroups: {}\nSeries:\n{}{}\n'
                "Use teal (#0D6E6E) for the first series, mint green (#00E5A0) for the second. "
                "Include a legend."
            ).format(title, x_label, y_label, labels, series_lines, STYLE)
        else:
            rows = _data_rows(labels, values)
            prompt = (
                "Create a professional bar chart for a business email newsletter.\n"
                'Title: "{}"\nX-axis: {}\nY-axis: {}\nData:\n{}\n{}'
            ).format(title, x_label, y_label, rows, STYLE)
        image_size = "16:9"

    else:  # bar (default)
        rows = _data_rows(labels, values)
        prompt = (
            "Create a professional bar chart for a business email newsletter.\n"
            'Title: "{}"\nX-axis: {}\nY-axis: {}\n'
            "Data (show exact values on top of each bar):\n{}\n{}\n"
            "Use teal (#0D6E6E) bars, slight rounding on bar tops."
        ).format(title, x_label, y_label, rows, STYLE)
        image_size = "16:9"

    if caption:
        prompt += '\nCaption / source note at the bottom: "{}"'.format(caption)

    return prompt, image_size


def create_task(prompt: str, image_size: str) -> str:
    """POST to kie.ai and return the taskId."""
    headers = {
        "Authorization": "Bearer {}".format(KIE_API_KEY),
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "input": {"prompt": prompt, "output_format": "png", "image_size": image_size},
    }
    resp = requests.post(CREATE_URL, headers=headers, json=payload, verify=False, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 200:
        raise RuntimeError("kie.ai error: {} — {}".format(body.get("msg"), body))
    return body["data"]["taskId"]


def poll_task(task_id: str) -> str:
    """Poll until the task succeeds; return the image URL."""
    headers = {"Authorization": "Bearer {}".format(KIE_API_KEY)}
    deadline = time.time() + MAX_WAIT
    while time.time() < deadline:
        resp = requests.get(
            POLL_URL, params={"taskId": task_id}, headers=headers, verify=False, timeout=30
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        state = data.get("state", "")
        if state == "success":
            result = json.loads(data.get("resultJson", "{}"))
            urls = result.get("resultUrls", [])
            if not urls:
                raise RuntimeError("Task succeeded but resultUrls is empty")
            return urls[0]
        if state == "fail":
            raise RuntimeError("Task failed: {}".format(data.get("failMsg")))
        time.sleep(POLL_INTERVAL)
    raise TimeoutError("Task {} did not complete within {}s".format(task_id, MAX_WAIT))


def download_image(url: str, output_path: str) -> None:
    resp = requests.get(url, verify=False, timeout=60)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        f.write(resp.content)


def generate_chart(spec: dict, output_path: str) -> None:
    prompt, image_size = build_prompt(spec)
    task_id = create_task(prompt, image_size)
    image_url = poll_task(task_id)
    download_image(image_url, output_path)


def main():
    parser = argparse.ArgumentParser(description="Generate charts via Nano Banana (kie.ai).")
    parser.add_argument("--content", required=True, help="Path to content JSON")
    parser.add_argument("--output-dir", default=".tmp/charts", dest="output_dir")
    # --width, --height, --dpi are kept for CLI compatibility but ignored (AI sets dimensions)
    parser.add_argument("--width", type=int, default=600)
    parser.add_argument("--height", type=int, default=320)
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args()

    if not KIE_API_KEY:
        print(json.dumps({"status": "error", "code": 1,
                          "message": "KIE_API_KEY not set in .env"}))
        sys.exit(1)

    if not os.path.exists(args.content):
        print(json.dumps({"status": "error", "code": 1,
                          "message": "Content file not found: {}".format(args.content)}))
        sys.exit(1)

    with open(args.content, encoding="utf-8") as f:
        content = json.load(f)

    specs = content.get("chart_specs", [])
    if not specs:
        print(json.dumps({"status": "ok", "charts": [],
                          "message": "No chart_specs in content JSON"}))
        sys.exit(0)

    os.makedirs(args.output_dir, exist_ok=True)
    generated = []
    errors = []

    for spec in specs:
        chart_id = spec.get("id", "chart_{}".format(len(generated)))
        output_path = os.path.join(args.output_dir, "{}.png".format(chart_id))
        try:
            generate_chart(spec, output_path)
            generated.append(output_path)
        except Exception as e:
            errors.append({"id": chart_id, "error": str(e)})

    result = {
        "status": "ok" if not errors else "partial",
        "charts": generated,
        "errors": errors,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
