#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ideaform · 阶段三：解说时间轴 → BGM 变奏计划

设计意图（本工作流区别于「随便配个 BGM」的地方）：
    论述每进入一个新层次，**音乐换一次形态** —— 但**不换曲子**。
    保持「身份要素」不变，只变「形态要素」，听众才会觉得
    「还是同一段音乐，但它进入下一层了」，而不是「切歌了」。

    身份要素（必须保持一致）          形态要素（变奏的着力点）
    ─────────────────────────         ─────────────────────────
    主题动机 / 动机细胞                配器（增删声部）
    调中心                             密度（音符疏密 / 细分）
    基本速度                           音区（上/下八度）
                                     和声张力（自然音 → 借用和弦 / 七度）
                                     节奏（增值 / 减值）
                                     动态（力度档）
                                     调式（相对大小调 / 同主音）

用法:
    # ① 标出「哪些台词句开启了新层次」
    #    写法 cue:功能    功能 ∈ {present,develop,intensify,contrast,resolve,sustain}
    bgm-plan.py --plan plan.json \
                --layers "1:present,4:develop,6:resolve" \
                --bpm 84 --key "A minor" \
                --out bgm-plan.json

    # ② 自动猜层次（没有人工标注时）：按句数均分
    bgm-plan.py --plan plan.json --auto-layers 3 --out bgm-plan.json

音乐的**两个职责**（都要做，别只做第一个）:
    ① 变奏 —— 保持身份要素（动机/调性/速度），只变形态要素 → 表达「段落推进」
    ② 重音 —— 把重点句钉到最近拍点，留半拍空白 + 重击 + 力度抬起 → 牵引「注意力」
               写法: --accents "4,14,22,27"（逗号分隔的 cue 号）
    只做①，音乐只是分段器；加上②，音乐才在修辞上真正服务于解说。

产出:
    bgm-plan.json   给 LMMS 侧 composer.py / 生成器脚本消费
    bgm-plan.md     人读版（含每段的「变奏证据」—— 与上一段比变了什么）

退出码: 0 成功 / 2 输入问题
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# ── LMMS 工程单位（实测标定，见 electronic-music-production/references/05）
TPB = 48                 # tick per beat
BEATS_PER_BAR = 4        # 4/4
TICKS_PER_BAR = TPB * BEATS_PER_BAR   # 192

# ── 变奏模板库 ────────────────────────────────────────────────────────────
# 每个模板 = 一种「形态」。字段含义:
#   layers      : 参与的声部（LMMS 里就是轨道）
#   density     : 音符密度档 low/mid/high
#   register    : 音区偏移（半音，+12 = 高八度）
#   harmony     : 和声语言
#   tension     : 张力档 0..3
#   dynamics    : 力度档 pp/p/mp/mf/f
#   rhythm      : 节奏处理
#   motif       : 动机处理 —— 变奏的灵魂
#   percussion  : 打击层
#   velocity    : 建议的 note vol 基准（LMMS 是 0..127）
TEMPLATES: dict[str, dict] = {
    "present": {
        "zh": "呈现 · 引入",
        "intent": "先给身份：只露动机，不要满。留白让听众记住主题。",
        "layers": ["pad"], "density": "low", "register": 0,
        "harmony": "diatonic-triad", "tension": 0, "dynamics": "p",
        "rhythm": "half-note pulse", "motif": "original (sole statement)",
        "percussion": "none", "velocity": 62,
    },
    "develop": {
        "zh": "展开 · 深入",
        "intent": "加入低音与律动层，动机开始被模仿/模进。层次感来自「多了东西」。",
        "layers": ["pad", "bass", "lead"], "density": "mid", "register": 0,
        "harmony": "diatonic + 7th color", "tension": 1, "dynamics": "mp",
        "rhythm": "quarter pulse", "motif": "sequence (motif shifted diatonically)",
        "percussion": "soft hat", "velocity": 78,
    },
    "intensify": {
        "zh": "强调 · 冲突",
        "intent": "把张力推上去：全声部、升八度、借用和弦、力度抬一档。",
        "layers": ["pad", "bass", "lead", "counter"], "density": "high", "register": 12,
        "harmony": "borrowed (bVI / iv) + 9th", "tension": 3, "dynamics": "f",
        "rhythm": "8th drive", "motif": "augmented + inverted fragment",
        "percussion": "kick + hat", "velocity": 104,
    },
    "contrast": {
        "zh": "对照 · 转折",
        "intent": "换质地而不是加音量：撤掉一层、换音色、转调式，制造「另一个视角」。",
        "layers": ["pluck", "bass"], "density": "mid", "register": -12,
        "harmony": "modal shift (parallel minor/major)", "tension": 2, "dynamics": "mp",
        "rhythm": "syncopated", "motif": "retrograde / fragmented",
        "percussion": "none", "velocity": 74,
    },
    "resolve": {
        "zh": "收束 · 回归",
        "intent": "做减法：回到主调与动机原形，动机增值（拉长），力度回落。",
        "layers": ["pad", "bass"], "density": "low", "register": 0,
        "harmony": "return to tonic (i)", "tension": 0, "dynamics": "pp",
        "rhythm": "augmented (2x)", "motif": "original, augmented",
        "percussion": "none", "velocity": 56,
    },
    "sustain": {
        "zh": "持续 · 过渡",
        "intent": "不动。层次未变时保持形态，避免无谓的变奏稀释对比。",
        "layers": ["pad", "bass"], "density": "mid", "register": 0,
        "harmony": "diatonic-triad", "tension": 1, "dynamics": "mp",
        "rhythm": "quarter pulse", "motif": "original", "percussion": "none",
        "velocity": 70,
    },
}

