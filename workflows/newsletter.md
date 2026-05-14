# Workflow: Newsletter Automation

## Objective
Produce and deliver a research-backed, chart-enhanced, NexNusa AI branded HTML newsletter on any topic in a single pipeline run.

## Inputs

| Input | Type | Required | Default | Description |
|---|---|---|---|---|
| `topic` | string | yes | — | The subject to research and write about |
| `tone` | string | no | `professional` | `professional`, `casual`, `analytical`, `inspirational` |
| `length` | string | no | `medium` | `short` (~600w), `medium` (~900w), `long` (~1300w) |
| `audience` | string | no | business professionals in Indonesia | Description of target reader |
| `context` | string | no | — | Extra editorial direction — angles to avoid, emphasis, etc. |
| `issue_number` | int | yes | — | Current issue number. Check Notion archive for last used. |
| `subject_line_pick` | int | no | — | Pre-select subject line 1, 2, or 3. If omitted, present all 3. |
| `dry_run` | bool | no | false | If true, build HTML but do not send email |

## Pre-flight Checklist (run before Step 1)

1. Verify `.env` exists (copy from `.env.example` if not). Must contain: `TAVILY_API_KEY`, `ANTHROPIC_API_KEY`, `KIE_API_KEY`, `SMTP_USER`, `SMTP_PASS`, `GOOGLE_SPREADSHEET_ID`
2. Verify `tools/templates/newsletter.html.j2` exists
3. Verify `brand_assets/Logo Nexnusa ai.png` and `brand_assets/icon nexnusa.png` exist
   - **Size check:** Logo must be under ~50 KB (PNG) or use a JPEG version. A large logo is the #1 cause of Gmail clipping. Use `brand_assets/Logo Nexnusa ai.jpg` (JPEG at q60, ~5 KB) for smallest size. Pass `--logo "brand_assets/Logo Nexnusa ai.jpg"` to `build_html.py`.
4. Create `.tmp/charts/` directory if it does not exist: `mkdir -p .tmp/charts`
5. **Google OAuth for sending:** `credentials.json` must exist in the project root for Step 7 to work. Without it, the subscriber list fetch from Google Sheets will fail. Obtain from Google Cloud Console (OAuth 2.0 Client Credentials) and run the auth flow once to generate `token.json`.
6. **Topic deduplication**: If Notion is configured, check the last 20 newsletter pages for overlapping keywords. If more than 3 keyword matches with a recent issue, warn the user before proceeding.

---

## Steps

### Step 1 — Research

- **Tool:** `tools/research.py`
- **Command:**
  ```
  python tools/research.py \
    --topic "{topic}" \
    --depth advanced \
    --max-results 8 \
    --days-back 30 \
    --output .tmp/research_YYYYMMDD.json
  ```
- **Output:** `.tmp/research_YYYYMMDD.json`
- **On failure (exit 2 — API error):** Check if `TAVILY_API_KEY` is set. Check Tavily dashboard for monthly quota (1000 requests free tier). If quota exhausted, retry with `--depth basic` to use 1 credit per call instead of 5.
- **On failure (exit 3 — zero results):** The tool already retries with `--days-back 90`. If still empty, inform the user: "No recent sources found for this topic. Try broadening the topic or add `--context` with related keywords."
- **Agent decision:** If `source_count < 3`, tell the user the research is thin. Ask if they want to proceed with limited sources or adjust the topic.

---

### Step 2 — Write Content

- **Tool:** `tools/write_content.py`
- **Command:**
  ```
  python tools/write_content.py \
    --research .tmp/research_YYYYMMDD.json \
    --topic "{topic}" \
    --tone {tone} \
    --length {length} \
    --audience "{audience}" \
    --context "{context}" \
    --issue-number {issue_number} \
    --output .tmp/content_YYYYMMDD.json
  ```
- **Output:** `.tmp/content_YYYYMMDD.json`
- **On failure (exit 3 — JSON parse failure):** Retry once. If it fails again, try with `--length short` to reduce output complexity.
- **Agent decision:** After the tool exits, read `spam_flags` from the output JSON. If any flags exist, show them to the user:
  ```
  ⚠️  Spam flags detected: [list]. These words may affect deliverability.
  Proceed anyway? (yes / regenerate with different wording)
  ```

---

### Step 3 — Subject Line Selection

*No tool needed — this is a pure agent decision.*

Read `content.email.subject_lines` (array of 3) from `.tmp/content_YYYYMMDD.json`.

If `subject_line_pick` was provided, use it directly.

If not, present all 3 with rationale:
```
Here are your 3 subject line options:

1. [Direct/Clear] — "{subject_1}"
   Best for: audiences who value clarity over cleverness.

2. [Curiosity-gap] — "{subject_2}"
   Best for: higher open rates when topic is not broadly known.

3. [Data-led] — "{subject_3}"
   Best for: analytical readers who respond to numbers and specifics.

Which would you like to use? (1, 2, or 3)
```

