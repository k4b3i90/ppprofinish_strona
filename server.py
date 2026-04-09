import json
import mimetypes
import os
import smtplib
from email.message import EmailMessage
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


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

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "p.p.profinish@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
CONTACT_TO = os.getenv("CONTACT_TO", "p.p.profinish@gmail.com")


class ContactServer(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self._serve_file("index.html")
            return

        safe_path = self.path.lstrip("/")
        if not safe_path:
            safe_path = "index.html"

        target = ROOT / safe_path
        if target.is_file() and ROOT in target.resolve().parents:
            self._serve_file(safe_path)
            return

        self._send_json({"error": "Nie znaleziono zasobu."}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if self.path != "/api/contact":
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

        if not SMTP_PASSWORD:
            self._send_json(
                {
                    "error": (
                        "Brakuje konfiguracji SMTP. Ustaw zmienną środowiskową "
                        "SMTP_PASSWORD z hasłem aplikacji Gmail."
                    )
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        try:
            self._send_contact_email(name, phone, email, message)
        except smtplib.SMTPException:
            self._send_json(
                {"error": "Nie udało się wysłać e-maila. Sprawdź konfigurację Gmail SMTP."},
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
        mail = EmailMessage()
        mail["Subject"] = f"Nowe zapytanie ze strony P&P Profinish od {name}"
        mail["From"] = SMTP_USERNAME
        mail["To"] = CONTACT_TO
        mail["Reply-To"] = email

        phone_line = phone if phone else "Nie podano"
        mail.set_content(
            "\n".join(
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
        )

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(mail)


if __name__ == "__main__":
    print(f"Serwer uruchomiony na http://{HOST}:{PORT}")
    print(f"Docelowy adres odbiorczy: {CONTACT_TO}")
    ThreadingHTTPServer((HOST, PORT), ContactServer).serve_forever()