# 变奏的「可感知要素」—— 用来生成「与上一段比变了什么」的证据
VARIATION_AXES = ["layers", "density", "register", "harmony",
                  "tension", "dynamics", "rhythm", "motif", "percussion"]


def pick_bpm(total_sec: float, want_bpm: float | None) -> tuple[float, int, float]:
    """给一个总时长选 BPM，使「小节数」尽量是整数。

    返回 (bpm, bars, 小节时长秒)。
    理由：BGM 必须与解说音轨等长，而音乐要落在小节线上才自然。
    做法：在 [66, 96] BPM 里找让 ceil(total/bar_dur) 的小数部分最小的那个；
          并列时优先**偶数小节**（乐句成对，4/8/16 小节更自然），再优先靠近 84 BPM。
    """
    if want_bpm:
        bar = BEATS_PER_BAR * 60 / want_bpm
        bars_f = total_sec / bar
        return want_bpm, max(1, round(bars_f)), bar
    best = None
    for bpm10 in range(660, 961, 2):           # 66.0 .. 96.0，步进 0.2
        bpm = bpm10 / 10
        bar = BEATS_PER_BAR * 60 / bpm
        bars_f = total_sec / bar
        bars = max(1, round(bars_f))
        err = abs(bars_f - round(bars_f))
        cand = (err, 0 if bars % 2 == 0 else 1, abs(bpm - 84), bpm, bars, bar)
        if best is None or cand[:3] < best[:3]:
            best = cand
    assert best
    _, _, _, bpm, bars, bar = best
    return round(bpm, 1), bars, bar


def parse_layers(spec: str) -> list[tuple[int, str]]:
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        cue, _, fn = part.partition(":")
        cue, fn = cue.strip(), (fn.strip() or "sustain")
        if fn not in TEMPLATES:
            raise ValueError(f"未知功能 '{fn}'（可选: {', '.join(TEMPLATES)}）")
        out.append((int(cue), fn))
    return sorted(out)


def auto_layers(n_cues: int, n_layers: int) -> list[tuple[int, str]]:
    """没有人工标注时的兜底：均匀切分，首段 present、末段 resolve、中间 develop。
    ⚠️ 这只是占位。真正决定层次的应该是**文稿的论述结构**，务必人工标一遍。"""
    n_layers = max(1, min(n_layers, n_cues))
    grid = [max(1, round(1 + i * (n_cues - 1) / max(1, n_layers - 1))) for i in range(n_layers)]
    out = []
    for i, c in enumerate(grid):
        if c in [x[0] for x in out]:
            continue
        fn = "present" if i == 0 else ("resolve" if i == n_layers - 1 else "develop")
        out.append((c, fn))
    return out


