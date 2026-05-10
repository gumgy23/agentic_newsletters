"""
Chart generator — reads chart_specs from content JSON and produces brand-styled PNG files.
Brand palette: NexNusa AI Design System.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import rcParams

# ── NexNusa AI brand palette ───────────────────────────────────────────────
BRAND_COLORS = ["#0D6E6E", "#00E5A0", "#00A875", "#0A2E2E", "#3B82F6"]
BG_COLOR = "#FFFFFF"
GRID_COLOR = "#D1D5D5"
TITLE_COLOR = "#111818"
LABEL_COLOR = "#374141"
CAPTION_COLOR = "#6B7272"
SPINE_COLOR = "#D1D5D5"

rcParams["font.family"] = "DejaVu Sans"
rcParams["axes.unicode_minus"] = False


def apply_base_style(ax, title: str, x_label: str, y_label: str):
    ax.set_title(title, fontsize=13, fontweight="bold", color=TITLE_COLOR, pad=12)
    ax.set_xlabel(x_label, fontsize=10, color=LABEL_COLOR, labelpad=6)
    ax.set_ylabel(y_label, fontsize=10, color=LABEL_COLOR, labelpad=6)
    ax.tick_params(colors=LABEL_COLOR, labelsize=9, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_facecolor(BG_COLOR)
    ax.figure.patch.set_facecolor(BG_COLOR)


def bar_chart(spec: dict, output_path: str, w: int, h: int, dpi: int):
    labels = spec["data"]["labels"]
    values = spec["data"]["values"]
    colors = [BRAND_COLORS[i % len(BRAND_COLORS)] for i in range(len(labels))]

    fig, ax = plt.subplots(figsize=(w / dpi, h / dpi), dpi=dpi)
    bars = ax.bar(labels, values, color=colors, width=0.55, zorder=3)

    # Value labels on bars
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.01,
                str(val), ha="center", va="bottom", fontsize=9,
                fontweight="bold", color=TITLE_COLOR)

    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    apply_base_style(ax, spec.get("title", ""), spec.get("x_label", ""), spec.get("y_label", ""))
    plt.xticks(rotation=20 if max(len(l) for l in labels) > 8 else 0, ha="right")
    plt.tight_layout(pad=1.5)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)


def line_chart(spec: dict, output_path: str, w: int, h: int, dpi: int):
    labels = spec["data"]["labels"]
    values = spec["data"]["values"]

    fig, ax = plt.subplots(figsize=(w / dpi, h / dpi), dpi=dpi)
    ax.plot(labels, values, color=BRAND_COLORS[0], linewidth=2.5, marker="o",
            markersize=6, markerfacecolor=BRAND_COLORS[1], markeredgecolor=BRAND_COLORS[0],
            markeredgewidth=1.5, zorder=3)
    ax.fill_between(labels, values, alpha=0.08, color=BRAND_COLORS[0], zorder=2)

    # Value labels
    for x, y in zip(labels, values):
        ax.annotate(str(y), (x, y), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=8, color=TITLE_COLOR, fontweight="bold")

    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    apply_base_style(ax, spec.get("title", ""), spec.get("x_label", ""), spec.get("y_label", ""))
    plt.xticks(rotation=20 if len(labels) > 6 else 0)
    plt.tight_layout(pad=1.5)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)


def donut_chart(spec: dict, output_path: str, w: int, h: int, dpi: int):
    labels = spec["data"]["labels"]
    values = spec["data"]["values"]
    colors = [BRAND_COLORS[i % len(BRAND_COLORS)] for i in range(len(labels))]

    fig, ax = plt.subplots(figsize=(w / dpi, h / dpi), dpi=dpi)
    wedges, texts, autotexts = ax.pie(
        values, labels=None, colors=colors, autopct="%1.0f%%",
        startangle=90, pctdistance=0.75,
        wedgeprops={"width": 0.5, "edgecolor": BG_COLOR, "linewidth": 2},
    )
    for at in autotexts:
        at.set_fontsize(9)
        at.set_color(BG_COLOR)
        at.set_fontweight("bold")

    ax.legend(wedges, labels, loc="lower center", bbox_to_anchor=(0.5, -0.12),
              ncol=min(len(labels), 3), fontsize=9, frameon=False,
              labelcolor=LABEL_COLOR)
    ax.set_title(spec.get("title", ""), fontsize=13, fontweight="bold",
                 color=TITLE_COLOR, pad=12)
    ax.figure.patch.set_facecolor(BG_COLOR)
    plt.tight_layout(pad=1.5)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)


def comparison_chart(spec: dict, output_path: str, w: int, h: int, dpi: int):
    """Grouped bar chart for comparing two series."""
    data = spec["data"]
    labels = data.get("labels", [])
    # Support either flat values or nested series
    if isinstance(data.get("values", [None])[0], (int, float)):
        # Single series — fall back to bar chart
        bar_chart(spec, output_path, w, h, dpi)
        return

    series = data.get("values", [])  # list of {label, values} dicts
    n_groups = len(labels)
    n_series = len(series)
    width = 0.8 / n_series
    x = list(range(n_groups))

    fig, ax = plt.subplots(figsize=(w / dpi, h / dpi), dpi=dpi)
    for i, s in enumerate(series):
        offsets = [xi + (i - n_series / 2 + 0.5) * width for xi in x]
        color = BRAND_COLORS[i % len(BRAND_COLORS)]
        ax.bar(offsets, s["values"], width=width * 0.9, color=color, label=s["label"], zorder=3)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(fontsize=9, frameon=False, labelcolor=LABEL_COLOR)
    apply_base_style(ax, spec.get("title", ""), spec.get("x_label", ""), spec.get("y_label", ""))
    plt.tight_layout(pad=1.5)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)


RENDERERS = {
    "bar": bar_chart,
    "line": line_chart,
    "donut": donut_chart,
    "comparison": comparison_chart,
}


def main():
    parser = argparse.ArgumentParser(description="Generate brand-styled charts from content JSON.")
    parser.add_argument("--content", required=True, help="Path to content JSON")
    parser.add_argument("--output-dir", default=".tmp/charts", dest="output_dir")
    parser.add_argument("--width", type=int, default=600, help="Chart width in pixels")
    parser.add_argument("--height", type=int, default=320, help="Chart height in pixels")
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args()

    if not os.path.exists(args.content):
        print(json.dumps({"status": "error", "code": 1,
                          "message": f"Content file not found: {args.content}"}))
        sys.exit(1)

    with open(args.content, encoding="utf-8") as f:
        content = json.load(f)

    specs = content.get("chart_specs", [])
    if not specs:
        print(json.dumps({"status": "ok", "charts": [], "message": "No chart_specs in content JSON"}))
        sys.exit(0)

    os.makedirs(args.output_dir, exist_ok=True)
    generated = []
    errors = []

    for spec in specs:
        chart_id = spec.get("id", f"chart_{len(generated)}")
        chart_type = spec.get("type", "bar")
        output_path = os.path.join(args.output_dir, f"{chart_id}.png")
        renderer = RENDERERS.get(chart_type, bar_chart)
        try:
            renderer(spec, output_path, args.width, args.height, args.dpi)
            generated.append(output_path)
        except Exception as e:
            errors.append({"id": chart_id, "error": str(e)})

    result = {"status": "ok" if not errors else "partial",
              "charts": generated, "errors": errors}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
