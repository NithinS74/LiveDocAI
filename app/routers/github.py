"""
GitHub Integration Router v2
─────────────────────────────
Endpoints:
  POST /api/github/repo          — fetch repo info + recent commits
  POST /api/github/analyze       — read code + diff + generate docs  
  POST /api/github/create-pr     — open real PR with generated docs
  POST /api/github/webhook       — receives GitHub push events
  GET  /api/github/history       — doc generation history for user
  GET  /api/github/dashboard     — stats: repos, PRs, drift events
"""

import re
import httpx
import base64
import json
import logging
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from pydantic import BaseModel
from typing import Optional, Literal, List
from datetime import datetime

from app.database import get_db

router = APIRouter(prefix="/api/github", tags=["GitHub"])
logger = logging.getLogger(__name__)


# ── Models ────────────────────────────────────────────────────────────────────

class RepoRequest(BaseModel):
    repo_url: str
    token: Optional[str] = None

class AnalyzeRequest(BaseModel):
    owner: str
    repo: str
    token: str
    doc_target: Literal["readme", "documentation_md", "custom"]
    custom_path: Optional[str] = None
    user_email: Optional[str] = None

class CreatePRRequest(BaseModel):
    owner: str
    repo: str
    token: str
    doc_target: Literal["readme", "documentation_md", "custom"]
    custom_path: Optional[str] = None
    generated_docs: str
    files_analyzed: Optional[List[str]] = []
    drift_detected: Optional[str] = "UNKNOWN"
    drift_summary: Optional[str] = None
    commit_sha: Optional[str] = None
    branch_name: Optional[str] = "livedocai/update-docs"
    user_email: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_repo_url(url: str):
    url = url.strip().rstrip("/")
    match = re.search(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?$", url)
    if match:
        return match.group(1), match.group(2)
    match = re.match(r"^([^/]+)/([^/]+)$", url)
    if match:
        return match.group(1), match.group(2)
    return None, None


def get_target_path(doc_target: str, custom_path: Optional[str]) -> str:
    if doc_target == "readme":
        return "README.md"
    if doc_target == "documentation_md":
        return "DOCUMENTATION.md"
    if doc_target == "custom" and custom_path:
        match = re.search(r"github\.com/[^/]+/[^/]+/blob/[^/]+/(.+)$", custom_path)
        if match:
            return match.group(1)
        return custom_path.strip("/")
    return "DOCUMENTATION.md"


def gh_headers(token: Optional[str]) -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "LiveDocAI/1.0",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/repo")
async def get_repo_info(body: RepoRequest):
    """Fetch repo info + recent commits. Proxied to avoid CORS."""
    owner, repo = parse_repo_url(body.repo_url)
    if not owner or not repo:
        raise HTTPException(status_code=400,
            detail="Invalid GitHub URL. Use: https://github.com/username/repo-name")

    headers = gh_headers(body.token)
    async with httpx.AsyncClient(timeout=15.0) as client:
        repo_res = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}", headers=headers)

        if repo_res.status_code == 404:
            raise HTTPException(status_code=404, detail="Repository not found.")
        if repo_res.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid token.")
        if repo_res.status_code == 403:
            rate = repo_res.headers.get("x-ratelimit-remaining", "unknown")
            if rate == "0":
                raise HTTPException(status_code=403,
                    detail="GitHub API rate limit exceeded. Add a Personal Access Token.")
            raise HTTPException(status_code=403,
                detail="Access denied. Add a Personal Access Token with 'repo' scope.")
        if not repo_res.is_success:
            try: err = repo_res.json().get("message", repo_res.text[:200])
            except: err = repo_res.text[:200]
            raise HTTPException(status_code=repo_res.status_code, detail=f"GitHub: {err}")

        repo_data = repo_res.json()
        commits_res = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=5",
            headers=headers)
        commits_data = commits_res.json() if commits_res.is_success else []

    return {"owner": owner, "repo": repo, "repo_info": repo_data, "commits": commits_data}


