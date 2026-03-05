"""GitHub plugin — indexes issues, PRs, and wiki pages via the gh CLI."""

from __future__ import annotations

import asyncio
import json
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


def _utc(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


async def _gh(*args: str, check: bool = True) -> str:
    """Run a gh CLI command and return stdout as a string.

    Raises:
        CLINotFoundError: ``gh`` is not installed.
        AuthError: ``gh`` returned an authentication error.
        PluginError: Any other non-zero exit code.
    """
    if shutil.which("gh") is None:
        raise CLINotFoundError("gh CLI is not installed. Install from https://cli.github.com/")

    proc = await asyncio.create_subprocess_exec(
        "gh",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    out = stdout.decode().strip()
    err = stderr.decode().strip()

    if proc.returncode != 0:
        if "authentication" in err.lower() or "not logged in" in err.lower():
            raise AuthError(f"gh CLI not authenticated: {err}")
        if check:
            raise PluginError(f"gh exited {proc.returncode}: {err}")

    return out


@register
class GitHubPlugin(BasePlugin):
    """Indexes GitHub issues, pull requests, and repository wikis.

    Config keys (all optional):
        repos (list[str]): Explicit list of "owner/repo" strings to index.
            If omitted, indexes all repos the user has access to (up to
            ``max_repos``).
        max_repos (int): Cap on number of repos fetched when ``repos`` is
            not specified. Default: 50.
        include_issues (bool): Index issues. Default: true.
        include_prs (bool): Index pull requests. Default: true.
        include_wiki (bool): Index GitHub wiki pages. Default: false.
        issues_limit (int): Max issues per repo. Default: 200.
        prs_limit (int): Max PRs per repo. Default: 200.
        state (str): Issue/PR state filter — "open", "closed", or "all".
            Default: "all".
    """

    name = "github"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def fetch(self, since: datetime | None = None) -> AsyncIterator[Document]:  # type: ignore[override]
        repos = await self._resolve_repos()
        include_issues = self.config.get("include_issues", True)
        include_prs = self.config.get("include_prs", True)
        include_wiki = self.config.get("include_wiki", False)

        for repo in repos:
            if include_issues:
                async for doc in self._fetch_issues(repo, since):
                    yield doc
            if include_prs:
                async for doc in self._fetch_prs(repo, since):
                    yield doc
            if include_wiki:
                async for doc in self._fetch_wiki(repo):
                    yield doc

    async def health(self) -> SourceStatus:
        name = self.name
        gh_present = shutil.which("gh") is not None
        if not gh_present:
            return SourceStatus(
                name=name,
                enabled=self.config.get("enabled", True),
                cli_available=False,
                authenticated=False,
                error="gh CLI not installed",
            )

        authed = False
        error: str | None = None
        try:
            await _gh("auth", "status")
            authed = True
        except AuthError as exc:
            error = str(exc)
        except PluginError as exc:
            error = str(exc)

        return SourceStatus(
            name=name,
            enabled=self.config.get("enabled", True),
            cli_available=True,
            authenticated=authed,
            error=error,
        )

    async def reauth(self) -> None:
        """Launch interactive gh login."""
        if shutil.which("gh") is None:
            raise CLINotFoundError("gh CLI not installed")
        proc = await asyncio.create_subprocess_exec("gh", "auth", "login")
        await proc.communicate()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_repos(self) -> list[str]:
        explicit = self.config.get("repos")
        if explicit:
            return list(explicit)

        max_repos = int(self.config.get("max_repos", 50))
        raw = await _gh(
            "repo",
            "list",
            "--limit",
            str(max_repos),
            "--json",
            "nameWithOwner",
        )
        items = json.loads(raw) if raw else []
        return [r["nameWithOwner"] for r in items]

    async def _fetch_issues(self, repo: str, since: datetime | None) -> AsyncIterator[Document]:
        limit = int(self.config.get("issues_limit", 200))
        state = self.config.get("state", "all")
        fields = "number,title,body,url,author,createdAt,updatedAt,state,labels,assignees,milestone"

        raw = await _gh(
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            fields,
        )
        items: list[dict] = json.loads(raw) if raw else []

        for item in items:
            updated = _utc(item.get("updatedAt"))
            if since and updated and updated <= since:
                continue

            labels = [lbl["name"] for lbl in item.get("labels", [])]
            assignees = [a["login"] for a in item.get("assignees", [])]
            milestone = (item.get("milestone") or {}).get("title")

            doc = Document(
                source="github",
                source_id=f"{repo}#issue#{item['number']}",
                doc_type="issue",
                title=f"[{repo}] #{item['number']}: {item['title']}",
                content=item.get("body") or "",
                url=item.get("url"),
                author=item.get("author", {}).get("login") if item.get("author") else None,
                created_at=_utc(item.get("createdAt")),
                updated_at=updated,
                metadata={
                    "repo": repo,
                    "number": item["number"],
                    "state": item.get("state"),
                    "labels": labels,
                    "assignees": assignees,
                    "milestone": milestone,
                },
            )
            yield doc

    async def _fetch_prs(self, repo: str, since: datetime | None) -> AsyncIterator[Document]:
        limit = int(self.config.get("prs_limit", 200))
        state = self.config.get("state", "all")
        fields = "number,title,body,url,author,createdAt,updatedAt,state,labels,reviewRequests,mergedAt,baseRefName,headRefName"

        raw = await _gh(
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            fields,
        )
        items: list[dict] = json.loads(raw) if raw else []

        for item in items:
            updated = _utc(item.get("updatedAt"))
            if since and updated and updated <= since:
                continue

            labels = [lbl["name"] for lbl in item.get("labels", [])]
            reviewers = [
                r.get("requestedReviewer", {}).get("login", "")
                for r in item.get("reviewRequests", [])
            ]

            doc = Document(
                source="github",
                source_id=f"{repo}#pr#{item['number']}",
                doc_type="pr",
                title=f"[{repo}] PR #{item['number']}: {item['title']}",
                content=item.get("body") or "",
                url=item.get("url"),
                author=item.get("author", {}).get("login") if item.get("author") else None,
                created_at=_utc(item.get("createdAt")),
                updated_at=updated,
                metadata={
                    "repo": repo,
                    "number": item["number"],
                    "state": item.get("state"),
                    "labels": labels,
                    "reviewers": reviewers,
                    "merged_at": item.get("mergedAt"),
                    "base_branch": item.get("baseRefName"),
                    "head_branch": item.get("headRefName"),
                },
            )
            yield doc

    async def _fetch_wiki(self, repo: str) -> AsyncIterator[Document]:
        """Fetch wiki pages via gh api (GitHub REST API)."""
        # GitHub doesn't expose wiki via REST/GraphQL directly; clone instead
        # We use `gh repo clone` to a temp dir and read .md files.
        # This is best-effort; skip if wiki doesn't exist.
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_url = f"{repo}.wiki"
            try:
                await _gh("repo", "clone", wiki_url, tmpdir, "--", "--depth=1")
            except PluginError:
                return  # wiki doesn't exist or is disabled

            for md_file in Path(tmpdir).glob("**/*.md"):
                try:
                    text = md_file.read_text(errors="replace")
                except OSError:
                    continue

                page_name = md_file.stem.replace("-", " ").replace("_", " ")
                doc = Document(
                    source="github",
                    source_id=f"{repo}#wiki#{md_file.stem}",
                    doc_type="wiki",
                    title=f"[{repo}] Wiki: {page_name}",
                    content=text,
                    url=f"https://github.com/{repo}/wiki/{md_file.stem}",
                    metadata={"repo": repo, "page": md_file.stem},
                )
                yield doc