def build(plan: dict, layers: list[tuple[int, str]], bpm: float | None, key: str,
          lead_in: float, accents: list[int] | None = None) -> dict:
    cues = plan["cues"]
    total = float(plan["total_sec"])
    fps = float(plan.get("fps", 30))
    by_i = {c["i"]: c for c in cues}

    bpm, bars, bar_sec = pick_bpm(total, bpm)
    total_ticks = max(TICKS_PER_BAR, round(bars * TICKS_PER_BAR))

    # 段落边界：从标注的 cue 起，到下一个标注的 cue 起
    secs = []
    for idx, (cue_i, fn) in enumerate(layers):
        c = by_i.get(cue_i)
        if not c:
            raise ValueError(f"plan 里没有第 {cue_i} 条台词")
        end = by_i[layers[idx + 1][0]]["start"] if idx + 1 < len(layers) else total
        start = max(0.0, c["start"] - lead_in)
        secs.append({"cue": cue_i, "fn": fn, "start": round(start, 3), "end": round(end, 3)})

    variations = []
    prev = None
    for i, s in enumerate(secs):
        t = dict(TEMPLATES[s["fn"]])
        t.pop("intent", None)
        # 与上一段对比，生成「变奏证据」
        if prev is None:
            changed = ["(起始段 —— 建立身份，尚无可比对象)"]
        else:
            changed = [ax for ax in VARIATION_AXES
                       if json.dumps(prev.get(ax), ensure_ascii=False)
                       != json.dumps(t.get(ax), ensure_ascii=False)]
        dur = s["end"] - s["start"]
        tk0 = round(s["start"] / total * total_ticks) if total else 0
        tk1 = round(s["end"] / total * total_ticks) if total else total_ticks
        variations.append({
            "index": i + 1,
            "id": f"S{i+1}",
            "template": s["fn"],
            "label": TEMPLATES[s["fn"]]["zh"],
            "intent": TEMPLATES[s["fn"]]["intent"],
            "from_cue": s["cue"],
            "start_sec": s["start"], "end_sec": s["end"], "dur_sec": round(dur, 3),
            "start_frame": round(s["start"] * fps), "end_frame": round(s["end"] * fps),
            "start_tick": tk0, "end_tick": tk1, "len_tick": max(1, tk1 - tk0),
            "texture": {**{k: t[k] for k in VARIATION_AXES}, "velocity": t["velocity"]},
            "changed_vs_prev": changed,
        })
        prev = t
        secs[i]["template"] = s["fn"]

    # ── 重音点（accents）──────────────────────────────────────────────
    # 音乐的第二职责：不只划分层次，还要**牵引注意力** ——
    # 讲到重点时把力度抬起来、必要处先留半拍，让那句话落得更重。
    # 这里只负责"把重点句钉到最近的拍点上"（音乐必须落在拍点），
    # 具体怎么强调（留白 + 重击 + 力度抬起）由渲染器读本字段执行。
    tick_per_beat = TICKS_PER_BAR // BEATS_PER_BAR
    accent_list = []
    for cue_i in (accents or []):
        c = by_i.get(cue_i)
        if not c:
            raise ValueError(f"--accents 指到不存在的台词第 {cue_i} 条")
        raw = round(c["start"] / total * total_ticks) if total else 0
        tick = int(round(raw / tick_per_beat) * tick_per_beat)     # 吸附到最近拍
        tick = max(0, min(total_ticks - 1, tick))
        accent_list.append({
            "cue": cue_i,
            "sec": round(c["start"], 3),
            "tick": tick,
            "bar": tick // TICKS_PER_BAR + 1,
            "beat": (tick % TICKS_PER_BAR) // tick_per_beat + 1,
            "kind": "emphasis",
            "breath_ticks": tick_per_beat // 2,   # 重音前留半拍空白
            "lift": 14,                           # 重音后一小节内力度 +14
            "text": c["text"],
        })

    return {
        "schema_version": 1,
        "generated_by": "bgm-plan.py",
        "source_plan": "plan.json",
        "fps": fps,
        "key": key,
        "bpm": bpm,
        "timesig": "4/4",
        "bar_sec": round(bar_sec, 4),
        "bars": bars,
        "total_sec": total,
        "total_frames": plan.get("total_frames"),
        "ticks_per_bar": TICKS_PER_BAR,
        "total_ticks": total_ticks,
        "principle": {
            "keep": ["motif identity", "tonal center", "basic tempo"],
            "vary": ["layers", "density", "register", "harmony",
                     "tension", "dynamics", "rhythm", "motif transform", "percussion"],
            "why": "保持身份要素不变、只变形态要素，听众才会感到『同一首曲子在推进』，而不是『切歌』。",
        },
        "rhetoric": {
            "role": "牵引注意力（不只是划分层次）",
            "how": "重点句钉到最近拍点 → 该拍之前留半拍空白 → 落拍一记重击 → "
                   "其后一小节内力度整体抬起",
            "why": "层次变奏管『段落感』，重音管『注意力』。两者都要，音乐才既在结构上、"
                   "也在修辞上服务于解说。",
        },
        "accents": accent_list,
        "variations": variations,
        "mmp_hints": {
            "head_bpm": bpm,
            "timeline_lp1pos": total_ticks,
            "note": "composer.py / 生成器读这里：bpm 与 timeline lp1pos 必须按此写，否则 BGM 与解说对不齐。",
        },
    }


