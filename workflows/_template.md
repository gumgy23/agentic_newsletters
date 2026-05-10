# Workflow: [Name]

## Objective
One sentence describing what this workflow produces.

## Inputs
| Input | Type | Required | Description |
|-------|------|----------|-------------|
| `param_name` | string | yes | What it represents |

## Steps

### Step 1 — [Action Name]
- **Tool:** `tools/script_name.py`
- **Args:** `--arg value`
- **Output:** What the tool produces and where it goes
- **On failure:** What to do if this step fails

### Step 2 — [Action Name]
- **Tool:** `tools/another_script.py`
- **Args:** depends on Step 1 output
- **Output:** Final deliverable location (e.g. Google Sheet URL)

## Expected Output
Describe the final artifact — format, location, and what "done" looks like.

## Edge Cases & Notes
- Rate limits, retries, known quirks
- Any API-specific behavior discovered during use
