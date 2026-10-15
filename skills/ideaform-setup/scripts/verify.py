#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ideaform-setup · 端到端冒烟校验

真的跑一遍最小闭环，四项全过才在契约上盖 verified_at。
    ① TTS      —— 合成一句中文，量 RMS
    ② 画面      —— Remotion 渲 1 帧 still，查尺寸与体积
    ③ 音频渲染  —— LMMS 渲 1 个小工程，查非静音（stkdir 守门人）
    ④ 音视频合流 —— 造静音轨陷阱 + 带 -map 合流，查输出音轨码率

用法:
    verify.py                # 跑全部，通过则盖章
    verify.py --no-write     # 只跑不盖章
    verify.py --json         # 机读结果
    verify.py --only tts,lmms
    verify.py --keep DIR     # 指定产物保留目录
"""
from __future__ import annotations

import argparse
import array
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import detect as D  # noqa: E402

CONFIG_ROOT = D.CONFIG_ROOT
FALLBACK_TMPDIR = Path("/tmp")
SMOKE_TMPL = Path(__file__).resolve().parent.parent / "assets" / "lmms-smoke.mmp"
TTS_TEXT = "这是一次环境冒烟测试，用于确认解说音轨可以正常合成。"


def resolve_tmpdir(ct: dict | None = None) -> Path:
    """临时目录：VW_TMPDIR → 契约 tmpdir → /tmp（兜底）。

    ⚠️ 本机 /tmp 常是 **10MB tmpfs**，Remotion 打包写它会 ENOSPC。
    契约里的 `tmpdir` 字段就是为这件事存在的 —— 所有子进程都要继承它，
    不能只拿它当"报告目录"。（曾因只读契约当报告目录、TMPDIR 却写死 /tmp 而误报。）
    """
    p = os.environ.get("VW_TMPDIR")
    if p:
        return Path(p)
    if ct and ct.get("tmpdir"):
        return Path(ct["tmpdir"])
    return FALLBACK_TMPDIR


# ------------------------------------------------------------------ 通用
def sh(cmd: list[str], timeout: int = 300,
       env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except FileNotFoundError:
        return 127, "NOT FOUND"
    except Exception as e:                                     # noqa: BLE001
        return 1, f"{type(e).__name__}: {e}"


def wav_stats(path: Path) -> dict:
    """纯 stdlib 量电平 —— 不依赖 ffmpeg 的 volumedetect（精简版没有）。"""
    with wave.open(str(path)) as w:
        sr, nch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        raw = w.readframes(n)
    a = array.array("h")
    a.frombytes(raw)
    if nch > 1:
        mono = [(a[i] + a[i + 1]) * 0.5 for i in range(0, len(a) - nch + 1, nch)]
    else:
        mono = list(a)
    if not mono:
        return {"sr": sr, "nch": nch, "dur": 0.0, "peak": 0, "rms": 0.0, "clip_pct": 0.0}
    peak = max(abs(x) for x in mono)
    rms = math.sqrt(sum(x * x for x in mono) / len(mono))
    clip = sum(1 for x in mono if abs(x) >= 32600)
    return {"sr": sr, "nch": nch, "dur": round(n / sr, 3), "peak": round(peak),
            "peak_fs": round(peak / 32768, 4), "rms": round(rms, 1),
            "clip_pct": round(clip / len(mono) * 100, 4)}


def probe_field(ffprobe: str, path: Path, entries: str) -> str:
    rc, out = sh([ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", entries,
                  "-of", "default=nw=1:nk=1", str(path)], timeout=30)
    return out.strip().splitlines()[0].strip().rstrip(",") if out.strip() else ""


# ------------------------------------------------------------------ 四项检查
def check_tts(ct: dict, work: Path) -> dict:
    name, venv = "① TTS 合成", ct["tools"]["venv"]
    py = venv.get("python")
    if not py:
        return {"name": name, "ok": False, "why": "契约里没有 venv 解释器"}
    out = work / "tts.mp3"
    script = (
        "import asyncio, edge_tts, sys, os\n"
        "async def m():\n"
        "    for i in range(1,6):\n"
        "        try:\n"
        "            await edge_tts.Communicate(sys.argv[1],'zh-CN-YunxiNeural').save(sys.argv[2])\n"
        "            return 0\n"
        "        except Exception as e:\n"
        "            print('retry',i,type(e).__name__,file=sys.stderr); await asyncio.sleep(1.5*i)\n"
        "    return 1\n"
        "sys.exit(asyncio.run(m()))\n"
    )
    rc, log = sh([py, "-c", script, TTS_TEXT, str(out)], timeout=120)
    if rc != 0 or not out.exists():
        hint = ""
        if "403" in log or "HandshakeError" in log:
            hint = "（403/握手失败 → pip install --upgrade edge-tts，再校准系统时钟）"
        return {"name": name, "ok": False, "why": f"合成失败 rc={rc} {hint}",
                "log_tail": log.strip().splitlines()[-3:]}
    size = out.stat().st_size
    ok = size > 2048
    return {"name": name, "ok": ok, "bytes": size,
            "why": "" if ok else f"产出过小（{size}B），疑似空音频"}


def parse_comp_ids(log: str) -> list[str]:
    """从 remotion 输出里稳健地抽 composition id。

    坑：`remotion compositions` 的可读输出里混着说明文字（
    "The following compositions are available:"），宽松正则会把 "The" 当成 id。
    → 双通道抽取：① 错误信息里的 "Available compositions: A, B, C"
              ② 整行就是一个标识符（无空格、无冒号）
    """
    ids: list[str] = []
    m = re.search(r"Available compositions:\s*([^\n]+)", log)
    if m:
        ids += [s.strip() for s in m.group(1).split(",") if s.strip()]
    for ln in log.splitlines():
        s = ln.strip()
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", s) and not s.islower():
            ids.append(s)
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def check_still(ct: dict, work: Path) -> dict:
    name = "② 画面 still"
    rm = ct["tools"]["remotion"]
    proj, chrome = rm.get("project"), (rm.get("browser") or {}).get("resolved")
    if not proj:
        return {"name": name, "ok": False, "why": "契约里没有 Remotion 工程"}
    node = ct["tools"]["node"]["path"]
    out = work / "still.png"
    cli = str(Path(proj) / "node_modules" / ".bin" / "remotion")
    env = dict(os.environ, TMPDIR=str(resolve_tmpdir(ct)))
    extra = ["--browser-executable", chrome] if chrome else []

    # ① 先问有哪些 composition（同样要带 TMPDIR —— 这一步也会打包）
    _, clog = sh([node, cli, "compositions", "--log=error"] + extra, timeout=240, env=env)
    ids = parse_comp_ids(clog) or ["MyComp"]

    # ② 逐个试，直到渲出一张 PNG（失败信息里若带 Available compositions 就换 id 重试）
    last_log = ""
    for cid in ids[:4]:
        cmd = [node, cli, "still", cid, str(out), "--log=error"] + extra
        p = subprocess.run(cmd, cwd=proj, env=env, capture_output=True, text=True, timeout=420)
        last_log = (p.stdout or "") + (p.stderr or "")
        if p.returncode == 0 and out.exists():
            break
        retry_ids = [i for i in parse_comp_ids(last_log) if i not in ids]
        if retry_ids:
            ids += retry_ids
    if not out.exists():
        hint = ""
        if "browserExecutable" in last_log:
            hint = "（chrome 路径失效 → 重跑 detect.py --write 刷新契约，或 --browser-executable 指定）"
        elif "ENOSPC" in last_log:
            hint = (f"（TMPDIR 太小 → 当前 {resolve_tmpdir(ct)}；本机 /tmp 若是小 tmpfs，"
                    f"请让契约的 tmpdir 指向大盘，或 export VW_TMPDIR=<大盘>）")
        elif "No composition" in last_log or "Could not find composition" in last_log:
            hint = "（工程里没有可用 composition → 换 VW_REMOTION_PROJECT，或用自带模板新建）"
        return {"name": name, "ok": False, "tried": ids[:4],
                "why": f"渲染失败 {hint}",
                "log_tail": [l for l in last_log.strip().splitlines()[-3:]]}

    size = out.stat().st_size
    wh = ""
    try:
        with open(out, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            wh = f"{int.from_bytes(head[16:20],'big')}x{int.from_bytes(head[20:24],'big')}"
    except OSError:
        pass
    ok = size > 20000 and bool(wh)
    return {"name": name, "ok": ok, "cid": cid, "bytes": size, "size": wh,
            "why": "" if ok else f"PNG 异常（{size}B, {wh or '非PNG'}）"}


def check_lmms(ct: dict, work: Path) -> dict:
    name = "③ LMMS 音频渲染"
    lm = ct["tools"]["lmms"]
    apprun = lm.get("apprun")
    if not apprun:
        return {"name": name, "ok": False, "why": "契约里没有 LMMS AppRun"}
    if not SMOKE_TMPL.exists():
        return {"name": name, "ok": False, "why": f"缺冒烟模板 {SMOKE_TMPL}"}
    if not lm.get("stkdir_ok"):
        return {"name": name, "ok": False,
                "why": f"stkdir 不一致（配的是 {lm.get('stkdir_configured')}，"
                       f"应为 {lm.get('stkdir_expected')}）→ 会全程静音"}
    d = work / "lmms"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(SMOKE_TMPL, d / "smoke.mmp")
    rc, log = sh(["bash", "-lc",
                  f"cd {shq(str(d))} && {shq(apprun)} --allowroot render smoke.mmp -f wav -o smoke.wav"],
                 timeout=300)
    wav = d / "smoke.wav"
    if not wav.exists():
        return {"name": name, "ok": False, "why": f"没产出 WAV rc={rc}",
                "log_tail": log.strip().splitlines()[-3:]}
    st = wav_stats(wav)
    ok = st["peak"] > 1000 and st["rms"] > 100
    return {"name": name, "ok": ok, "dur": st["dur"], "peak_fs": st["peak_fs"],
            "rms": st["rms"], "clip_pct": st["clip_pct"],
            "why": "" if ok else "★ 渲染为静音（峰值/RMS 过低）→ 查 stkdir 与波表路径"}


def check_mux(ct: dict, work: Path) -> dict:
    """复现已知陷阱：Remotion 输出自带静音 AAC 轨，合流必须显式 -map。"""
    name = "④ 音视频合流"
    ff = ct["tools"]["ffmpeg"].get("path")
    fp = ct["tools"]["ffprobe"].get("path")
    if not ff or not fp:
        return {"name": name, "ok": False, "why": "契约里没有 ffmpeg/ffprobe"}
    still, tts = work / "still.png", work / "tts.mp3"
    if not still.exists() or not tts.exists():
        return {"name": name, "ok": False, "why": "前置产物缺失（先过 ①②）"}
    env = dict(os.environ, TMPDIR=str(resolve_tmpdir(ct)))
    silent, muxed = work / "silent_track.mp4", work / "muxed.mp4"

    rc, log = sh([ff, "-y", "-loop", "1", "-framerate", "30", "-i", str(still),
                  "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "2",
                  "-vf", "scale=640:360", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "96k", "-shortest", str(silent)], timeout=180)
    if rc != 0 or not silent.exists():
        return {"name": name, "ok": False, "why": f"造静音轨样本失败 rc={rc}",
                "log_tail": log.strip().splitlines()[-3:]}

    rc, log = sh([ff, "-y", "-i", str(silent), "-i", str(tts),
                  "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                  "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                  "-shortest", str(muxed)], timeout=180)
    if rc != 0 or not muxed.exists():
        return {"name": name, "ok": False, "why": f"合流失败 rc={rc}",
                "log_tail": log.strip().splitlines()[-3:]}

    ab = probe_field(fp, muxed, "stream=bit_rate")
    try:
        abi = int(ab)
    except ValueError:
        abi = 0
    nb = probe_field(fp, muxed, "stream=nb_frames") or "0"
    ok = abi > 64000
    return {"name": name, "ok": ok, "audio_bitrate": abi, "frames": nb,
            "why": "" if ok else f"音轨疑似静音（{abi} bps）→ 检查是不是没加 -map，挑中了静音轨"}


def shq(s: str) -> str:
    return "'" + str(s).replace("'", "'\\''") + "'"


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description="端到端冒烟校验（全过才盖章）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--keep", default="")
    args = ap.parse_args()

    contract_path = Path(os.environ.get("VW_CONTRACT", CONFIG_ROOT / "toolchain.json"))
    if not contract_path.exists():
        print(f"✗ 找不到契约 {contract_path}\n  先跑: detect.py --write", file=sys.stderr)
        return 2
    ct = json.loads(contract_path.read_text(encoding="utf-8"))
    if ct.get("schema_version") != D.SCHEMA_VERSION:
        print(f"✗ 契约 schema_version={ct.get('schema_version')}，本脚本要 {D.SCHEMA_VERSION}"
              f"\n  重跑: detect.py --write", file=sys.stderr)
        return 2

    work = Path(args.keep) if args.keep else resolve_tmpdir(ct) / f"smoke-{int(time.time())}"
    work.mkdir(parents=True, exist_ok=True)

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    plan = [("tts", check_tts), ("still", check_still), ("lmms", check_lmms), ("mux", check_mux)]
    results = []
    for key, fn in plan:
        if only and key not in only:
            continue
        if not args.json:
            print(f"… 检查 {key} …", flush=True)
        try:
            r = fn(ct, work)
        except Exception as e:                                 # noqa: BLE001
            r = {"name": key, "ok": False, "why": f"{type(e).__name__}: {e}"}
        results.append(r)
        if not args.json:
            print(("  ✓ " if r["ok"] else "  ✗ ") + r["name"]
                  + ("" if r["ok"] else f"  —— {r.get('why','')}"))

    # 注意：only 是集合（已去重），等式右边必须用去重后的数量，
    # 否则 --only tts,tts 这种重复传参会把"全过"误判为"未过"（错题本 E07）
    passed = all(r["ok"] for r in results) and len(results) == (4 if not only else len(only))

    if passed and not args.no_write:
        ct["verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        ct["smoke_report"] = str(work / "report.json")
        contract_path.write_text(json.dumps(ct, ensure_ascii=False, indent=2), encoding="utf-8")

    (work / "report.json").write_text(
        json.dumps({"results": results, "passed": passed,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps({"passed": passed, "results": results, "workdir": str(work)},
                         ensure_ascii=False, indent=2))
    else:
        print()
        print("═" * 60)
        if passed:
            print("✓ 冒烟校验全部通过" + ("" if args.no_write else
                  f"\n  verified_at 已盖入 {contract_path}"))
            print(f"  产物留证: {work}")
            print("\n下一步：切到工作流技能 —— skills/ideaform/SKILL.md")
        else:
            bad = [r["name"] for r in results if not r["ok"]]
            print(f"✗ 冒烟校验未通过：{'、'.join(bad)}")
            print("  修好后重跑本脚本。未通过前不要盖章，也不要把环境配置技能删掉。")
            print(f"  详情: {work/'report.json'}")
        print("═" * 60)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
