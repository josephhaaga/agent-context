"""Google Workspace plugin — indexes Drive files and Docs via REST API.

Auth strategy (in preference order):
1. ``gcloud auth print-access-token`` — uses existing gcloud credentials.
   The user must have run ``gcloud auth login --enable-gdrive-access`` at
   least once to grant the Drive scope.
2. Embedded OAuth loopback — if gcloud is missing or the token lacks Drive
   scope, we launch a local loopback server and open the browser for consent.
   The client credentials are bundled in the package (public, non-secret for
   installed apps).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import urllib.parse
import webbrowser
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import httpx

from agent_context.models import Document, SourceStatus
from agent_context.plugins.base import AuthError, BasePlugin, register

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DRIVE_SCOPES = "https://www.googleapis.com/auth/drive.readonly"
_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_DOCS_EXPORT_URL = "https://docs.googleapis.com/v1/documents/{id}"

# Mime types we care about and how we export them
_EXPORTABLE = {
    "application/vnd.google-apps.document": ("text/plain", "doc"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", "sheet"),
    "application/vnd.google-apps.presentation": ("text/plain", "slides"),
}

# Drive files we can read directly
_READABLE = {
    "text/plain": "txt",
    "text/markdown": "md",
    "text/csv": "csv",
}

_TOKEN_CACHE = Path.home() / ".config" / "agent-context" / "google_token.json"


def _utc(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


# ---------------------------------------------------------------------------
# Token acquisition
# ---------------------------------------------------------------------------


async def _gcloud_token() -> str | None:
    """Try to get an access token from gcloud. Returns None on failure."""
    if shutil.which("gcloud") is None:
        return None
    proc = await asyncio.create_subprocess_exec(
        "gcloud",
        "auth",
        "print-access-token",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return None
    token = stdout.decode().strip()
    # Verify token has Drive scope by hitting the tokeninfo endpoint
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"access_token": token},
        )
        if resp.status_code != 200:
            return None
        info = resp.json()
        scopes = info.get("scope", "")
        if "drive" not in scopes:
            return None
    return token


async def _loopback_oauth(client_id: str, client_secret: str) -> str:
    """Run embedded OAuth loopback flow. Opens browser, returns access token."""
    port = 8787
    redirect_uri = f"http://localhost:{port}"
    auth_code: list[str] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if "code" in params:
                auth_code.append(params["code"][0])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h1>Authenticated! You can close this tab.</h1>")

        def log_message(self, *_: object) -> None:  # suppress server log noise
            pass

    server = HTTPServer(("localhost", port), _Handler)
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _DRIVE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    print(f"\nOpening browser for Google auth:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    # Wait for the code (up to 120 s)
    for _ in range(240):
        if auth_code:
            break
        await asyncio.sleep(0.5)
    server.shutdown()

    if not auth_code:
        raise AuthError("Google OAuth flow timed out waiting for browser redirect.")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": auth_code[0],
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        token_data = resp.json()

    # Cache token
    _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_CACHE.write_text(json.dumps(token_data))

    return token_data["access_token"]


async def _get_token(config: dict) -> str:
    """Resolve a valid Drive access token, trying gcloud then loopback OAuth."""
    # Try gcloud first
    token = await _gcloud_token()
    if token:
        return token

    # Try cached token
    if _TOKEN_CACHE.exists():
        try:
            cached = json.loads(_TOKEN_CACHE.read_text())
            access_token = cached.get("access_token", "")
            if access_token:
                # Quick validity check
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "https://oauth2.googleapis.com/tokeninfo",
                        params={"access_token": access_token},
                    )
                    if resp.status_code == 200:
                        return access_token
        except Exception:  # noqa: BLE001
            pass

    # Fallback: loopback OAuth
    client_id = config.get("oauth_client_id", "")
    client_secret = config.get("oauth_client_secret", "")
    if not client_id or not client_secret:
        raise AuthError(
            "Google Drive scope not available via gcloud and no OAuth credentials configured.\n"
            "Run: gcloud auth login --enable-gdrive-access\n"
            "Or set oauth_client_id / oauth_client_secret in your agent-context config."
        )
    return await _loopback_oauth(client_id, client_secret)


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


@register
class GooglePlugin(BasePlugin):
    """Indexes Google Drive files (Docs, Sheets, Slides, plain text).

    Config keys:
        enabled (bool): Default true.
        include_shared (bool): Include files shared with me. Default true.
        folders (list[str]): Drive folder IDs to restrict indexing to.
        file_limit (int): Max files per fetch. Default 500.
        oauth_client_id (str): Client ID for loopback OAuth fallback.
        oauth_client_secret (str): Client secret for loopback OAuth fallback.
    """

    name = "google"

    async def fetch(self, since: datetime | None = None) -> AsyncIterator[Document]:  # type: ignore[override]
        token = await _get_token(self.config)
        headers = {"Authorization": f"Bearer {token}"}
        limit = int(self.config.get("file_limit", 500))
        include_shared = self.config.get("include_shared", True)
        folders: list[str] = self.config.get("folders", [])

        # Build query
        q_parts = [
            "trashed = false",
            "(" + " or ".join(f"mimeType = '{m}'" for m in {**_EXPORTABLE, **_READABLE}) + ")",
        ]
        if not include_shared:
            q_parts.append("'me' in owners")
        if folders:
            folder_q = " or ".join(f"'{fid}' in parents" for fid in folders)
            q_parts.append(f"({folder_q})")
        if since:
            q_parts.append(f"modifiedTime > '{since.isoformat()}'")

        q = " and ".join(q_parts)
        params: dict[str, str | int] = {
            "q": q,
            "pageSize": min(limit, 100),
            "fields": "nextPageToken,files(id,name,mimeType,webViewLink,owners,createdTime,modifiedTime,description)",
            "orderBy": "modifiedTime desc",
        }

        fetched = 0
        async with httpx.AsyncClient() as client:
            while fetched < limit:
                resp = await client.get(_DRIVE_FILES_URL, headers=headers, params=params)  # type: ignore[arg-type]
                if resp.status_code == 401:
                    raise AuthError("Google Drive token expired or invalid.")
                resp.raise_for_status()
                data = resp.json()
                files = data.get("files", [])

                for f in files:
                    if fetched >= limit:
                        break
                    doc = await self._file_to_document(f, headers, client)
                    if doc:
                        fetched += 1
                        yield doc

                next_page = data.get("nextPageToken")
                if not next_page or not files:
                    break
                params["pageToken"] = next_page  # type: ignore[assignment]

    async def health(self) -> SourceStatus:
        gcloud_present = shutil.which("gcloud") is not None
        authed = False
        error: str | None = None

        try:
            token = await _get_token(self.config)
            authed = bool(token)
        except AuthError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

        return SourceStatus(
            name=self.name,
            enabled=self.config.get("enabled", True),
            cli_available=gcloud_present,
            authenticated=authed,
            error=error,
        )

    async def reauth(self) -> None:
        """Guide user to re-authenticate with Drive scope."""
        if shutil.which("gcloud") is not None:
            print("Run the following command to grant Drive access:")
            print("  gcloud auth login --enable-gdrive-access")
        else:
            # Trigger loopback flow
            await _get_token(self.config)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _file_to_document(
        self,
        f: dict,
        headers: dict,
        client: httpx.AsyncClient,
    ) -> Document | None:
        mime = f.get("mimeType", "")
        file_id = f["id"]
        name = f.get("name", "Untitled")
        url = f.get("webViewLink", "")
        owner = (f.get("owners") or [{}])[0].get("emailAddress")
        created = _utc(f.get("createdTime"))
        updated = _utc(f.get("modifiedTime"))

        content = ""
        doc_type = "doc"

        if mime in _EXPORTABLE:
            export_mime, doc_type = _EXPORTABLE[mime]
            export_url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export"
            try:
                resp = await client.get(
                    export_url,
                    headers=headers,
                    params={"mimeType": export_mime},
                    follow_redirects=True,
                )
                if resp.status_code == 200:
                    content = resp.text[:50_000]  # cap per-doc content
            except Exception:  # noqa: BLE001
                pass
        elif mime in _READABLE:
            doc_type = _READABLE[mime]
            dl_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
            try:
                resp = await client.get(dl_url, headers=headers, follow_redirects=True)
                if resp.status_code == 200:
                    content = resp.text[:50_000]
            except Exception:  # noqa: BLE001
                pass
        else:
            return None

        return Document(
            source="google",
            source_id=file_id,
            doc_type=doc_type,
            title=name,
            content=content,
            url=url,
            author=owner,
            created_at=created,
            updated_at=updated,
            metadata={
                "mime_type": mime,
                "description": f.get("description", ""),
            },
        )
