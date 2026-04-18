import json
import mimetypes
import os
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "4173"))


def load_env_file():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env_file()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "465").strip())
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "p.p.profinish@gmail.com").strip()
# Google shows app passwords in groups of four. Railway may receive the spaces,
# so normalize all whitespace before logging in to Gmail SMTP.
SMTP_PASSWORD = "".join(os.getenv("SMTP_PASSWORD", "").split())
CONTACT_TO = os.getenv("CONTACT_TO", "p.p.profinish@gmail.com").strip()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_FROM = os.getenv("RESEND_FROM", "P&P Profinish <onboarding@resend.dev>").strip()


class ContactServer(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)
        request_path = unquote(parsed_url.path)
        if request_path != "/" and request_path.endswith("/"):
            request_path = request_path.rstrip("/")

        if request_path == "/":
            self._serve_file("index.html")
            return

        safe_path = request_path.lstrip("/")
        if not safe_path:
            safe_path = "index.html"

        target = ROOT / safe_path
        if target.is_file() and ROOT in target.resolve().parents:
            self._serve_file(safe_path)
            return

        html_target = ROOT / f"{safe_path}.html"
        if html_target.is_file() and ROOT in html_target.resolve().parents:
            self._serve_file(f"{safe_path}.html")
            return

        self._send_json({"error": "Nie znaleziono zasobu."}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        request_path = urlparse(self.path).path

        if request_path != "/api/contact":
            self._send_json({"error": "Nieprawidlowy endpoint."}, HTTPStatus.NOT_FOUND)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({"error": "Nieprawidlowe dane formularza."}, HTTPStatus.BAD_REQUEST)
            return

        name = str(payload.get("name", "")).strip()
        phone = str(payload.get("phone", "")).strip()
        email = str(payload.get("email", "")).strip()
        message = str(payload.get("message", "")).strip()

        if not name or not email or not message:
            self._send_json(
                {"error": "Uzupełnij imię, e-mail i opis zakresu prac."},
                HTTPStatus.BAD_REQUEST,
            )
            return

        if not SMTP_PASSWORD and not RESEND_API_KEY:
            self._send_json(
                {
                    "error": (
                        "Brakuje konfiguracji wysyłki. Ustaw RESEND_API_KEY albo "
                        "SMTP_PASSWORD w Railway."
                    )
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        try:
            self._send_contact_email(name, phone, email, message)
        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            print(f"Resend API failed: {error.code} {error_body}", flush=True)
            self._send_json(
                {
                    "error": (
                        "Resend odrzucił wysyłkę. Sprawdź RESEND_API_KEY i "
                        "RESEND_FROM w Railway."
                    )
                },
                HTTPStatus.BAD_GATEWAY,
            )
            return
        except urllib.error.URLError as error:
            print(f"Resend connection failed: {error}", flush=True)
            self._send_json(
                {"error": "Nie udało się połączyć z Resend API. Spróbuj ponownie za chwilę."},
                HTTPStatus.BAD_GATEWAY,
            )
            return
        except smtplib.SMTPAuthenticationError as error:
            print(f"SMTP authentication failed: {error.smtp_code} {error.smtp_error!r}", flush=True)
            self._send_json(
                {
                    "error": (
                        "Gmail odrzucił logowanie SMTP. Sprawdź, czy SMTP_USERNAME "
                        "to dokładnie konto, na którym wygenerowano hasło aplikacji."
                    )
                },
                HTTPStatus.BAD_GATEWAY,
            )
            return
        except (smtplib.SMTPException, OSError) as error:
            print(f"SMTP send failed: {type(error).__name__}: {error}", flush=True)
            self._send_json(
                {"error": "Nie udało się połączyć z Gmail SMTP. Sprawdź zmienne SMTP w Railway."},
                HTTPStatus.BAD_GATEWAY,
            )
            return

        self._send_json({"ok": True}, HTTPStatus.OK)

    def log_message(self, format, *args):
        return

    def _serve_file(self, relative_path: str):
        target = ROOT / relative_path
        if not target.exists():
            self._send_json({"error": "Nie znaleziono pliku."}, HTTPStatus.NOT_FOUND)
            return

        content_type, _ = mimetypes.guess_type(target.name)
        if content_type:
            if content_type.startswith("text/"):
                content_type = f"{content_type}; charset=utf-8"
            elif content_type in {"application/javascript", "application/json"}:
                content_type = f"{content_type}; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def _send_json(self, payload, status: HTTPStatus):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_contact_email(self, name: str, phone: str, email: str, message: str):
        if RESEND_API_KEY:
            self._send_contact_email_resend(name, phone, email, message)
            return

        self._send_contact_email_smtp(name, phone, email, message)

    def _build_contact_text(self, name: str, phone: str, email: str, message: str):
        phone_line = phone if phone else "Nie podano"
        return "\n".join(
            [
                "Nowe zapytanie ze strony P&P Profinish",
                "",
                f"Imię i nazwisko: {name}",
                f"Telefon: {phone_line}",
                f"E-mail: {email}",
                "",
                "Zakres prac:",
                message,
            ]
        )

    def _send_contact_email_resend(self, name: str, phone: str, email: str, message: str):
        payload = {
            "from": RESEND_FROM,
            "to": [CONTACT_TO],
            "subject": f"Nowe zapytanie ze strony P&P Profinish od {name}",
            "text": self._build_contact_text(name, phone, email, message),
            "reply_to": email,
        }
        request = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()

    def _send_contact_email_smtp(self, name: str, phone: str, email: str, message: str):
        mail = EmailMessage()
        mail["Subject"] = f"Nowe zapytanie ze strony P&P Profinish od {name}"
        mail["From"] = SMTP_USERNAME
        mail["To"] = CONTACT_TO
        mail["Reply-To"] = email

        mail.set_content(self._build_contact_text(name, phone, email, message))

        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(mail)
            return

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(mail)


if __name__ == "__main__":
    print(f"Serwer uruchomiony na http://{HOST}:{PORT}")
    print(f"Docelowy adres odbiorczy: {CONTACT_TO}")
    ThreadingHTTPServer((HOST, PORT), ContactServer).serve_forever()
