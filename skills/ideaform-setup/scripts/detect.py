#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ideaform-setup · 只读工具链探测 / 路径契约生成

用法:
    detect.py                 # 人类可读报告
    detect.py --json          # 机器可读 JSON（到 stdout）
    detect.py --write         # 解析并写入契约: toolchain.json + env.sh
    detect.py --workspace DIR # 指定工作空间（默认当前目录）

安全保证:
    * 本脚本**只读**。不创建、不修改、不删除任何系统文件。
    * 唯一写入发生在 --write，且只写 $VW_CONFIG_ROOT 下的两个文件。
    * 绝不触碰 /mnt/c、/mnt/d。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCHEMA_VERSION = 1
GENERATOR = "ideaform-setup@1.0.0"

HOME = Path.home()
CONFIG_ROOT = Path(os.environ.get("VW_CONFIG_ROOT", HOME / ".config" / "ideaform"))
SKILL_DIR = Path(__file__).resolve().parent.parent          # .../ideaform-setup
STARTER_TEMPLATE = SKILL_DIR / "assets" / "templates" / "remotion-starter"

WSL_MARKERS = ("microsoft", "wsl")


# ----------------------------------------------------------------------------- helpers
def run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    """跑一个命令，返回 (returncode, stdout+stderr)。永不抛异常。"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    except Exception as e:                                    # noqa: BLE001
        return 1, f"{type(e).__name__}: {e}"


def first_existing(cands: list[Path]) -> Path | None:
    """返回第一个存在的可执行路径 —— **刻意不 resolve 软链**。

    坑（本机实测）：托管工具链的路径里含软链（`bin/` 也是软链）。
    `.resolve()` 会把 venv 的解释器解析成系统 python，`sys.prefix` 随之改变
    → venv 里装的包全部 import 不到。所以一律保留原路径。
    """
    for c in cands:
        try:
            if c and c.exists() and os.access(c, os.X_OK):
                return Path(os.path.abspath(c))
        except OSError:
            continue
    return None


def real_target(p: Path | None) -> str | None:
    """软链的真实目标（仅供诊断展示，不用于执行）。"""
    if not p:
        return None
    try:
        r = os.path.realpath(p)
        return r if r != str(p) else None
    except OSError:
        return None


def glob_sorted(pattern: str, root: Path, limit: int = 40) -> list[Path]:
    try:
        return sorted(root.glob(pattern))[:limit]
    except Exception:                                          # noqa: BLE001
        return []


def ver_of(exe: Path | None, args: list[str] | None = None) -> str | None:
    """取版本号。优先取输出里第一个看起来像 x.y[.z] 的 token。"""
    if not exe:
        return None
    rc, out = run([str(exe)] + (args or ["--version"]))
    if rc != 0 and not out:
        return None
    m = re.search(r"\d+\.\d+(?:\.\d+)?", out)
    return m.group(0) if m else (out.strip().splitlines() or [""])[0][:60]


def is_wsl() -> bool:
    try:
        if "microsoft" in Path("/proc/version").read_text(errors="ignore").lower():
            return True
    except OSError:
        pass
    return any(m in platform.release().lower() for m in WSL_MARKERS)


def distro() -> str:
    try:
        txt = Path("/etc/os-release").read_text(errors="ignore")
        for key in ("PRETTY_NAME", "NAME"):
            m = re.search(rf'^{key}="?([^"\n]+)"?', txt, re.M)
            if m:
                return m.group(1).strip()
    except OSError:
        pass
    return f"{platform.system()} {platform.release()}"


# ----------------------------------------------------------------------------- probes
def find_node() -> dict:
    cands = []
    if os.environ.get("VW_NODE"):
        cands.append(Path(os.environ["VW_NODE"]))
    cands += glob_sorted("binaries/node/versions/*/bin/node", HOME / ".workbuddy")
    cands += [HOME / ".nvm/current/bin/node", Path("/usr/local/bin/node"), Path("/usr/bin/node")]
    if shutil.which("node"):
        cands.append(Path(shutil.which("node")))
    exe = first_existing(cands)
    v = ver_of(exe)
    return {"path": str(exe) if exe else None, "version": v, "real": real_target(exe),
            "status": "ok" if exe and v else "missing"}


def find_python() -> dict:
    cands = []
    if os.environ.get("VW_PYTHON"):
        cands.append(Path(os.environ["VW_PYTHON"]))
    for pat in ("binaries/python/versions/*/bin/python3", "binaries/python/versions/*/bin/python"):
        cands += list(reversed(glob_sorted(pat, HOME / ".workbuddy")))
    cands += [Path("/usr/local/bin/python3"), Path("/usr/bin/python3")]
    if shutil.which("python3"):
        cands.append(Path(shutil.which("python3")))
    exe = first_existing(cands)
    rc, out = run([str(exe), "-V"]) if exe else (1, "")
    m = re.search(r"(\d+\.\d+\.\d+)", out)
    return {"path": str(exe) if exe else None, "version": m.group(1) if m else None,
            "status": "ok" if exe and m else "missing"}


def find_venv() -> dict:
    cands = []
    if os.environ.get("VW_VENV"):
        cands.append(Path(os.environ["VW_VENV"]))
    cands += [HOME / ".workbuddy/binaries/python/envs/default", CONFIG_ROOT / "venv"]
    for c in cands:
        py = c / "bin" / "python"
        if py.exists():
            return {"path": os.path.abspath(c), "python": os.path.abspath(py),
                    "python_real": real_target(py),
                    "pip": os.path.abspath(c / "bin" / "pip"), "status": "ok",
                    "owned": os.access(c, os.W_OK)}
    return {"path": None, "python": None, "python_real": None, "pip": None,
            "status": "missing", "owned": False}


def find_ffmpeg(venv: dict, remotion: dict) -> tuple[dict, dict]:
    """先找系统 PATH；没有就挖 Remotion 自带的精简版。"""
    ff = first_existing([Path(shutil.which("ffmpeg"))] if shutil.which("ffmpeg") else [])
    fp = first_existing([Path(shutil.which("ffprobe"))] if shutil.which("ffprobe") else [])

    if not ff:
        roots = []
        if remotion.get("project"):
            roots.append(Path(remotion["project"]) / "node_modules" / "@remotion")
        # 顺手扫一下常见的 Remotion 工程
        for pat in ("**/node_modules/@remotion/compositor-*",):
            for base in [HOME / "tools", HOME / "WorkBuddy"]:
                for d in glob_sorted(pat, base, limit=10):
                    roots.append(d)
        for r in roots:
            for name in ("ffmpeg", "ffprobe"):
                hit = first_existing(list(r.glob(f"*/{name}")) + list(r.glob(f"{name}")))
                if hit:
                    if name == "ffmpeg" and not ff:
                        ff = hit
                    if name == "ffprobe" and not fp:
                        fp = hit

    def describe(exe: Path | None) -> dict:
        if not exe:
            return {"path": None, "version": None, "flavor": None, "status": "missing"}
        rc, out = run([str(exe), "-version"])
        m = re.search(r"ffmpeg version (\S+)", out)
        version = m.group(1) if m else ver_of(exe)
        # 精简版判据：滤镜数量少
        rc2, fl = run([str(exe), "-hide_banner", "-filters"])
        n = len([ln for ln in fl.splitlines() if re.match(r"\s*\S+\s+\S+\s+\S+", ln)])
        flavor = "remotion-minimal" if n and n < 60 else ("full" if n else None)
        return {"path": str(exe), "version": version, "flavor": flavor,
                "filters": n, "status": "degraded" if flavor == "remotion-minimal" else "ok"}

    d = describe(ff)
    p = describe(fp)
    return d, {"path": p["path"], "status": p["status"]}


def find_browser(proj: Path | None) -> dict:
    """解析 Remotion 用的 headless chrome。

    坑（本机实测）：`remotion.config.ts` 里 `setBrowserExecutable("<旧路径>")`
    常常指向一个**已经不存在的**目录（换过机器/清理过缓存），
    此时 `npx remotion still` 直接报 browserExecutable does not exist 而失败。
    → 探测到失效时，去 Remotion / puppeteer 的缓存里找真实二进制回报。
    """
    configured = None
    if proj:
        cfg = proj / "remotion.config.ts"
        if cfg.exists():
            try:
                m = re.search(r'setBrowserExecutable\(\s*["\']([^"\']+)["\']', cfg.read_text())
                configured = m.group(1) if m else None
            except OSError:
                pass
    if configured and Path(configured).is_file():
        return {"configured": configured, "resolved": configured,
                "source": "remotion.config.ts", "status": "ok"}

    found = None
    cands: list[Path] = []
    if proj:
        for pat in ("node_modules/.remotion/**/chrome-headless-shell",
                    "node_modules/.remotion/chrome-headless-shell"):
            cands += list(proj.glob(pat))
    for pat in ("**/chrome-headless-shell", "**/chrome-headless-shell-linux64/chrome-headless-shell"):
        for base in (HOME / ".cache/remotion", HOME / ".cache/puppeteer", HOME / "tools"):
            if base.exists():
                cands += list(base.glob(pat))[:6]
    for c in cands:
        try:
            if c.is_file() and os.access(c, os.X_OK):
                found = Path(os.path.abspath(c))
                break
        except OSError:
            continue

    if found:
        return {"configured": configured, "resolved": str(found),
                "source": "cache-scan", "status": "ok" if not configured else "stale"}
    return {"configured": configured, "resolved": None, "source": None,
            "status": "missing" if configured else "unknown"}


def find_remotion(workspace: Path) -> dict:
    cands = []
    if os.environ.get("VW_REMOTION_PROJECT"):
        cands.append(Path(os.environ["VW_REMOTION_PROJECT"]))
    cands += [HOME / "tools" / "remotion-app"]
    for base in (workspace, HOME / "WorkBuddy"):
        for cfg in glob_sorted("*/remotion.config.ts", base, limit=8):
            cands.append(cfg.parent)
        for cfg in glob_sorted("*/*/remotion.config.ts", base, limit=8):
            cands.append(cfg.parent)

    proj = None
    for c in cands:
        try:
            if (c / "remotion.config.ts").exists() or (c / "package.json").exists():
                proj = Path(os.path.abspath(c))
                break
        except OSError:
            continue
    bundled = False
    if proj is None and (STARTER_TEMPLATE / "package.json").exists():
        proj, bundled = STARTER_TEMPLATE, True

    version = None
    installed = False
    if proj:
        pkg = proj / "node_modules" / "remotion" / "package.json"
        try:
            version = json.loads(pkg.read_text())["version"]
            installed = True
        except Exception:                                      # noqa: BLE001
            try:
                version = json.loads((proj / "package.json").read_text()).get(
                    "dependencies", {}).get("remotion")
            except Exception:                                  # noqa: BLE001
                pass
    return {"project": str(proj) if proj else None, "version": version,
            "deps_installed": installed, "is_bundled_template": bundled,
            "browser": find_browser(proj),
            "status": "ok" if (proj and installed) else ("degraded" if proj else "missing")}


def find_lmms() -> dict:
    cands = []
    if os.environ.get("VW_LMMS_APPRUN"):
        cands.append(Path(os.environ["VW_LMMS_APPRUN"]))
    cands.append(CONFIG_ROOT / "lmms" / "squashfs-root" / "AppRun")
    for base in (HOME / "WorkBuddy", HOME / "tools"):
        for hit in glob_sorted("*/lmms-lab/squashfs-root/AppRun", base, limit=6):
            cands.append(hit)
        for hit in glob_sorted("*/*/squashfs-root/AppRun", base, limit=6):
            cands.append(hit)
    apprun = first_existing(cands)

    # ⚠️ AppRun 是软链（squashfs-root/AppRun -> usr/bin/lmms）。
    # 绝不能 resolve —— 那样 parent 就变成 squashfs-root/usr，stkdir 推导全错。
    root = apprun.parent if apprun else None            # → .../squashfs-root
    stkdir = root / "usr" / "share" / "stk" / "rawwaves" if root else None

    # 读 ~/.lmmsrc.xml 里配的 stkdir，判断与实际是否一致（最常见的静音坑）
    configured = None
    rc_file = HOME / ".lmmsrc.xml"
    if rc_file.exists():
        try:
            m = re.search(r'stkdir="([^"]*)"', rc_file.read_text(errors="ignore"))
            configured = m.group(1) if m else None
        except OSError:
            pass
    stk_ok = False
    if stkdir and stkdir.exists() and configured:
        try:
            stk_ok = os.path.realpath(configured) == os.path.realpath(stkdir)
        except OSError:
            stk_ok = False

    version = None
    if apprun:
        rc, out = run([str(apprun), "--allowroot", "--version"], timeout=25)
        m = re.search(r"(\d+\.\d+\.\d+)", out)
        version = m.group(1) if m else None

    status = "ok" if (apprun and stk_ok) else ("degraded" if apprun else "missing")
    return {"apprun": str(apprun) if apprun else None,
            "root": str(root) if root else None,
            "version": version,
            "stkdir_expected": str(stkdir) if stkdir else None,
            "stkdir_configured": configured,
            "stkdir_ok": stk_ok,
            "status": status}


def find_fonts() -> dict:
    if shutil.which("fc-list"):
        rc, out = run(["fc-list", ":lang=zh", "family"])
        fams = sorted({f.strip() for ln in out.splitlines() for f in ln.split(",") if f.strip()})
        cjk = [f for f in fams if "CJK" in f.upper() or "HAN" in f.upper() or "WQY" in f.upper()]
        # 简体优先排前（构建视频默认用 SC）
        cjk.sort(key=lambda f: (0 if f.endswith(" SC") else 1 if "SC" in f else 2, f))
        return {"method": "fontconfig", "cjk_families": cjk[:12], "count_zh": len(fams),
                "has_sc": any(f.endswith(" SC") or " SC " in f for f in cjk),
                "status": "ok" if cjk or fams else "missing"}
    return {"method": "none", "cjk_families": [], "count_zh": 0, "has_sc": False,
            "status": "missing"}


def find_vcs() -> dict:
    out = {}
    for name in ("git", "gh"):
        exe = Path(shutil.which(name)) if shutil.which(name) else None
        out[name] = {"path": str(exe) if exe else None, "version": ver_of(exe)}
    return out


def resolve_tmpdir(workspace: Path) -> Path:
    if os.environ.get("VW_TMPDIR"):
        return Path(os.environ["VW_TMPDIR"])
    for base in (workspace, CONFIG_ROOT):
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / ".tmp"
            probe.mkdir(exist_ok=True)
            free = shutil.disk_usage(base).free
            if free > 2 * 1024**3:                              # > 2GB 才算大盘
                return probe
        except OSError:
            continue
    return Path("/tmp")


# ----------------------------------------------------------------------------- main
def probe(workspace: Path) -> dict:
    node = find_node()
    python = find_python()
    venv = find_venv()
    remotion = find_remotion(workspace)
    ffmpeg, ffprobe = find_ffmpeg(venv, remotion)
    lmms = find_lmms()
    fonts = find_fonts()
    vcs = find_vcs()

    # venv 内的关键包
    pkgs = {}
    if venv.get("python"):
        for mod, label in (("edge_tts", "edge-tts"), ("soundfile", "soundfile"), ("numpy", "numpy")):
            rc, out = run([venv["python"], "-c", f"import {mod};print(getattr({mod},'__version__','?'))"])
            pkgs[label] = {"present": rc == 0, "version": out.strip() if rc == 0 else None}

    tmpdir = resolve_tmpdir(workspace)

    required_flags = {
        "node": node["status"] == "ok",
        "python": python["status"] == "ok",
        "venv": venv["status"] == "ok",
        "ffmpeg": ffmpeg["status"] != "missing",
        "ffprobe": ffprobe["status"] != "missing",
        "remotion": remotion["status"] == "ok",
        "lmms": lmms["status"] == "ok",
        "fonts": fonts["status"] == "ok",
    }
    missing = [k for k, v in required_flags.items() if not v]
    degraded = [k for k, s in (("ffmpeg", ffmpeg), ("lmms", lmms), ("remotion", remotion))
                if s["status"] == "degraded"]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generated_by": GENERATOR,
        "verified_at": None,
        "host": {"os": platform.system().lower(), "distro": distro(),
                 "arch": platform.machine(), "in_wsl": is_wsl(),
                 "kernel": platform.release()},
        "config_root": str(CONFIG_ROOT),
        "tmpdir": str(tmpdir),
        "tools": {
            "node": node, "python": python, "venv": venv,
            "packages": pkgs,
            "ffmpeg": ffmpeg, "ffprobe": ffprobe,
            "remotion": remotion, "lmms": lmms, "fonts": fonts, "vcs": vcs,
        },
        "env_file": str(CONFIG_ROOT / "env.sh"),
        "manifest": str(CONFIG_ROOT / "install-manifest.jsonl"),
        "_summary": {
            "required_missing": missing,
            "degraded": degraded,
            "ready": not missing,
        },
    }


def human_report(c: dict) -> str:
    t = c["tools"]
    L = []
    A = L.append
    A("=" * 68)
    A("  构造主义视频工作流 · 环境探测报告（只读）")
    A("=" * 68)
    A(f"  主机    : {c['host']['distro']} / {c['host']['arch']}"
      f"{' / WSL' if c['host']['in_wsl'] else ''}")
    A(f"  契约定向: {c['config_root']}")
    A(f"  临时目录: {c['tmpdir']}")
    A("-" * 68)
    A(f"{'工具':<14}{'状态':<10}路径 / 备注")
    A("-" * 68)

    def row(name: str, st: str, note: str) -> None:
        mark = {"ok": "✓ ok", "degraded": "△ degraded", "missing": "✗ missing"}.get(st, st)
        A(f"{name:<14}{mark:<10}{note}")

    row("node", t["node"]["status"], f"{t['node']['path'] or '-'}  v{t['node']['version'] or '-'}")
    row("python", t["python"]["status"], f"{t['python']['path'] or '-'}  v{t['python']['version'] or '-'}")
    row("venv", t["venv"]["status"], t["venv"]["path"] or "-")
    for label, info in t["packages"].items():
        A(f"{'  · ' + label:<14}{'✓ ok' if info['present'] else '✗ missing':<10}"
          f"{info['version'] or '未安装'}")
    ff = t["ffmpeg"]
    row("ffmpeg", ff["status"],
        f"{ff['path'] or '-'}  [{ff.get('flavor') or '-'}, {ff.get('filters') or 0} filters]")
    row("ffprobe", t["ffprobe"]["status"], t["ffprobe"]["path"] or "-")
    if t["venv"]["status"] == "ok" and t["venv"].get("python_real"):
        A(f"{'  · 注':<14}{'':10}venv 解释器经软链 → {t['venv']['python_real']}"
          f"（执行一律用原路径，勿 resolve）")
    rm = t["remotion"]
    row("remotion", rm["status"],
        f"{rm['project'] or '-'}  v{rm['version'] or '-'}"
        f"{'（自带模板，未装依赖）' if rm.get('is_bundled_template') else ''}"
        f"{'（依赖未装）' if not rm['deps_installed'] else ''}")
    br = rm.get("browser") or {}
    if rm["project"]:
        _bl = {"ok": "✓ ok", "stale": "△ 已失效→已重新定位", "missing": "✗ 找不到",
               "unknown": "△ 未配置"}.get(br.get("status"), "-")
        A(f"{'  · chrome':<14}{_bl:<10}{br.get('resolved') or '（未找到 headless chrome）'}")
        if br.get("status") == "stale":
            A(f"{'':14}{'':10}配置里写的是 {br.get('configured')} ← 已不存在，"
              f"渲染会直接报错")
    lm = t["lmms"]
    row("lmms", lm["status"], f"{lm['apprun'] or '-'}  v{lm['version'] or '-'}")
    if lm["apprun"]:
        A(f"{'  · stkdir':<14}{'✓ ok' if lm['stkdir_ok'] else '✗ 不一致':<10}"
          f"期望 {lm['stkdir_expected']}")
        if not lm["stkdir_ok"]:
            A(f"{'':14}{'':10}实配 {lm['stkdir_configured'] or '（未配置）'}"
              f"  ← 会导致渲染全程静音")
    row("fonts", t["fonts"]["status"],
        f"{t['fonts']['count_zh']} 个中文字族；CJK: {', '.join(t['fonts']['cjk_families'][:3]) or '无'}")

    A("-" * 68)
    s = c["_summary"]
    if s["ready"]:
        A("  结论: ✓ 必需工具齐备，可以进入校验步骤")
    else:
        A(f"  结论: ✗ 缺 {len(s['required_missing'])} 项 → {', '.join(s['required_missing'])}")
    if s["degraded"]:
        A(f"  注意: △ 降级项 {', '.join(s['degraded'])}（能用但能力不全，见 toolchain-matrix.md）")
    A("=" * 68)
    return "\n".join(L)


def write_contract(c: dict) -> list[Path]:
    CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    (CONFIG_ROOT / "logs").mkdir(exist_ok=True)
    (CONFIG_ROOT / "backup").mkdir(exist_ok=True)

    tj = CONFIG_ROOT / "toolchain.json"
    tj.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")

    t = c["tools"]
    env_lines = [
        "# ideaform · 由 ideaform-setup 生成，勿手改",
        f"# generated_at {c['generated_at']}",
        f"export VW_CONFIG_ROOT={shq(c['config_root'])}",
        f"export VW_TMPDIR={shq(c['tmpdir'])}",
        f"export VW_CONTRACT={shq(str(tj))}",
    ]
    mapping = {
        "VW_NODE": t["node"]["path"], "VW_PYTHON": t["python"]["path"],
        "VW_VENV": (t["venv"] or {}).get("path"),
        "VW_FFMPEG": t["ffmpeg"]["path"], "VW_FFPROBE": t["ffprobe"]["path"],
        "VW_REMOTION_PROJECT": (t["remotion"] or {}).get("project"),
        "VW_CHROME": ((t["remotion"] or {}).get("browser") or {}).get("resolved"),
        "VW_LMMS_APPRUN": (t["lmms"] or {}).get("apprun"),
        "VW_LMMS_ROOT": (t["lmms"] or {}).get("root"),
    }
    for k, v in mapping.items():
        if v:
            env_lines.append(f"export {k}={shq(v)}")
    env_lines += [
        "export TMPDIR=\"$VW_TMPDIR\"",
        "export PATH=\"$(dirname \"$VW_NODE\"):$PATH\"",
        "# 便捷函数：从契约里取任意字段  vw <jq 路径>",
        "vw() { python3 -c \"import json,sys;d=json.load(open('$VW_CONTRACT'));[d:=d.get(k) for k in sys.argv[1].split('.')];print(d)\" \"$1\"; }",
        "",
    ]
    ef = CONFIG_ROOT / "env.sh"
    ef.write_text("\n".join(env_lines), encoding="utf-8")
    try:
        os.chmod(ef, 0o644)
    except OSError:
        pass
    return [tj, ef]


def shq(s: str) -> str:
    return "'" + str(s).replace("'", "'\\''") + "'"


def main() -> int:
    ap = argparse.ArgumentParser(description="只读探测本机工具链并生成路径契约")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--write", action="store_true", help="写入契约 toolchain.json + env.sh")
    ap.add_argument("--workspace", default=os.getcwd(), help="工作空间目录（默认 cwd）")
    args = ap.parse_args()

    ws = Path(args.workspace).resolve()
    c = probe(ws)

    if args.write:
        files = write_contract(c)
        print(f"✓ 契约已写入：")
        for f in files:
            print(f"    {f}")
        print(f"\n  schema_version = {c['schema_version']}  (工作流技能据此校验兼容性)")
        print(f"  verified_at    = {c['verified_at']}  (下一步跑 verify.py 后才会盖章)")
        if c["_summary"]["required_missing"]:
            print(f"\n  ⚠ 仍缺: {', '.join(c['_summary']['required_missing'])}"
                  f" → 先跑 install.sh")
        return 0

    if args.json:
        print(json.dumps(c, ensure_ascii=False, indent=2))
    else:
        print(human_report(c))
    return 0 if c["_summary"]["ready"] else 2


if __name__ == "__main__":
    sys.exit(main())
