#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""harvest-skills.py —— 拿来主义：为指定工具去开源社区收割成熟 Agent Skill。

对每台新机器 / 每个新工具，先去 GitHub 找现成的 SKILL.md（社区已踩过坑的
成熟技能），审一遍（许可证 / 热度 / 安全扫描），落盘到技能目录 ——
找不到合适的才自己写。

用法:
  harvest-skills.py remotion lmms           # 为两个工具各收割最佳 1 个
  harvest-skills.py rdkit --dry-run         # 只列候选，不安装
  harvest-skills.py rdkit --all             # 安装所有通过安检的候选
  harvest-skills.py --from-contract         # 读路径契约，为链上工具逐个收割
  harvest-skills.py remotion --force        # 覆盖已存在的同名 skill

流程（每个工具）:
  ① GitHub code search: filename:SKILL.md <tool>   （无 token 时退化到仓库搜索）
  ② 候选去重 → 拉仓库元数据（stars / license / 是否归档 / 最近推送）
  ③ 拉 SKILL.md 解析 frontmatter（name / description）
  ④ 评分排序 → 逐候选安全扫描（危险模式 → 隔离区，换下一个）
  ⑤ 落盘 <dest>/<name>/ + _PROVENANCE.md（来源凭证）→ 记 install-manifest.jsonl

环境事实（本机实测，写死为默认行为）:
  - api.github.com 可达；raw.githubusercontent.com 被拦 → 一律走 contents API
    + `Accept: application/vnd.github.raw`。
  - 未认证限速 60 次/小时；有 `gh auth token` 或 GITHUB_TOKEN 时用认证通道
    （code search API 本身也要求认证）。
  - codeload 大包会被杀 → 不打 tarball，逐文件走 contents API（skill 都很小）。