@router.post("/analyze")
async def analyze_repo(body: AnalyzeRequest):
    """
    Read code from GitHub + detect diff-based drift + generate docs.
    This is the core intelligence endpoint.
    """
    headers = gh_headers(body.token)
    owner, repo = body.owner, body.repo

    async with httpx.AsyncClient(timeout=30.0) as client:

        # ── Get repo tree ─────────────────────────────────────
        tree_res = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1",
            headers=headers)
        if not tree_res.is_success:
            raise HTTPException(status_code=tree_res.status_code,
                detail="Could not read repo. Make sure the token has 'repo' scope.")
        tree = tree_res.json().get("tree", [])

        # ── Select best files to read ─────────────────────────
        code_extensions = {'.py','.js','.ts','.jsx','.tsx','.go','.java','.rb','.php','.cs','.rs'}
        skip_dirs = ["node_modules","venv",".venv",".git","dist","build",
                     "__pycache__",".next","coverage",".pytest_cache","migrations",
                     "static","assets","images","fonts","test","tests","__tests__"]

        scored_files = []
        for item in tree:
            if item.get("type") != "blob": continue
            path = item.get("path", "")
            ext = "." + path.split(".")[-1] if "." in path else ""
            name = path.split("/")[-1].lower()
            if any(skip in path.split("/") for skip in skip_dirs): continue
            if ext not in code_extensions: continue
            depth = path.count("/")
            score = 10 - depth
            priority = ['app','main','server','index','route','router','api','handler',
                        'controller','view','endpoint','model','schema','dashboard','core']
            if any(kw in name for kw in priority):
                score += 5
            scored_files.append((score, path))

        scored_files.sort(key=lambda x: x[0], reverse=True)
        candidate_files = [p for _, p in scored_files[:8]]

        # Always include dependency files
        for dep_file in ['requirements.txt','package.json','pyproject.toml','go.mod','Cargo.toml']:
            for item in tree:
                if item.get("path") == dep_file and dep_file not in candidate_files:
                    candidate_files.insert(0, dep_file)

        # ── Read file contents ────────────────────────────────
        file_contents = {}
        for path in candidate_files:
            try:
                r = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
                    headers=headers)
                if r.is_success:
                    decoded = base64.b64decode(
                        r.json().get("content","")).decode("utf-8", errors="replace")
                    file_contents[path] = decoded[:3000]
            except: continue

        # ── Read existing README ──────────────────────────────
        readme_content = ""
        try:
            r = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/readme", headers=headers)
            if r.is_success:
                readme_content = base64.b64decode(
                    r.json().get("content","")).decode("utf-8", errors="replace")[:3000]
        except: pass

        # ── Get latest 2 commits for diff detection ───────────
        commits_res = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=2",
            headers=headers)
        commits = commits_res.json() if commits_res.is_success else []
        latest_sha  = commits[0]["sha"] if len(commits) > 0 else None
        prev_sha    = commits[1]["sha"] if len(commits) > 1 else None

        # ── Get diff between last 2 commits ───────────────────
        diff_summary = ""
        if latest_sha and prev_sha:
            try:
                diff_res = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/compare/{prev_sha}...{latest_sha}",
                    headers={**headers, "Accept": "application/vnd.github.v3.diff"})
                if diff_res.is_success:
                    diff_text = diff_res.text[:3000]
                    # Count changed files
                    changed = [l for l in diff_text.split("\n") if l.startswith("diff --git")]
                    diff_summary = f"{len(changed)} file(s) changed in latest commit.\n" + diff_text[:1500]
            except: pass

        # ── Get repo info ─────────────────────────────────────
        repo_res = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
        repo_info = repo_res.json() if repo_res.is_success else {}

    # ── AI: Detect drift between code and existing docs ───────
    from app.services.ai_service import get_llm
    # Groq if available (fast + high quota), else Gemini fallback
    llm = get_llm(use_gemini=True)

    async def invoke(prompt: str) -> str:
        result = await llm.ainvoke(prompt)
        return result.content if hasattr(result, 'content') else str(result)

    # Drift detection — compare existing README vs actual code
    drift_detected = "NO"
    drift_summary_text = None

    if readme_content and file_contents and diff_summary:
        drift_prompt = f"""You are analyzing whether documentation is outdated compared to the actual code.

Repository: {owner}/{repo}
Latest commit changes:
{diff_summary[:1000]}

Existing README/docs:
{readme_content[:1000]}

Current code files:
{list(file_contents.keys())}

Answer EXACTLY:
DRIFT: YES or NO
REASON: one sentence explaining what changed that makes docs outdated, or "Documentation appears up to date"
"""
        drift_reply = (await invoke(drift_prompt)).strip()
        if "DRIFT: YES" in drift_reply.upper():
            drift_detected = "YES"
            if "REASON:" in drift_reply:
                drift_summary_text = drift_reply.split("REASON:", 1)[-1].strip()
        else:
            drift_detected = "NO"

    # ── Generate documentation in 3 focused steps ─────────────
    proj_name = repo_info.get('name', repo)
    proj_desc = repo_info.get('description', '')
    proj_lang = repo_info.get('language', 'Unknown')
    proj_url  = f"https://github.com/{owner}/{repo}"

    deps_content = (file_contents.get('requirements.txt','') or
                   file_contents.get('package.json','') or
                   file_contents.get('pyproject.toml',''))
    deps_lines = [l.strip() for l in deps_content.split('\n')
                  if l.strip() and not l.startswith('#')][:20]
    deps_str = ', '.join(deps_lines) if deps_lines else 'Not found'

    code_section = "\n\n".join([
        f"### {path}\n```\n{code[:1500]}\n```"
        for path, code in list(file_contents.items())[:5]
        if path not in ['requirements.txt','package.json','pyproject.toml']
    ]) or "No source files found."

    file_list = list(file_contents.keys())

    # Single Gemini call — consolidate to avoid rate limits (free tier: 5 req/min)
    proj_name = repo_info.get('name', repo)
    proj_desc = repo_info.get('description', '')
    proj_lang = repo_info.get('language', 'Unknown')
    proj_url  = f"https://github.com/{owner}/{repo}"

    deps_content = (file_contents.get('requirements.txt','') or
                   file_contents.get('package.json','') or
                   file_contents.get('pyproject.toml',''))
    deps_lines = [l.strip() for l in deps_content.split('\n')
                  if l.strip() and not l.startswith('#')][:20]
    deps_str = ', '.join(deps_lines) if deps_lines else 'Not found'

    code_section = "\n\n".join([
        f"### {path}\n```\n{code[:2000]}\n```"
        for path, code in list(file_contents.items())[:6]
        if path not in ['requirements.txt','package.json','pyproject.toml']
    ]) or "No source files found."

    file_list = list(file_contents.keys())

    # One comprehensive prompt instead of 3 separate calls
    full_prompt = f"""You are a senior technical writer. Write professional, modern documentation for this project.

PROJECT: {proj_name}
DESCRIPTION: {proj_desc}
LANGUAGE: {proj_lang}
REPO: {proj_url}
DEPENDENCIES: {deps_str}
FILES: {', '.join(file_list)}

SOURCE CODE:
{code_section[:4000]}

EXISTING README:
{readme_content[:1500] if readme_content else 'None'}

Write a complete README.md following this EXACT structure:

<div align="center">

# {proj_name}

> {proj_desc or 'A powerful development tool.'}

![Language](https://img.shields.io/badge/{proj_lang}-blue?style=for-the-badge)
![GitHub Stars](https://img.shields.io/github/stars/{owner}/{repo}?style=for-the-badge)

</div>

---

## 📋 Table of Contents
- [Overview](#-overview)
- [Features](#-features)
- [Getting Started](#-getting-started)
- [Usage](#-usage)
- [Project Structure](#-project-structure)
- [Tech Stack](#️-tech-stack)
- [Contributing](#-contributing)

---

## 🎯 Overview
[Write 2-3 paragraphs based on actual code: what it does, who it's for, what problem it solves]

## ✨ Features
[6-8 bullet points with emoji — extract REAL features from the source code]
- 🔥 **Feature** — description

## 🚀 Getting Started

### Prerequisites
[Based on actual language/deps found]

### Installation
```bash
[Exact correct commands]
```

### Quick Start
```bash
[Exact command to run based on code]
```

## 📖 Usage
[2-3 concrete examples based on actual code]

## 📁 Project Structure
```
{proj_name}/
[List actual files with comments]
```

## 🛠️ Tech Stack
| Technology | Version | Purpose |
|-----------|---------|---------|
[From actual deps]

## ⚙️ Configuration
[Only if env vars found in code]

## 🤝 Contributing
1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

<div align="center">
*Documentation auto-generated by [LiveDocAI](https://github.com) — Production-Aware API Intelligence*
</div>

Output ONLY the Markdown. No explanation before or after."""

    full_doc = await invoke(full_prompt)

    # Build final doc with drift info
    drift_section = ""
    if drift_detected == "YES" and drift_summary_text:
        drift_section = f"""
---

## ⚠️ Documentation Drift Detected

> {drift_summary_text}

*This documentation was auto-regenerated by LiveDocAI to reflect the latest code changes.*

---
"""

    generated_docs = full_doc.strip() + drift_section
    return {
        "generated_docs":   generated_docs.strip(),
        "files_analyzed":   file_list,
        "owner":            owner,
        "repo":             repo,
        "drift_detected":   drift_detected,
        "drift_summary":    drift_summary_text,
        "commit_sha":       latest_sha,
        "prev_commit_sha":  prev_sha,
    }