def render_md(p: dict) -> str:
    L = []
    A = L.append
    A(f"# BGM 变奏计划\n")
    A(f"- 总时长 **{p['total_sec']}s** / {p['total_frames']} 帧 @ {p['fps']}fps")
    A(f"- 调性 **{p['key']}**　速度 **{p['bpm']} BPM**　{p['timesig']}　"
      f"共 **{p['bars']} 小节**（每小节 {p['bar_sec']}s，{p['ticks_per_bar']} ticks）")
    A(f"- LMMS 提示：`<head bpm=\"{p['bpm']}\">`，`<timeline lp1pos=\"{p['total_ticks']}\">`\n")
    A("## 变奏表（时间主轴 = 解说音轨）\n")
    A("| # | 起(cue) | 时间 | 帧 | 功能 | 配器 | 密度 | 音区 | 和声 | 张力 | 力度 | 动机处理 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for v in p["variations"]:
        t = v["texture"]
        reg = {0: "原位", 12: "+8ve", -12: "-8ve"}.get(t["register"], str(t["register"]))
        A(f"| {v['index']} | 第{v['from_cue']}条 | {v['start_sec']}–{v['end_sec']}s "
          f"| {v['start_frame']}–{v['end_frame']} | **{v['label']}** | {'+'.join(t['layers'])} "
          f"| {t['density']} | {reg} | {t['harmony']} | {t['tension']} | {t['dynamics']} "
          f"| {t['motif']} |")
    A("\n## 变奏证据（每段相对上一段变了什么）\n")
    for v in p["variations"]:
        A(f"### {v['index']}. {v['label']}　`{v['start_sec']}s – {v['end_sec']}s`")
        A(f"{v['intent']}\n")
        if v["index"] == 1:
            A("- 起始段，建立身份。")
        else:
            A(f"- **变了**：{', '.join(v['changed_vs_prev']) or '（无 —— 这一段不该变奏）'}")
            A("- **没变（身份）**：主题动机细胞、调中心、基本速度")
        A("")

    acc = p.get("accents") or []
    A("## 重音点（牵引注意力 —— 音乐的第二职责）\n")
    if not acc:
        A('（未标注。加 `--accents "4,14,22,27"` 可把重点句钉成重音。）')
    else:
        A(f"共 **{len(acc)}** 处。层次变奏管『段落感』，重音管『注意力』；两者都要。\n")
        A("| cue | 时间 | 小节·拍 | 手法 | 原文 |")
        A("|---|---|---|---|---|")
        for x in acc:
            A(f"| 第{x['cue']}条 | {x['sec']}s | {x['bar']}·{x['beat']} "
              f"| 留白 {x['breath_ticks']}t → 重击 → 力度 +{x['lift']} | {x['text']} |")
        A("\n> 渲染器读 `accents[]` 执行：`tick - breath_ticks` 起旋律让位（留白），"
          "`tick` 落一记重击，`tick ~ tick+1小节` 力度 +`lift`。")

    A("\n## 铁律")
    A("- **身份要素不许变**：动机细胞、调中心、基本速度。变了就是切歌，不是变奏。")
    A("- **每段至少变 1 项形态要素**；相邻两段若 `changed_vs_prev` 为空，说明层次标注漏了。")
    A("- 变奏点必须落在解说的层次边界上 —— 音乐先于/同时于文字转向，听众才跟得上。")
    A("- **重点句要有重音**：只变层次而不管重点，音乐就只是分段器，没能牵引注意力。")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="解说时间轴 → BGM 变奏计划")
    ap.add_argument("--plan", required=True, help="make-tts-track.py 产出的 plan.json")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--layers", help='层次标注 "cue:功能,..." 例 "1:present,4:develop,6:resolve"')
    g.add_argument("--auto-layers", type=int, metavar="N", help="自动均分 N 层（占位用）")
    ap.add_argument("--bpm", type=float, default=None, help="不传则自动选（使小节数为整）")
    ap.add_argument("--key", default="A minor")
    ap.add_argument("--lead-in", type=float, default=0.0,
                    help="变奏点相对层次边界提前多少秒（音乐先动）")
    ap.add_argument("--accents", default="",
                    help='重点句（逗号分隔的 cue 号）→ 该拍强调，牵引注意力。例 "4,14,22,27"')
    ap.add_argument("--out", default="bgm-plan.json")
    a = ap.parse_args()

    pp = Path(a.plan)
    if not pp.exists():
        print(f"✗ 找不到 {pp}", file=sys.stderr)
        return 2
    plan = json.loads(pp.read_text(encoding="utf-8"))

    try:
        if a.layers:
            layers = parse_layers(a.layers)
        else:
            layers = auto_layers(len(plan["cues"]), a.auto_layers)
    except ValueError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2

    try:
        acc = [int(x) for x in a.accents.replace("，", ",").split(",") if x.strip()]
    except ValueError:
        print("✗ --accents 必须是逗号分隔的整数 cue 号", file=sys.stderr)
        return 2

    try:
        out = build(plan, layers, a.bpm, a.key, a.lead_in, acc)
    except ValueError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2

    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    md = Path(a.out).with_suffix(".md")
    md.write_text(render_md(out), encoding="utf-8")

    print(f"✓ BGM 变奏计划已生成")
    print(f"  {a.out}")
    print(f"  {md}")
    print(f"\n  {out['bpm']} BPM / {out['key']} / {out['bars']} 小节 / "
          f"{out['total_sec']}s（= 解说音轨长度）")
    print(f"\n  变奏表：")
    for v in out["variations"]:
        ch = "" if v["index"] == 1 else f"  ← 变了 {len(v['changed_vs_prev'])} 项"
        print(f"    {v['index']}. {v['start_sec']:>7.3f}s–{v['end_sec']:>7.3f}s  "
              f"{v['label']}{ch}")
    nop = [v["index"] for v in out["variations"]
           if v["index"] > 1 and not v["changed_vs_prev"]]
    if nop:
        print(f"\n  ⚠ 第 {nop} 段与上一段形态完全相同 —— 若那里确有层次变化，"
              f"说明标注漏了；若没有，用 sustain 是对的。")
    print(f"\n  LMMS: bpm={out['mmp_hints']['head_bpm']}  "
          f"timeline lp1pos={out['mmp_hints']['timeline_lp1pos']}")
    accs = out.get("accents") or []
    if accs:
        print(f"\n  重音点（牵引注意力）{len(accs)} 处：")
        for x in accs:
            print(f"    第{x['cue']:>2}条  {x['sec']:>7.3f}s  第{x['bar']}小节第{x['beat']}拍  "
                  f"留白{x['breath_ticks']}t→重击→+{x['lift']}  「{x['text']}」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
