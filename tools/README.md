# Tools

Each script in this directory is a self-contained, deterministic executor.

## Conventions
- Accept inputs via CLI args (`argparse`) or stdin
- Read credentials from `.env` via `python-dotenv`
- Print results to stdout (JSON preferred for piping)
- Exit with code 0 on success, non-zero on failure
- Never contain business logic — that lives in workflows

## Running a tool
```bash
python tools/script_name.py --arg value
```

## Adding a new tool
1. Create `tools/your_tool.py`
2. Add it to the relevant workflow `.md` file
3. Test it standalone before wiring into a workflow
