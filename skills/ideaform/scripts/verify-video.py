#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ideaform · 无目视校验

**前提：模型看不到图像、听不到声音。** 所以「渲染成功」≠「画面对」。
本脚本用像素与元数据实测代替目视，以非零退出码表示失败，可直接串进 && 流水线。

用法:
    verify-video.py cover <png> [--w 1920] [--h 1080]
                              [--layout scene|cover]          # 取样带版式，默认 scene
                              [--text-band y0,y1,x0,x1]       # 分数坐标，覆盖版式预设
                              [--red-band  y0,y1,x0,x1]       # P5 红线禁入带
                              [--corridor  y0,y1,x0,x1]
    verify-video.py video <mp4> --frames N [--fps 30] [--tol 2]
                              [--min-audio-bps 64000]

注意 cover 的取样带分版式：视频场景（scene）标题在上、轴线远在下方；
封面（cover）字标更大更低、且红「构想」是品牌字标。带子用错会误报失败。
ffprobe 定位顺序：VW_FFPROBE → 路径契约 toolchain.json → 系统。

退出码: 0 全过 / 1 有失败项 / 2 用法或依赖问题
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore

# 构造主义调色板（与 theme.ts 保持一致）
PAL = {
    "paper": (239, 232, 219),
    "paper2": (226, 215, 194),
    "ink": (23, 20, 15),
    "ink2": (58, 52, 44),
    "red": (206, 42, 29),
    "rule": (201, 191, 169),
}


# ------------------------------------------------------------------ 工具
def near(c, ref, tol=26) -> bool:
    return all(abs(c[i] - ref[i]) <= tol for i in range(3))


def closest_name(c) -> str:
    """返回最近的调色板名字（不要『首个匹配』—— 相近色会互相误判）。"""
    best, bd = None, 1e9
    for k, v in PAL.items():
        d = sum((c[i] - v[i]) ** 2 for i in range(3))
        if d < bd:
            best, bd = k, d
    return best


def ffprobe_path() -> str | None:
    """定位 ffprobe。优先级：VW_FFPROBE → 路径契约 → 系统。

    本机多数情况下**没有系统 ffmpeg/ffprobe**（只有 Remotion 自带的精简版），
    所以必须能读契约里 detect.py 探到的那个 ffprobe。契约由环境配置技能写入：
      环境变量 IDEAFORM_CONTRACT 指定，否则找 ~/.config/ideaform/toolchain.json
    """
    p = os.environ.get("VW_FFPROBE")
    if p and Path(p).exists():
        return p
    for cpath in (os.environ.get("IDEAFORM_CONTRACT"),
                  str(Path.home() / ".config/ideaform/toolchain.json")):
        if not cpath or not Path(cpath).exists():
            continue
        try:
            cfg = json.loads(Path(cpath).read_text(encoding="utf-8"))
            fp = (cfg.get("tools", {}).get("ffprobe", {}) or {}).get("path")
            if fp and Path(fp).exists():
                return fp
        except (OSError, ValueError):
            pass
    for c in ("/usr/bin/ffprobe", "/usr/local/bin/ffprobe"):
        if Path(c).exists():
            return c
    return None


