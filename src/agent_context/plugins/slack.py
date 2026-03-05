"""Slack plugin — indexes channels and threads via slackcli (browser token auth).

Auth strategy:
  slackcli uses xoxd/xoxc browser tokens obtained by the user pasting a cURL
  command from browser DevTools. No Slack app creation required.

Token expiry handling:
  - On 401/token_revoked, catch gracefully and set error on SourceStatus.
  - Return cached results and surface inline warning suggesting reauth.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from datetime import datetime, timezone
from typing import AsyncIterator

from agent_context.models import Document, SourceStatus
from agent_context.plugins.base import (
    AuthError,
    BasePlugin,
    CLINotFoundError,
    PluginError,
    register,
)


def _utc_from_ts(ts: str | float | None) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (ValueError, TypeError):
        return None


async def _slackcli(*args: str) -> str:
    """Run a slackcli command and return stdout.

    Raises:
        CLINotFoundError: slackcli is not installed.
        AuthError: Token expired or invalid.
        PluginError: Any other error.
    """
    if shutil.which("slackcli") is None:
        raise CLINotFoundError(
            "slackcli is not installed. Install from https://github.com/shaharia-lab/slackcli\n"
            "Then authenticate: slackcli auth parse-curl --login"
        )

    proc = await asyncio.create_subprocess_exec(
        "slackcli",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    out = stdout.decode().strip()
    err = stderr.decode().strip()

    if proc.returncode != 0:
        combined = f"{out} {err}".lower()
        if any(kw in combined for kw in ("token_revoked", "invalid_auth", "not_authed", "401")):
            raise AuthError(
                "Slack token expired or revoked. "
                "Re-authenticate with: agent-context sources reauth slack"
            )
        raise PluginError(f"slackcli exited {proc.returncode}: {err or out}")

    return out


def _strip_slack_markup(text: str) -> str:
    """Remove Slack mrkdwn formatting for cleaner indexing."""
    # User/channel mentions: <@U123ABC> → @user
    text = re.sub(r"<@[A-Z0-9]+>", "@user", text)
    # Channel links: <#C123|general> → #general
    text = re.sub(r"<#[A-Z0-9]+\|([^>]+)>", r"#\1", text)
    # URLs: <https://example.com|label> → label
    text = re.sub(r"<https?://[^|>]+\|([^>]+)>", r"\1", text)
    # Bare URLs: <https://example.com>
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
    return text


@register
class SlackPlugin(BasePlugin):
    """Indexes Slack public channels and threads.

    Config keys:
        enabled (bool): Default true.
        channels (list[str]): Channel names (without #) to index.
            If omitted, indexes all public channels up to ``max_channels``.
        max_channels (int): Cap when channels is unset. Default: 20.
        messages_per_channel (int): Max messages per channel. Default: 1000.
        include_threads (bool): Fetch thread replies. Default: true.
        include_dms (bool): Index DMs. Default: false (privacy).
        workspace (str): Workspace slug for URL construction.
    """

    name = "slack"

    async def fetch(self, since: datetime | None = None) -> AsyncIterator[Document]:  # type: ignore[override]
        channels = await self._resolve_channels()
        include_threads = self.config.get("include_threads", True)
        msg_limit = int(self.config.get("messages_per_channel", 1000))

        for ch_id, ch_name in channels:
            async for doc in self._fetch_channel(ch_id, ch_name, msg_limit, since, include_threads):
                yield doc

    async def health(self) -> SourceStatus:
        present = shutil.which("slackcli") is not None
        authed = False
        error: str | None = None

        if present:
            try:
                await _slackcli("auth", "status")
                authed = True
            except AuthError as exc:
                error = str(exc)
            except PluginError as exc:
                error = str(exc)

        return SourceStatus(
            name=self.name,
            enabled=self.config.get("enabled", True),
            cli_available=present,
            authenticated=authed,
            error=error,
        )

    async def reauth(self) -> None:
        """Launch slackcli interactive browser token capture."""
        if shutil.which("slackcli") is None:
            raise CLINotFoundError("slackcli is not installed.")
        print(
            "\nTo re-authenticate Slack:\n"
            "1. Open your Slack workspace in a browser.\n"
            "2. Open DevTools → Network tab → find any API request → Copy as cURL.\n"
            "3. Run:  slackcli auth parse-curl --login\n"
            "4. Paste the cURL command when prompted.\n"
        )
        proc = await asyncio.create_subprocess_exec("slackcli", "auth", "parse-curl", "--login")
        await proc.communicate()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _resolve_channels(self) -> list[tuple[str, str]]:
        """Return list of (channel_id, channel_name) to index."""
        explicit: list[str] = self.config.get("channels", [])
        max_ch = int(self.config.get("max_channels", 20))

        raw = await _slackcli("channel", "list", "--output", "json")
        all_channels: list[dict] = json.loads(raw) if raw else []

        # slackcli channel list may return list directly or wrapped
        if isinstance(all_channels, dict):
            all_channels = all_channels.get("channels", [])

        pairs: list[tuple[str, str]] = []
        for ch in all_channels:
            ch_id = ch.get("id", "")
            ch_name = ch.get("name", "")
            if not ch_id:
                continue
            if explicit:
                if ch_name in explicit:
                    pairs.append((ch_id, ch_name))
            else:
                # Skip private channels and DMs unless configured
                is_private = ch.get("is_private", False)
                is_im = ch.get("is_im", False)
                if is_im and not self.config.get("include_dms", False):
                    continue
                if not is_private:  # public only by default
                    pairs.append((ch_id, ch_name))

            if not explicit and len(pairs) >= max_ch:
                break

        return pairs

    async def _fetch_channel(
        self,
        ch_id: str,
        ch_name: str,
        limit: int,
        since: datetime | None,
        include_threads: bool,
    ) -> AsyncIterator[Document]:
        oldest = str(since.timestamp()) if since else "0"
        try:
            raw = await _slackcli(
                "message",
                "list",
                "--channel",
                ch_id,
                "--limit",
                str(limit),
                "--oldest",
                oldest,
                "--output",
                "json",
            )
        except AuthError:
            raise
        except PluginError:
            return  # channel not accessible, skip

        messages: list[dict] = json.loads(raw) if raw else []
        if isinstance(messages, dict):
            messages = messages.get("messages", [])

        workspace = self.config.get("workspace", "")

        for msg in messages:
            ts = msg.get("ts", "")
            user = msg.get("user") or msg.get("username", "")
            text = _strip_slack_markup(msg.get("text", ""))
            thread_ts = msg.get("thread_ts")
            is_parent = thread_ts == ts

            url = ""
            if workspace and ts:
                ts_clean = ts.replace(".", "")
                url = f"https://{workspace}.slack.com/archives/{ch_id}/p{ts_clean}"

            doc = Document(
                source="slack",
                source_id=f"{ch_id}:{ts}",
                doc_type="thread"
                if (include_threads and is_parent and int(msg.get("reply_count", 0)) > 0)
                else "message",
                title=f"#{ch_name}: {text[:80]}{'...' if len(text) > 80 else ''}",
                content=text,
                url=url,
                author=user,
                created_at=_utc_from_ts(ts),
                updated_at=_utc_from_ts(ts),
                metadata={
                    "channel_id": ch_id,
                    "channel_name": ch_name,
                    "ts": ts,
                    "thread_ts": thread_ts,
                    "reply_count": msg.get("reply_count", 0),
                },
            )
            yield doc

            # Fetch thread replies
            if include_threads and is_parent and int(msg.get("reply_count", 0)) > 0:
                try:
                    raw_replies = await _slackcli(
                        "message",
                        "replies",
                        "--channel",
                        ch_id,
                        "--ts",
                        ts,
                        "--output",
                        "json",
                    )
                    replies: list[dict] = json.loads(raw_replies) if raw_replies else []
                    if isinstance(replies, dict):
                        replies = replies.get("messages", [])

                    # Skip first element (parent message)
                    for reply in replies[1:]:
                        r_ts = reply.get("ts", "")
                        r_user = reply.get("user") or reply.get("username", "")
                        r_text = _strip_slack_markup(reply.get("text", ""))
                        r_url = ""
                        if workspace and r_ts:
                            r_ts_clean = r_ts.replace(".", "")
                            r_url = f"https://{workspace}.slack.com/archives/{ch_id}/p{r_ts_clean}"

                        yield Document(
                            source="slack",
                            source_id=f"{ch_id}:{r_ts}",
                            doc_type="message",
                            title=f"#{ch_name} (reply): {r_text[:80]}{'...' if len(r_text) > 80 else ''}",
                            content=r_text,
                            url=r_url,
                            author=r_user,
                            created_at=_utc_from_ts(r_ts),
                            updated_at=_utc_from_ts(r_ts),
                            metadata={
                                "channel_id": ch_id,
                                "channel_name": ch_name,
                                "ts": r_ts,
                                "thread_ts": ts,
                                "reply_count": 0,
                            },
                        )
                except (AuthError, PluginError):
                    pass