@router.post("/create-pr")
async def create_pull_request(body: CreatePRRequest, db: AsyncSession = Depends(get_db)):
    """Create a branch, commit the docs, and open a PR."""
    headers = gh_headers(body.token)
    owner, repo = body.owner, body.repo
    file_path = get_target_path(body.doc_target, body.custom_path)
    branch = body.branch_name or "livedocai/update-docs"

    async with httpx.AsyncClient(timeout=30.0) as client:

        # Get default branch + latest SHA
        repo_res = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
        if not repo_res.is_success:
            raise HTTPException(status_code=400, detail="Could not fetch repo info.")
        default_branch = repo_res.json().get("default_branch", "main")

        ref_res = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{default_branch}",
            headers=headers)
        if not ref_res.is_success:
            raise HTTPException(status_code=400,
                detail=f"Could not get branch '{default_branch}'.")
        base_sha = ref_res.json()["object"]["sha"]

        # Create branch (ignore 422 = already exists)
        await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch}", "sha": base_sha})

        # Get existing file SHA if file exists
        file_sha = None
        existing = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}?ref={branch}",
            headers=headers)
        if existing.is_success:
            file_sha = existing.json().get("sha")

        # Commit the file
        content_b64 = base64.b64encode(body.generated_docs.encode("utf-8")).decode("utf-8")
        payload = {
            "message": f"docs: update {file_path} via LiveDocAI 🤖",
            "content": content_b64,
            "branch":  branch,
        }
        if file_sha:
            payload["sha"] = file_sha

        file_res = await client.put(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}",
            headers=headers, json=payload)
        if not file_res.is_success:
            raise HTTPException(status_code=400,
                detail=f"Could not write file: {file_res.text[:300]}")

        # Open PR
        drift_note = ""
        if body.drift_detected == "YES" and body.drift_summary:
            drift_note = f"\n\n> ⚠️ **Drift detected:** {body.drift_summary}"

        pr_res = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls",
            headers=headers,
            json={
                "title": f"docs: LiveDocAI — production-aware documentation update 🤖",
                "body": (
                    f"## 📄 Automated Documentation Update\n\n"
                    f"This PR was automatically generated by **LiveDocAI**.\n\n"
                    f"**What was analyzed:**\n"
                    f"- ✅ Source code structure and logic\n"
                    f"- ✅ Dependencies and tech stack\n"
                    f"- ✅ Diff between recent commits\n"
                    f"- ✅ Existing documentation vs current code{drift_note}\n\n"
                    f"**File updated:** `{file_path}`\n"
                    f"**Files analyzed:** {', '.join(f'`{f}`' for f in (body.files_analyzed or [])[:5])}\n\n"
                    f"*Review and merge to keep your docs production-aware.* 🚀"
                ),
                "head":  branch,
                "base":  default_branch,
            })

        if pr_res.status_code == 422:
            return {
                "success":  True,
                "message":  "PR already exists for this branch.",
                "pr_url":   f"https://github.com/{owner}/{repo}/pulls",
                "pr_number": None,
            }

        if not pr_res.is_success:
            raise HTTPException(status_code=400,
                detail=f"Could not create PR: {pr_res.text[:300]}")

        pr_data = pr_res.json()
        pr_url  = pr_data.get("html_url")
        pr_number = pr_data.get("number")

    # ── Save to doc_history ───────────────────────────────────
    try:
        from app.models.doc_history import DocHistory
        history = DocHistory(
            user_email     = body.user_email or "unknown",
            owner          = owner,
            repo           = repo,
            repo_url       = f"https://github.com/{owner}/{repo}",
            doc_target     = body.doc_target,
            file_path      = file_path,
            pr_url         = pr_url,
            pr_number      = pr_number,
            branch         = branch,
            generated_docs = body.generated_docs[:5000],
            files_analyzed = body.files_analyzed or [],
            drift_detected = body.drift_detected,
            drift_summary  = body.drift_summary,
            commit_sha     = body.commit_sha,
            trigger        = "manual",
            status         = "success",
        )
        db.add(history)
        await db.commit()
    except Exception as e:
        logger.error(f"[GitHub] Failed to save doc history: {e}")

    return {
        "success":    True,
        "pr_url":     pr_url,
        "pr_number":  pr_number,
        "branch":     branch,
        "file_path":  file_path,
    }


