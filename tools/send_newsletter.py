"""
Newsletter sender — fetches subscriber list from Google Sheets and sends via SMTP.
Only sends to rows where status == active.
"""
import argparse
import json
import os
import smtplib
import ssl
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Windows SSL workaround — must happen before any google/requests imports
ssl._create_default_https_context = ssl._create_unverified_context  # noqa
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import requests as _requests
_orig_send = _requests.Session.send
def _no_verify_send(self, request, **kwargs):
    kwargs["verify"] = False
    return _orig_send(self, request, **kwargs)
_requests.Session.send = _no_verify_send
import os
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

import gspread
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
          "https://www.googleapis.com/auth/drive.readonly"]

REQUIRED_HEADERS = {"email", "first_name", "last_name", "status"}


def get_gspread_client() -> gspread.Client:
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    token_path = os.getenv("GOOGLE_TOKEN_PATH", "token.json")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return gspread.authorize(creds)


def get_subscribers(spreadsheet_id: str, sheet_name: str) -> list[dict]:
    gc = get_gspread_client()
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(sheet_name)
    records = ws.get_all_records()

    if not records:
        return []

    # Validate headers
    headers = set(records[0].keys())
    missing = REQUIRED_HEADERS - headers
    if missing:
        print(json.dumps({
            "status": "error", "code": 5,
            "message": f"Subscriber sheet missing columns: {', '.join(sorted(missing))}. "
                       "Expected: email, first_name, last_name, status, tags"
        }))
        sys.exit(5)

    return [r for r in records if str(r.get("status", "")).strip().lower() == "active"]


def build_message(html: str, txt: str, subject: str, preview_text: str,
                  from_addr: str, from_name: str, to_addr: str,
                  first_name: str) -> MIMEMultipart:
    personalised_subject = subject.replace("{{first_name}}", first_name).replace(
        "{{ first_name }}", first_name)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = personalised_subject
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_addr
    msg["X-Preview-Text"] = preview_text[:90]

    msg.attach(MIMEText(txt, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def smtp_connect(host: str, port: int, user: str, password: str) -> smtplib.SMTP:
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.ehlo()
            server.starttls()
            server.ehlo()
        server.login(user, password)
        return server
    except smtplib.SMTPException as e:
        print(json.dumps({"status": "error", "code": 3,
                          "message": f"SMTP connection failed: {e}. "
                          "If using Gmail with 2FA, use an App Password (not your main password). "
                          "If port 587 times out, try SMTP_PORT=465."}))
        sys.exit(3)
    except OSError as e:
        print(json.dumps({"status": "error", "code": 3,
                          "message": f"Network error connecting to {host}:{port}: {e}. "
                          "Some Indonesian ISPs block port 587 — try SMTP_PORT=465."}))
        sys.exit(3)


def main():
    parser = argparse.ArgumentParser(description="Send newsletter to Google Sheets subscriber list.")
    parser.add_argument("--html", required=True, help="Path to rendered HTML newsletter")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--preview-text", default="", dest="preview_text")
    parser.add_argument("--spreadsheet-id", required=True, dest="spreadsheet_id")
    parser.add_argument("--sheet-name", default="Subscribers", dest="sheet_name")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Print recipients without sending any email")
    parser.add_argument("--delay-seconds", type=float, default=0.5, dest="delay_seconds",
                        help="Delay between sends to avoid rate limits")
    args = parser.parse_args()

    if not os.path.exists(args.html):
        print(json.dumps({"status": "error", "code": 1,
                          "message": f"HTML file not found: {args.html}"}))
        sys.exit(1)

    with open(args.html, encoding="utf-8") as f:
        html = f.read()

    txt_path = args.html.replace(".html", ".txt")
    txt = open(txt_path, encoding="utf-8").read() if os.path.exists(txt_path) else ""

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    from_name = os.getenv("NEWSLETTER_FROM_NAME", "NexNusa AI")

    if not smtp_user or not smtp_pass:
        print(json.dumps({"status": "error", "code": 3,
                          "message": "SMTP_USER and SMTP_PASS must be set in .env"}))
        sys.exit(3)

    try:
        subscribers = get_subscribers(args.spreadsheet_id, args.sheet_name)
    except Exception as e:
        import traceback
        print(json.dumps({"status": "error", "code": 2,
                          "message": f"Google Sheets auth failed: {e}",
                          "traceback": traceback.format_exc()}))
        sys.exit(2)

    if not subscribers:
        print(json.dumps({"status": "ok", "sent": 0, "message": "No active subscribers found"}))
        sys.exit(0)

    if args.dry_run:
        recipients = [r["email"] for r in subscribers]
        print(json.dumps({
            "status": "ok (dry-run)",
            "would_send_to": recipients,
            "count": len(recipients),
        }))
        return

    server = smtp_connect(smtp_host, smtp_port, smtp_user, smtp_pass)

    sent, failed = [], []
    for sub in subscribers:
        to_addr = str(sub.get("email", "")).strip()
        first_name = str(sub.get("first_name", "")).strip()
        if not to_addr or "@" not in to_addr:
            continue
        try:
            msg = build_message(
                html, txt, args.subject, args.preview_text,
                smtp_user, from_name, to_addr, first_name,
            )
            server.sendmail(smtp_user, [to_addr], msg.as_string())
            sent.append(to_addr)
        except smtplib.SMTPException as e:
            failed.append({"email": to_addr, "error": str(e)})

        if args.delay_seconds > 0:
            time.sleep(args.delay_seconds)

    server.quit()

    result = {
        "status": "ok" if not failed else "partial",
        "sent": len(sent),
        "failed": len(failed),
        "failed_details": failed,
        "recipients": sent,
    }
    print(json.dumps(result))

    if failed:
        sys.exit(4)


if __name__ == "__main__":
    main()