def probe(fp: str, path: Path, stream: str, entries: str) -> str:
    """取值 —— 必须清掉 csv 的尾逗号（实测 `-of csv=p=0` 会带）。"""
    p = subprocess.run([fp, "-v", "error", "-select_streams", stream,
                        "-show_entries", entries, "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True, timeout=30)
    out = (p.stdout or "").strip()
    return out.splitlines()[0].strip().rstrip(",") if out else ""


def parse_rect(s: str) -> tuple[float, float, float, float]:
    v = [float(x) for x in s.split(",")]
    if len(v) != 4:
        raise ValueError("需要 y0,y1,x0,x1 四个分数")
    return v[0], v[1], v[2], v[3]


# ------------------------------------------------------------------ 封面
# 版式取样带（分数坐标 y0,y1,x0,x1）。为什么必须分版式：
#   scene = 视频场景：标题在上（0.34H），对角线轴远在下方 → 标题带无红、走廊干净
#   cover = 封面：字标更大更低，且**红「构想」是品牌字标**（≈0.48–0.56H）、
#           正文下行到 ≈0.71H → 沿用 scene 的带会误判「轴线穿过文字」
# 两套带都由实测像素分布定出（见 examples/demo-episode 的封面实测）。
LAYOUT_BANDS = {
    "scene": {"text": (0.22, 0.64, 0.05, 0.62),
              "red": (0.30, 0.55, 0.05, 0.64),
              "corridor": (0.58, 0.68, 0.05, 0.52)},
    "cover": {"text": (0.30, 0.72, 0.05, 0.62),   # Ideaform + 正文
              "red": (0.60, 0.73, 0.05, 0.62),    # 正文区：轴线不得穿入
              "corridor": (0.725, 0.795, 0.05, 0.52)},  # 正文底 → 轴线顶的净空
}


def check_cover(path: Path, W: int, H: int, *,
                text_band=None, corridor=None, red_band=None) -> list[dict]:
    R: list[dict] = []
    if Image is None:
        return [{"id": "P0", "ok": False, "msg": "缺 Pillow：<venv>/bin/pip install pillow"}]
    if not path.exists():
        return [{"id": "P0", "ok": False, "msg": f"文件不存在 {path}"}]

    size = path.stat().st_size
    R.append({"id": "P2", "ok": size > 20000,
              "msg": f"文件 {size} B" + ("" if size > 20000 else " ← <20KB 基本是渲染失败")})

    img = Image.open(path).convert("RGB")
    Wp, Hp = img.size
    R.append({"id": "P1", "ok": (Wp, Hp) == (W, H),
              "msg": f"尺寸 {Wp}x{Hp}（期望 {W}x{H}）"})
    px = img.load()

    # P3 底色：四角与中上取样，应是 paper
    samples = [(30, 30), (Wp - 30, 30), (Wp // 2, 20), (Wp - 300, Hp // 2)]
    ok3 = all(closest_name(px[x, y]) in ("paper", "paper2") for x, y in samples)
    R.append({"id": "P3", "ok": ok3,
              "msg": "底色为纸色" if ok3 else
                     f"底色异常 {[px[x, y] for x, y in samples]}"})

    # P4 文字像素计数（防字体缺失 → 空白 / opacity:0 / 被同色底盖住）
    tb = text_band or (0.22, 0.64, 0.05, 0.62)
    ty0, ty1 = int(tb[0] * Hp), int(tb[1] * Hp)
    tx0, tx1 = int(tb[2] * Wp), int(tb[3] * Wp)
    n_ink = 0
    for y in range(ty0, ty1, 3):
        for x in range(tx0, tx1, 3):
            if closest_name(px[x, y]) in ("ink", "ink2"):
                n_ink += 1
    R.append({"id": "P4", "ok": n_ink > 300,
              "msg": f"文字区墨色像素 {n_ink}" + ("" if n_ink > 300 else " ← 疑似字没渲出来/字体缺失")})

    # P5 ★ 轴线不得穿过文字块 —— 这是本版式最容易犯的错。
    # 判据：标题+副标题的矩形内**不应出现强调红**（红是轴线/色块的颜色）。
    # 比「走廊纯净度」更精准：直接盯住轴线撞进文字的那种失败。
    tb2 = red_band or (0.30, 0.55, 0.05, 0.64)
    n_red_in_text = 0
    for y in range(int(tb2[0] * Hp), int(tb2[1] * Hp), 2):
        for x in range(int(tb2[2] * Wp), int(tb2[3] * Wp), 2):
            if near(px[x, y], PAL["red"], 40):
                n_red_in_text += 1
    R.append({"id": "P5", "ok": n_red_in_text < 60,
              "msg": f"标题区内红色像素 {n_red_in_text}"
                     + ("" if n_red_in_text < 60 else " ← 轴线穿过了文字块，请改轴线走向或下沉文字")})

    # P7 走廊纯净度：文字块下方到轴线之间应有净空（防其它元素重叠）
    cb = corridor or (0.58, 0.68, 0.05, 0.52)
    cy0, cy1 = int(cb[0] * Hp), int(cb[1] * Hp)
    cx0, cx1 = int(cb[2] * Wp), int(cb[3] * Wp)
    tot = bad = 0
    for y in range(cy0, cy1, 2):
        for x in range(cx0, cx1, 2):
            tot += 1
            if min(px[x, y]) < 150:      # 文字/实心块/彩线必然 < 150；纸色/淡纹样通过
                bad += 1
    pct = bad / tot * 100 if tot else 0
    R.append({"id": "P7", "ok": pct < 1.5,
              "msg": f"走廊异物 {pct:.2f}%" + ("" if pct < 1.5 else " ← 文字下方有元素侵入")})

    # P6 强调红：构造主义版式应恰好有一处克制的红
    n_red = 0
    for y in range(0, Hp, 4):
        for x in range(0, Wp, 4):
            if near(px[x, y], PAL["red"], 40):
                n_red += 1
    R.append({"id": "P6", "ok": n_red > 50,
              "msg": f"红色像素 {n_red}" + ("" if n_red > 50 else " ← 强调色丢了")})
    return R


# ------------------------------------------------------------------ 成片
def check_video(path: Path, frames: int, fps: float, tol: int,
                min_abps: int) -> list[dict]:
    R: list[dict] = []
    fp = ffprobe_path()
    if not fp:
        return [{"id": "V0", "ok": False, "msg": "找不到 ffprobe（设 VW_FFPROBE 或装系统 ffprobe）"}]
    if not path.exists():
        return [{"id": "V0", "ok": False, "msg": f"文件不存在 {path}"}]

    nb = probe(fp, path, "v:0", "stream=nb_frames")
    try:
        nbi = int(nb)
    except ValueError:
        nbi = -1
    R.append({"id": "V1", "ok": nbi == frames,
              "msg": f"帧数 {nb}（期望 {frames}）"
                     + ("" if nbi == frames else " ← 有段丢了，或 --frames 区间写错")})

    dur = probe(fp, path, "v:0", "stream=duration") or probe(fp, path, "v:0", "format=duration")
    try:
        durf = float(dur)
    except ValueError:
        durf = -1.0
    want = frames / fps if fps else 0
    ok_d = durf > 0 and abs(durf - want) <= max(tol / fps, 0.5)
    R.append({"id": "V3", "ok": ok_d,
              "msg": f"时长 {durf:.3f}s（期望 ≈{want:.3f}s）"})

    ab = probe(fp, path, "a:0", "stream=bit_rate")
    try:
        abi = int(ab)
    except ValueError:
        abi = 0
    R.append({"id": "V2", "ok": abi > min_abps,
              "msg": f"音轨码率 {abi} bps（阈值 {min_abps}）"
                     + ("" if abi > min_abps else " ← 疑似静音轨：合流时没加 -map 0:v:0 -map 1:a:0")})
    return R


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description="无目视校验（像素 + 元数据实测）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("cover", help="校验封面 PNG")
    c.add_argument("png")
    c.add_argument("--w", type=int, default=1920)
    c.add_argument("--h", type=int, default=1080)
    c.add_argument("--layout", choices=sorted(LAYOUT_BANDS), default="scene",
                   help="取样带版式：scene=视频场景（默认）/ cover=封面。"
                        "带子由各版式的实测像素分布定出；用错了会误报。")
    c.add_argument("--text-band", default="", help="覆盖版式预设：y0,y1,x0,x1（分数）")
    c.add_argument("--red-band", default="", help="覆盖版式预设：P5 红线禁入带")
    c.add_argument("--corridor", default="", help="覆盖版式预设：走廊净空带")
    c.add_argument("--json", action="store_true")

    v = sub.add_parser("video", help="校验成片 MP4")
    v.add_argument("mp4")
    v.add_argument("--frames", type=int, required=True)
    v.add_argument("--fps", type=float, default=30)
    v.add_argument("--tol", type=int, default=2, help="帧数容差")
    v.add_argument("--min-audio-bps", type=int, default=64000)
    v.add_argument("--json", action="store_true")

    a = ap.parse_args()
    if a.cmd == "cover":
        pres = LAYOUT_BANDS[a.layout]
        res = check_cover(
            Path(a.png), a.w, a.h,
            text_band=parse_rect(a.text_band) if a.text_band else pres["text"],
            corridor=parse_rect(a.corridor) if a.corridor else pres["corridor"],
            red_band=parse_rect(a.red_band) if a.red_band else pres["red"],
        )
    else:
        res = check_video(Path(a.mp4), a.frames, a.fps, a.tol, a.min_audio_bps)

    passed = all(r["ok"] for r in res)
    if a.json:
        print(json.dumps({"passed": passed, "results": res}, ensure_ascii=False, indent=2))
    else:
        for r in res:
            print(f"{'✓' if r['ok'] else '✗'} [{r['id']}] {r['msg']}")
        print()
        print("结论: " + ("全部通过 ✓" if passed else "未通过 ✗ —— 不要交付"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