Also show the preview text: `Preview text: "{preview_text}"`

Record the chosen subject as `selected_subject`.

---

### Step 4 — Generate Charts

- **Tool:** `tools/generate_charts.py`
- **Provider:** [Nano Banana (kie.ai)](https://kie.ai/) — AI image generation API. Requires `KIE_API_KEY` in `.env` (get one at https://kie.ai/api-key).
- **Command:**
  ```
  python tools/generate_charts.py \
    --content .tmp/content_YYYYMMDD.json \
    --output-dir .tmp/charts
  ```
  (`--width`, `--height`, `--dpi` flags are accepted for CLI compatibility but ignored — Nano Banana determines output dimensions.)
- **Output:** `.tmp/charts/chart_0.png`, `.tmp/charts/chart_1.png`, etc.
- **How it works:** Each `chart_spec` is converted into a detailed text prompt describing the chart type, data, and NexNusa AI brand colors. The prompt is sent to Nano Banana, which generates a PNG image. The tool polls for completion (up to 5 minutes per chart) and downloads the result.
- **Skip condition:** If `chart_specs` is empty in the content JSON, skip this step. `build_html.py` handles zero charts gracefully.
- **On failure (exit 1 — missing API key):** Set `KIE_API_KEY` in `.env`.
- **On failure (API/timeout error):** The tool logs the bad spec and continues with remaining charts. Check the error output and notify the user if all charts failed. If kie.ai credits are exhausted, top up at https://kie.ai.

---

### Step 5 — Build HTML

- **Tool:** `tools/build_html.py`
- **Command:**
  ```
  python tools/build_html.py \
    --content .tmp/content_YYYYMMDD.json \
    --charts-dir .tmp/charts \
    --logo "brand_assets/Logo Nexnusa ai.png" \
    --icon "brand_assets/icon nexnusa.png" \
    --output .tmp/newsletter_YYYYMMDD.html \
    --utm-campaign "{topic_slug}-issue-{issue_number}"
  ```
- **Output:** `.tmp/newsletter_YYYYMMDD.html` + `.tmp/newsletter_YYYYMMDD.txt`
- **Agent decision:** After build, check the `size_kb` field in the output. If `size_kb > 100`, warn:
  ```
  ⚠️  HTML is {size_kb} KB. Gmail clips messages over 102 KB.
  Consider removing one chart or shortening a section before sending.
  ```
- **On failure (exit 3 — chart file missing):** Re-run Step 4 first, then retry.

---

### Step 6 — Review Gate

*Stop and present a summary to the user before sending.*

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 NexNusa AI Newsletter — Ready to Send
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Title:        {title}
 Subject:      {selected_subject}
 Preview text: {preview_text}
 Word count:   ~{word_count_estimate}
 Charts:       {chart_count}
 HTML size:    {size_kb} KB
 Issue #:      {issue_number}
 HTML file:    .tmp/newsletter_YYYYMMDD.html
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Type YES to send, or describe edits to make first.
```

**If user requests edits:**
- Text edits → re-run Step 2 with updated `--context`, then Steps 4–5
- Chart edits → re-run from Step 4
- Layout edits → re-run Step 5 only
- Subject line change → update `selected_subject` and re-ask

Do NOT proceed to Step 7 without explicit YES.

---

### Step 7 — Send

- **Tool:** `tools/send_newsletter.py`
- **Command:**
  ```
  python tools/send_newsletter.py \
    --html .tmp/newsletter_YYYYMMDD.html \
    --subject "{selected_subject}" \
    --preview-text "{preview_text}" \
    --spreadsheet-id {GOOGLE_SPREADSHEET_ID} \
    --sheet-name Subscribers \
    [--dry-run if dry_run == true]
  ```
- **Output:** Delivery report JSON: `{sent, failed, recipients}`
- **On failure (exit 3 — SMTP error):**
  - Verify `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` in `.env`
  - Gmail requires an **App Password** when 2FA is enabled. Never use the main account password.
  - Get App Password: Google Account → Security → 2-Step Verification → App passwords
  - If port 587 times out (common on some Indonesian ISPs), change `SMTP_PORT=465` in `.env`
- **On failure (exit 4 — partial failure):** Some sends failed. List the failed addresses and offer to retry for just those recipients.
- **On failure (exit 5 — sheet headers invalid):** The subscriber sheet is missing required columns. Fix headers and re-run.
- **Agent decision:** If `sent == 0` and no errors, it means no active subscribers were found. Check the sheet `status` column.

---

### Step 8 — Archive to Notion

- **Tool:** `tools/archive_notion.py`
- **Command:**
  ```
  python tools/archive_notion.py \
    --content .tmp/content_YYYYMMDD.json \
    --html .tmp/newsletter_YYYYMMDD.html \
    --sent-count {sent_count} \
    --subject "{selected_subject}" \
    --issue-number {issue_number}
  ```
- **Output:** Notion page URL (or skip message if Notion is not configured)
- **Non-blocking:** If this step fails, note the error but do NOT re-send the email. Notify the user that archival failed and suggest they manually log the issue.
- **On failure (exit 2 — API error):** Check `NOTION_API_KEY` and `NOTION_DATABASE_ID`. Ensure the Notion integration has been added to the database (Database → Share → Invite your integration).

---

## Expected Output

At the end of a successful run:
- ✅ Email delivered to all active subscribers
- ✅ Notion archive page created with issue metadata
- ✅ Local files saved:
  - `.tmp/newsletter_YYYYMMDD.html` — full branded HTML
  - `.tmp/newsletter_YYYYMMDD.txt` — plain text fallback
  - `.tmp/content_YYYYMMDD.json` — structured content
  - `.tmp/research_YYYYMMDD.json` — raw research data
  - `.tmp/charts/chart_*.png` — chart images

---

## Edge Cases & Notes

**Tavily quota (1000 req/month free tier)**
- `--depth advanced` uses 5 credits per call. Two calls per run = 10 credits.
- At 10 credits/run, you get ~100 newsletters/month on the free tier.
- Switch to `--depth basic` (1 credit each) to stretch to ~500/month.

**Gmail SMTP port blocked**
- Some Indonesian ISPs block outbound port 587.
- Workaround: set `SMTP_PORT=465` in `.env`. The tool automatically uses `SMTP_SSL` for port 465.

**Gmail App Password**
- Required when Google account has 2-Step Verification enabled.
- Path: myaccount.google.com → Security → 2-Step Verification → App passwords
- Generate one for "Mail" + "Windows Computer" (or "Other").
- Use this 16-character password as `SMTP_PASS`, NOT your main Gmail password.

**Gmail daily send limit**
- Free Gmail: 500 emails/day
- Google Workspace: 2000 emails/day
- If your list exceeds these limits, add `--delay-seconds 2` or split sends across days.

**Notion database setup**
Create a Notion database with these properties (exact names matter):
| Property | Type |
|---|---|
| Title | Title |
| Topic | Text |
| Subject Line | Text |
| Issue | Number |
| Date | Date |
| Status | Select (options: Draft, Sent) |
| Subscribers Reached | Number |
| Key Takeaways | Text |
| Sources | Text |
Then invite your Notion integration to the database.

**Google Sheets subscriber setup**
Row 1 must be exactly: `email | first_name | last_name | status | tags`
Set `status=active` for live subscribers, `status=unsubscribed` for opt-outs.
The sheet ID is in the URL: `spreadsheets/d/SHEET_ID/edit`

**HTML size limit**
Gmail clips HTML emails at 102 KB. Monitor `size_kb` in the Step 5 output.
If over 100 KB: the logo is almost always the culprit. Use the JPEG version (`Logo Nexnusa ai.jpg`) with `--logo`. If still over, remove one chart. Last resort: shorten a section.

**Windows SSL certificate errors**
On this machine (Windows 11), the default Python SSL context cannot verify external API certificates. Fixes applied to each tool:
- `research.py`: `TavilyClient` initialized with `session=requests.Session(); session.verify=False`
- `write_content.py`: `anthropic.Anthropic(http_client=httpx.Client(verify=False))`
- `archive_notion.py`: `requests.post(..., verify=False)` on each API call
If adding new tools that call external APIs, apply the same pattern.

**Anthropic API credits**
`write_content.py` calls the Anthropic API directly using `ANTHROPIC_API_KEY`. If that key has no credits, the tool exits with code 2. In that case, write the content JSON manually following the schema in `write_content.py:SYSTEM_PROMPT`, or top up credits at console.anthropic.com.

**Notion database schema**
Property names must match exactly (case-sensitive). If the database doesn't have the expected columns, `archive_notion.py` now skips gracefully (exit 0) with a skip message instead of failing. Fix by creating properties: Title (Title type), Topic (Text), Subject Line (Text), Issue (Number), Date (Date), Status (Select: Draft/Sent), Subscribers Reached (Number), Key Takeaways (Text), Sources (Text).

**Charts with no data**
If Claude sets `chart_specs: []` (no chartable data found in research), Step 4 is skipped and the newsletter renders without charts. This is expected and handled gracefully.

**Nano Banana image quality**
Nano Banana is an AI image model — chart output is generated from a text prompt, so exact pixel-perfect rendering is not guaranteed. If a chart looks off (wrong values, missing labels), re-run Step 4; generation is non-deterministic and a second attempt usually improves results. For maximum accuracy, keep data sets small (≤8 data points per chart). Nano Banana uses a point-based credit system at kie.ai — monitor usage at https://kie.ai/logs.