@router.get("/history")
async def get_doc_history(
    user_email: str = Query(...),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Returns doc generation history for a user."""
    try:
        from app.models.doc_history import DocHistory
        result = await db.execute(
            select(DocHistory)
            .where(DocHistory.user_email == user_email)
            .order_by(desc(DocHistory.created_at))
            .limit(limit)
        )
        rows = result.scalars().all()
        return [{
            "id":            r.id,
            "owner":         r.owner,
            "repo":          r.repo,
            "repo_url":      r.repo_url,
            "doc_target":    r.doc_target,
            "file_path":     r.file_path,
            "pr_url":        r.pr_url,
            "pr_number":     r.pr_number,
            "drift_detected": r.drift_detected,
            "drift_summary": r.drift_summary,
            "commit_sha":    r.commit_sha,
            "trigger":       r.trigger,
            "status":        r.status,
            "created_at":    r.created_at.isoformat() if r.created_at else None,
        } for r in rows]
    except Exception as e:
        logger.error(f"[GitHub] history error: {e}")
        return []


@router.get("/dashboard")
async def get_github_dashboard(
    user_email: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Returns dashboard stats for the GitHub tab."""
    try:
        from app.models.doc_history import DocHistory
        from sqlalchemy import distinct

        total_prs = await db.execute(
            select(func.count()).select_from(DocHistory)
            .where(DocHistory.user_email == user_email)
            .where(DocHistory.pr_url != None)
        )
        repos_result = await db.execute(
            select(DocHistory.owner, DocHistory.repo)
            .where(DocHistory.user_email == user_email)
            .distinct()
        )
        drift_count = await db.execute(
            select(func.count()).select_from(DocHistory)
            .where(DocHistory.user_email == user_email)
            .where(DocHistory.drift_detected == "YES")
        )
        recent = await db.execute(
            select(DocHistory)
            .where(DocHistory.user_email == user_email)
            .order_by(desc(DocHistory.created_at))
            .limit(10)
        )
        recent_rows = recent.scalars().all()

        repos_list = [{"owner": r.owner, "repo": r.repo} for r in repos_result]
        unique_repos = list({f"{r['owner']}/{r['repo']}": r for r in repos_list}.values())

        return {
            "total_prs_opened":    total_prs.scalar() or 0,
            "repos_connected":     len(unique_repos),
            "drift_events":        drift_count.scalar() or 0,
            "repos":               unique_repos,
            "recent_activity":     [{
                "id":            r.id,
                "owner":         r.owner,
                "repo":          r.repo,
                "file_path":     r.file_path,
                "pr_url":        r.pr_url,
                "pr_number":     r.pr_number,
                "drift_detected": r.drift_detected,
                "trigger":       r.trigger,
                "status":        r.status,
                "created_at":    r.created_at.isoformat() if r.created_at else None,
            } for r in recent_rows],
        }
    except Exception as e:
        logger.error(f"[GitHub] dashboard error: {e}")
        return {
            "total_prs_opened": 0,
            "repos_connected":  0,
            "drift_events":     0,
            "repos":            [],
            "recent_activity":  [],
        }


@router.post("/webhook")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receives GitHub push webhook events."""
    payload = await request.body()
    event = request.headers.get("X-GitHub-Event", "")
    if event != "push":
        return {"status": "ignored", "event": event}
    try:
        data = json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    repo_full = data.get("repository", {}).get("full_name", "unknown")
    branch    = data.get("ref", "").replace("refs/heads/", "")
    commits   = data.get("commits", [])
    logger.info(f"[Webhook] Push to {repo_full}:{branch} — {len(commits)} commit(s)")
    return {"status": "received", "repo": repo_full, "branch": branch, "commits": len(commits)}


async def _get_traffic_summary() -> str:
    try:
        from app.database import AsyncSessionLocal
        from app.services.endpoint_service import EndpointService
        async with AsyncSessionLocal() as db:
            ep_svc = EndpointService(db)
            endpoints = await ep_svc.list_all()
            lines = ["Endpoints from real production traffic:"]
            for ep in endpoints[:10]:
                drift = " [DRIFT]" if ep.has_drift else ""
                lines.append(
                    f"  {ep.method} {ep.path_pattern} — "
                    f"{ep.total_requests} reqs, {ep.avg_latency_ms:.0f}ms avg{drift}"
                )
            return "\n".join(lines) if len(lines) > 1 else "No traffic data yet."
    except Exception as e:
        return f"Traffic data unavailable: {e}"