退出码: 0 = 至少装了一个（或 dry-run 正常跑完）；1 = 什么都没装上；2 = 用法错误。
"""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
UA = "ideaform-harvest/1.0"

SKILLS_DEST = os.path.expanduser(os.environ.get("SKILLS_DEST", "~/.workbuddy/skills"))
QUAR_DIRNAME = "_quarantine"
UPSTREAM_DIRNAME = "_upstream"   # 本地已进化 skill 的上游新版 / 强刷前备份 的存放处
CONFIG_ROOT = os.path.expanduser(os.environ.get("VW_CONFIG_ROOT", "~/.config/ideaform"))
MANIFEST = os.path.join(CONFIG_ROOT, "install-manifest.jsonl")

# 单个文件 / 整个 skill 的体积护栏（字节）。skill 是文本资产，超了基本不是 skill。
MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 5 * 1024 * 1024

# 契约工具名 → 搜索词（太泛的词不配默认搜索词，宁可不搜也别捞垃圾）
CONTRACT_SEARCH_TERMS = {
    "remotion": ["remotion"],
    "lmms": ["lmms"],
    "ffmpeg": ["ffmpeg"],
    "edge-tts": ["edge-tts"],
    "rdkit": ["rdkit"],
}

# 安全扫描：命中即隔离。只列明确危险的模式，宁可漏报不可误报
# （误报会把好 skill 扔进隔离区，漏报的由用户自查兜底）。
DANGER_PATTERNS = [
    (re.compile(r"curl\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z|fi)?sh\b", re.I), "curl 管道进 shell"),
    (re.compile(r"wget\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z|fi)?sh\b", re.I), "wget 管道进 shell"),
    (re.compile(r"base64\s+(?:-d|--decode|-D)\b[^\n]*\|\s*(?:ba|z|fi)?sh\b", re.I), "base64 解码进 shell"),
    (re.compile(r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+(?:/|~|\$HOME)\b"), "rm -rf 根/家目录"),
    (re.compile(r"\bmkfs\.|\bdd\s+if=.*of=/dev/"), "磁盘毁灭命令"),
    (re.compile(r"(?:\.ssh/|id_rsa|\.aws/|\.gnupg/)"), "触碰凭据目录"),
    (re.compile(r"\bos\.environ\b[^\n]*(?:requests\.|urllib|http|curl|wget)", re.I), "环境变量外发嫌疑"),
    (re.compile(r"\bcurl\b[^\n]*\$\{?(?:AWS_|GITHUB_|GH_|OPENAI_|ANTHROPIC_)[A-Z_]*TOKEN", re.I), "token 外发嫌疑"),
]

TEXT_SUFFIXES = {".md", ".py", ".sh", ".ts", ".tsx", ".js", ".json", ".yaml",
                 ".yml", ".txt", ".toml", ".cfg", ".ini", ""}

_rate_remaining = None


def log(msg):
    print(msg, flush=True)


def get_token():
    """优先 gh CLI（本机已认证），退环境变量，再退未认证。"""
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True,
                           text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def http_get(path_or_url, token, raw=False):
    """GET GitHub API。返回 (status, bytes)。raw=True 时取原始文件内容。"""
    global _rate_remaining
    url = path_or_url if path_or_url.startswith("http") else API + path_or_url
    headers = {"User-Agent": UA,
               "Accept": "application/vnd.github.raw" if raw
                         else "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            rem = resp.headers.get("X-RateLimit-Remaining")
            if rem is not None:
                _rate_remaining = int(rem)
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        rem = e.headers.get("X-RateLimit-Remaining") if e.headers else None
        if rem is not None:
            _rate_remaining = int(rem)
        return e.code, b""


def api_json(path_or_url, token):
    status, body = http_get(path_or_url, token)
    if status != 200 or not body:
        return None
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- 搜索与评估

def search_code(tool, token, per_page=20):
    """filename:SKILL.md <tool>。无 token 时 code search 会 401，返回 None。"""
    q = urllib.parse.quote(f"filename:SKILL.md {tool}")
    data = api_json(f"/search/code?q={q}&per_page={per_page}", token)
    if not data or "items" not in data:
        return None
    return data["items"]


def search_repos_fallback(tool, token, per_page=10):
    """无认证退化方案：搜仓库名/描述，再探根目录有没有 SKILL.md。"""
    q = urllib.parse.quote(f"{tool} agent skill")
    data = api_json(f"/search/repositories?q={q}&per_page={per_page}", token)
    if not data or "items" not in data:
        return []
    items = []
    for repo in data["items"]:
        full = repo["full_name"]
        for cand in ("SKILL.md", "skill/SKILL.md", "skills/SKILL.md"):
            status, _ = http_get(f"/repos/{full}/contents/{cand}", token, raw=True)
            if status == 200:
                items.append({"path": cand, "repository": {"full_name": full}})
                break
    return items


def repo_meta(full, token):
    return api_json(f"/repos/{full}", token)


def head_sha(full, token, branch):
    data = api_json(f"/repos/{full}/git/ref/heads/{urllib.parse.quote(branch, safe='')}", token)
    if data and isinstance(data.get("object"), dict):
        return data["object"].get("sha", "")
    return ""


def parse_frontmatter(text):
    """极简 frontmatter 解析（不引 yaml 依赖）。返回 (name, description)。"""
    name = desc = ""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    block = m.group(1) if m else text[:2000]
    for line in block.splitlines():
        for key in ("name", "description"):
            km = re.match(rf"^{key}\s*:\s*(.+?)\s*$", line)
            if km and not (name if key == "name" else desc):
                val = km.group(1).strip().strip("'\"")
                if key == "name":
                    name = val
                else:
                    desc = val
    return name, desc


def score_candidate(meta, name, desc, tool):
    """越大越好。归档仓库在调用处已被淘汰，这里不打分。"""
    stars = meta.get("stargazers_count", 0) if meta else 0
    lic = (meta.get("license") or {}).get("spdx_id", "") if meta else ""
    s = math.log10(stars + 1) * 10
    if lic and lic != "NOASSERTION":
        s += 15
    haystack = f"{name} {desc}".lower()
    if tool.lower() in haystack:
        s += 10
    pushed = meta.get("pushed_at", "") if meta else ""
    if pushed:  # 18 个月内动过 +5
        try:
            dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - dt).days < 548:
                s += 5
        except ValueError:
            pass
    return s


# ---------------------------------------------------------------- 下载与安检

def fetch_dir_recursive(full, sdir, token):
    """递归拉取 skill 目录全部文件。返回 {相对路径: bytes} 或 None（超护栏）。"""
    files = {}
    total = 0
    queue = [sdir]
    while queue:
        cur = queue.pop(0)
        entries = api_json(f"/repos/{full}/contents/{urllib.parse.quote(cur)}", token)
        if not isinstance(entries, list):
            return None
        for e in entries:
            if e.get("type") == "dir":
                queue.append(e["path"])
            elif e.get("type") == "file":
                size = e.get("size", 0)
                if size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES:
                    return None
                status, body = http_get(
                    f"/repos/{full}/contents/{urllib.parse.quote(e['path'])}",
                    token, raw=True)
                if status != 200:
                    return None
                rel = os.path.relpath(e["path"], sdir) if sdir else e["path"]
                files[rel] = body
                total += len(body)
    return files


def security_scan(files):
    """返回 [(文件, 命中说明)]。空列表 = 通过。"""
    findings = []
    for rel, body in files.items():
        suffix = os.path.splitext(rel)[1].lower()
        if suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = body.decode("utf-8", "replace")
        except Exception:
            continue
        for pat, label in DANGER_PATTERNS:
            if pat.search(text):
                findings.append((rel, label))
    return findings


# ---------------------------------------------------------------- 落盘与记账

def write_skill(files, dest):
    os.makedirs(dest, exist_ok=True)
    for rel, body in files.items():
        p = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(p) or dest, exist_ok=True)
        with open(p, "wb") as f:
            f.write(body)


def write_harvest_marker(dest, *, tool, full, sdir, sha, files):
    """机器可读的分叉检测锚点：逐文件 SHA256 + 来源。_PROVENANCE.md 给人看，这个给脚本看。"""
    marker = {
        "tool": tool, "source": f"https://github.com/{full}",
        "path": sdir, "sha": sha,
        "harvested_at": datetime.now(timezone.utc).isoformat(),
        "files": {rel: hashlib.sha256(body).hexdigest() for rel, body in files.items()},
    }
    with open(os.path.join(dest, "_harvest.json"), "w", encoding="utf-8") as f:
        json.dump(marker, f, ensure_ascii=False, indent=2)


def divergence_state(dest):
    """clean=收割后没动过 | evolved=本地已进化 | foreign=不是本脚本落的（私产） | absent"""
    if not os.path.isdir(dest):
        return "absent"
    marker_path = os.path.join(dest, "_harvest.json")
    if not os.path.isfile(marker_path):
        return "foreign"
    try:
        marker = json.load(open(marker_path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "foreign"
    for rel, digest in (marker.get("files") or {}).items():
        p = os.path.join(dest, rel)
        if not os.path.isfile(p):
            return "evolved"          # 本地删过文件
        with open(p, "rb") as f:
            if hashlib.sha256(f.read()).hexdigest() != digest:
                return "evolved"      # 本地改过文件
    return "clean"


def write_provenance(dest, *, tool, full, sdir, meta, sha, files, verdict):
    skill_md = files.get("SKILL.md", b"")
    digest = hashlib.sha256(skill_md).hexdigest() if skill_md else "(无 SKILL.md)"
    stars = meta.get("stargazers_count", "?") if meta else "?"
    lic = (meta.get("license") or {}).get("spdx_id", "未知") if meta else "未知"
    lines = [
        "# _PROVENANCE.md —— 来源凭证（harvest-skills.py 生成）",
        "",
        f"- **收割对象工具**: {tool}",
        f"- **来源**: https://github.com/{full}/tree/HEAD/{sdir}".rstrip("/"),
        f"- **仓库**: {full}  stars={stars}  license={lic}",
        f"- **commit**: {sha or '(未取到)'}",
        f"- **收割时间**: {datetime.now(timezone.utc).isoformat()}",
        f"- **SKILL.md SHA256**: `{digest}`",
        f"- **安全扫描**: {verdict}",
        f"- **文件数**: {len(files)}（逐文件经 contents API 拉取）",
        "",
        "> 本目录是从开源社区收割的第三方 skill，许可证以仓库内 LICENSE 为准。",
        "> 升级 = 重跑 `harvest-skills.py <tool> --force`；卸载 = 删本目录。",
    ]
    with open(os.path.join(dest, "_PROVENANCE.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def manifest_append(entry):
    os.makedirs(CONFIG_ROOT, exist_ok=True)
    with open(MANIFEST, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 主流程

def harvest_one(tool, args, token):
    log(f"\n== 收割: {tool} ==")
    items = search_code(tool, token)
    if items is None:
        if not token:
            log("  （未认证，code search 不可用 → 退化到仓库搜索）")
            items = search_repos_fallback(tool, token)
        else:
            log("  ✗ code search 失败（网络/限速？）")
            return False
    if not items:
        log("  ✗ 没找到候选。这个工具可能真得自己写 skill 了。")
        return False

    # 去重：(repo, skill_dir)
    seen, cands = set(), []
    for it in items:
        full = it.get("repository", {}).get("full_name", "")
        path = it.get("path", "")
        sdir = os.path.dirname(path)
        key = (full, sdir)
        if not full or key in seen:
            continue
        seen.add(key)
        cands.append((full, sdir, path))
        if len(cands) >= args.limit:
            break

    #  enrich + 评分
    scored = []
    for full, sdir, path in cands:
        meta = repo_meta(full, token)
        if meta and meta.get("archived"):
            log(f"  - {full} 已归档，跳过")
            continue
        status, raw = http_get(f"/repos/{full}/contents/{urllib.parse.quote(path)}",
                               token, raw=True)
        if status != 200:
            continue
        name, desc = parse_frontmatter(raw.decode("utf-8", "replace"))
        if not name:
            name = os.path.basename(sdir) or full.split("/")[-1]
        s = score_candidate(meta, name, desc, tool)
        stars = meta.get("stargazers_count", "?") if meta else "?"
        lic = (meta.get("license") or {}).get("spdx_id", "-") if meta else "-"
        scored.append({"full": full, "sdir": sdir, "path": path, "meta": meta,
                       "name": name, "desc": desc, "score": s})
        log(f"  · {name:<28} {full:<44} ★{stars:<7} {lic:<12} 得分 {s:.1f}")
    if not scored:
        log("  ✗ 候选全部不可达。")
        return False
    scored.sort(key=lambda c: -c["score"])
    if args.min_stars:
        scored = [c for c in scored
                  if (c["meta"] or {}).get("stargazers_count", 0) >= args.min_stars]
    if args.dry_run:
        log("  （dry-run，不安装）")
        return True

    installed = False
    for c in scored:
        dest = os.path.join(SKILLS_DEST, c["name"])
        quar = os.path.join(SKILLS_DEST, QUAR_DIRNAME,
                            f"{c['name']}-{c['full'].replace('/', '__')}")
        if os.path.isdir(dest) and not args.force:
            log(f"  → {c['name']} 已存在，跳过（--force 可覆盖）")
            installed = True  # 已存在视为本工具已有着落
            break
        files = fetch_dir_recursive(c["full"], c["sdir"], token)
        if files is None or "SKILL.md" not in files:
            log(f"  → {c['name']} 拉取失败或超体积护栏，换下一个")
            continue
        findings = security_scan(files)
        sha = head_sha(c["full"], token,
                       (c["meta"] or {}).get("default_branch", "main"))
        if findings:
            log(f"  ⚠ {c['name']} 命中危险模式 → 隔离区 {quar}")
            for f, label in findings:
                log(f"      {f}: {label}")
            write_skill(files, quar)
            write_provenance(quar, tool=tool, full=c["full"], sdir=c["sdir"],
                             meta=c["meta"], sha=sha, files=files,
                             verdict="未通过：" + "; ".join(f"{f}({l})" for f, l in findings))
            manifest_append({"ts": datetime.now(timezone.utc).isoformat(),
                             "kind": "skill-harvest-quarantine", "tool": tool,
                             "source": f"https://github.com/{c['full']}",
                             "target": quar, "undo": f"rm -rf {quar}"})
            continue  # 换下一个候选
        write_skill(files, dest)
        write_provenance(dest, tool=tool, full=c["full"], sdir=c["sdir"],
                         meta=c["meta"], sha=sha, files=files, verdict="通过")
        manifest_append({"ts": datetime.now(timezone.utc).isoformat(),
                         "kind": "skill-harvest", "tool": tool,
                         "source": f"https://github.com/{c['full']}",
                         "sha": sha, "target": dest, "undo": f"rm -rf {dest}"})
        log(f"  ✓ 已落盘 {dest}（{len(files)} 个文件）")
        installed = True
        if not args.all:
            break
    return installed


def tools_from_contract():
    contract = os.path.join(CONFIG_ROOT, "toolchain.json")
    try:
        data = json.load(open(contract, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log(f"✗ 读不到契约 {contract}，--from-contract 不可用")
        return []
    terms = []
    for name, info in (data.get("tools") or {}).items():
        if (info or {}).get("status") in ("ok", "degraded"):
            terms.extend(CONTRACT_SEARCH_TERMS.get(name, []))
    return sorted(set(terms))


def main():
    global SKILLS_DEST
    ap = argparse.ArgumentParser(
        description="拿来主义：为指定工具从开源社区收割成熟 Agent Skill")
    ap.add_argument("tools", nargs="*", help="工具名（搜索词），如 remotion lmms rdkit")
    ap.add_argument("--from-contract", action="store_true",
                    help="读路径契约，为链上工具自动逐个收割")
    ap.add_argument("--dest", default=SKILLS_DEST,
                    help=f"技能落盘目录（默认 {SKILLS_DEST}）")
    ap.add_argument("--limit", type=int, default=8, help="每工具最多评估几个候选")
    ap.add_argument("--min-stars", type=int, default=0, help="候选仓库最低 star 数")
    ap.add_argument("--all", action="store_true", help="安装全部过检候选（默认只装最佳 1 个）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的同名 skill")
    ap.add_argument("--dry-run", action="store_true", help="只列候选不安装")
    args = ap.parse_args()

    tools = list(args.tools)
    if args.from_contract:
        tools.extend(tools_from_contract())
    tools = list(dict.fromkeys(tools))
    if not tools:
        ap.print_help()
        return 2

    SKILLS_DEST = os.path.expanduser(args.dest)
    os.makedirs(SKILLS_DEST, exist_ok=True)

    token = get_token()
    log(f"认证: {'gh/env token ✓' if token else '未认证（60 次/小时限速，慎用）'}")
    log(f"落盘目录: {SKILLS_DEST}")

    ok = 0
    for t in tools:
        if harvest_one(t, args, token):
            ok += 1
    if _rate_remaining is not None and _rate_remaining < 10:
        log(f"\n⚠ GitHub API 额度只剩 {_rate_remaining} 次，悠着点。")
    log(f"\n完成：{ok}/{len(tools)} 个工具有了着落。")
    return 0 if ok > 0 or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
