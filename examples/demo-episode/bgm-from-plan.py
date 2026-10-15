#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
变奏计划 → LMMS 工程（参考实现）

这是「阶段三」的落地脚本：读 bgm-plan.json，把它翻译成一份可渲染的 .mmp。

设计要点（也就是「怎么让变奏真的听得出来」）：
  * **所有声部常驻工程**，靠"在某段里不写音符"来实现「撤层」——和 DAW 里一样。
    这样变奏 = 同一份工程里不同区间的配器差，听起来才是"同一首曲子"。
  * **动机细胞只有一个**，全曲都是它的变形（原形 / 模进 / 增值 / 倒影）。
    这是"身份要素不变"的落地方式。
  * **和声循环跨段连续**（bar 索引全局递增），换段不重置 —— 否则会有"切歌感"。
  * **调中心与速度全曲不变**，只改配器 / 密度 / 音区 / 力度 / 张力。

用法:
    python3 bgm-from-plan.py --plan out/bgm-plan.json --out bgm.mmp
    "$VW_LMMS_APPRUN" --allowroot render bgm.mmp -f wav -o out/bgm.wav
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ── LMMS 单位（实测标定）──────────────────────────────────────────────
TPB = 48                      # tick per beat
BAR = TPB * 4                 # 192 tick = 1 小节 (4/4)
PAD = 192                     # 每轨 64 步，够长（工程实际长度由 timeline 决定）

# ── 动机细胞（身份要素，全曲不变）────────────────────────────────────
# A 小调：A - C - E，音程结构 = 小三度 + 大三度
MOTIF = [0, 3, 7]

# ── 和声循环（A 小调：i - VI - III - VII = Am - F - C - G）──────────
CHORDS_SAFE = [
    (57, 60, 64),   # Am
    (53, 57, 60),   # F
    (48, 52, 55),   # C
    (55, 59, 62),   # G
]
# 「强调」段用的借用和弦，张力更高：i - VI - iv - V
CHORDS_TENSE = [
    (57, 60, 64),   # Am
    (53, 57, 60),   # F
    (50, 53, 57),   # Dm  (iv，借用/下属小调)
    (52, 56, 59),   # E   (V，大调和弦 → 张力)
]


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def note(pos: int, key: int, ln: int, vol: int, pan: int = 0) -> str:
    return (f'<note vol="{max(1, min(127, int(vol)))}" pan="{int(pan)}" '
            f'len="{max(1, int(ln))}" pos="{int(pos)}" key="{max(0, min(127, int(key)))}"/>')


# ── 乐器定义 ────────────────────────────────────────────────────────────
def instr_pad() -> str:
    return ('<instrument name="tripleoscillator"><tripleoscillator modalgo1="2" modalgo2="2" '
            'modalgo3="2" wavetype0="1" wavetype1="1" wavetype2="1" coarse0="0" coarse1="0" '
            'coarse2="0" finer0="0" finer1="0" finer2="0" finel0="0" finel1="0" finel2="0" '
            'vol0="40" vol1="40" vol2="40" pan0="-38" pan1="0" pan2="38" stphdetun0="18" '
            'stphdetun1="-16" stphdetun2="12" phoffset0="0" phoffset1="0" phoffset2="0" '
            'useWaveTable1="0" useWaveTable2="0" useWaveTable3="0" userwavefile0="" '
            'userwavefile1="" userwavefile2=""><key/></tripleoscillator></instrument>')


def instr_lead(saw: bool = True) -> str:
    wt = "2" if saw else "1"
    return (f'<instrument name="tripleoscillator"><tripleoscillator modalgo1="2" modalgo2="2" '
            f'modalgo3="2" wavetype0="{wt}" wavetype1="{wt}" wavetype2="{wt}" coarse0="0" '
            f'coarse1="0" coarse2="0" finer0="0" finer1="0" finer2="0" finel0="0" finel1="0" '
            f'finel2="0" vol0="46" vol1="0" vol2="0" pan0="0" pan1="0" pan2="0" '
            f'stphdetun0="7" stphdetun1="0" stphdetun2="0" phoffset0="0" phoffset1="0" '
            f'phoffset2="0" useWaveTable1="0" useWaveTable2="0" useWaveTable3="0" '
            f'userwavefile0="" userwavefile1="" userwavefile2=""><key/></tripleoscillator></instrument>')


def instr_bass() -> str:
    return ('<instrument name="lb302"><lb302 vcf_mod="1" slide_dec="0.19" vcf_res="0.35" '
            'dist="0" db24="1" shape="0" slide="0" dead="0" vcf_cut="0.55" vcf_dec="0"/></instrument>')


def instr_sampler(src: str, amp: int) -> str:
    return (f'<instrument name="audiofileprocessor"><audiofileprocessor interp="1" '
            f'reversed="0" looped="0" sframe="0" lframe="0" eframe="1" src="{src}" '
            f'amp="{amp}" stutter="0"/></instrument>')


def eldata(kind: str) -> str:
    """包络。★ amt 必须非零，否则整条包络静默失效（音色死板）[实测]。"""
    presets = {
        # 名称: (att, hold, dec, sus, rel) 秒
        "pad":  (0.35, 0, 0, 1.0, 0.9),
        "lead": (0.02, 0.06, 0.30, 0.8, 0.30),
        "bass": (0.0, 0, 0.15, 0.6, 0.15),
        "drum": (0.0, 0, 0, 1.0, 0.0),
    }
    att, hold, dec, sus, rel = presets[kind]

    def T2p(sec: float) -> float:
        return 0 if sec <= 0 else (sec / 5.0) ** 0.5   # 实测：秒 ≈ 5 × 参数²

    def env(tag: str, amt: float) -> str:
        return (f'<{tag} lspd_denominator="4" lpdel="0" latt="0" lshp="0" pdel="0" '
                f'lspd_numerator="4" amt="{amt}" lamt="0" att="{T2p(att):.4f}" '
                f'dec="{T2p(dec):.4f}" userwavefile="" lspd_syncmode="0" x100="0" '
                f'rel="{T2p(rel):.4f}" hold="{T2p(hold):.4f}" ctlenvamt="0" '
                f'lspd="0.1" sustain="{sus}"/>')

    return (f'<eldata fcut="14000" ftype="0" fres="0.5" fwet="0">'
            f'{env("elvol", 1.0)}{env("elcut", 0.0)}{env("elres", 0.0)}</eldata>')


def track(name: str, vol: int, pan: int, instrument: str, env_kind: str,
          fx: str, notes: list[str], total_ticks: int) -> str:
    return f"""      <track minimized="0" type="0" y="60" muted="0" visible="1" tab="0" name="{esc(name)}" maximized="0" width="262" solo="0" height="472" x="5">
        <instrumenttrack vol="{vol}" pan="{pan}" fxch="0" usemasterpitch="1" pitch="0" basenote="57" pitchrange="1">
          {instrument}
          {eldata(env_kind)}
          <chordcreator chord="0" chord-enabled="0" chordrange="1"/>
          <arpeggiator arpdir="0" arpcycle="0" arpmiss="0" arptime="200" arprange="1" arpmode="0" arp="0" arptime_denominator="4" arp-enabled="0" arpskip="0" arpgate="100" arptime_numerator="4" arptime_syncmode="0"/>
          <midiport inputchannel="0" outputprogram="1" fixedinputvelocity="-1" fixedoutputnote="-1" outputcontroller="0" basevelocity="100" fixedoutputvelocity="-1" writable="0" inputcontroller="0" outputchannel="1" readable="0"/>
          <fxchain numofeffects="{1 if fx else 0}" enabled="{1 if fx else 0}">{fx}</fxchain>
        </instrumenttrack>
        <pattern len="{total_ticks}" muted="0" name="{esc(name)}" steps="16" pos="0" type="1">
            {chr(10).join('            ' + n for n in notes) if notes else ''}
        </pattern>
      </track>
"""


FX_REVERB = '<effect on="1" wet="0.40" name="reverbsc"><reverbsc/></effect>'
FX_DELAY = '<effect on="1" wet="0.20" name="delay"><delay feedback="0.30" lfo_time="0" lfo_amount="0" lfo_speed="0" time="0.5" level="0.6" on="1"/></effect>'


# ── 变奏 → 音符 ────────────────────────────────────────────────────────
def build_notes(plan: dict) -> dict[str, list[str]]:
    """按 variations[] 逐段生成各轨音符。返回 {轨名: [note 行]}。"""
    tracks: dict[str, list[str]] = {}
    total = int(plan["total_ticks"])
    bpm = float(plan["bpm"])

    def put(name: str, s: str) -> None:
        tracks.setdefault(name, []).append(s)

    # ★ 段落的小节区间必须首尾相接，否则边界处会漏掉整小节 → 音乐出现空洞。
    #   踩过的坑：原写法 bar0=ceil(start/BAR)、bar1=floor(end/BAR)，两端各自向内收，
    #   当边界不落在小节线上时，中间那一小节不属于任何段 —— 实测漏了 4 个小节，
    #   而那正是重音所在处（重音落在空小节里，留白自然无从谈起）。
    #   改法：以「各段起始 tick 吸附到最近小节线」为共同分界，第 i 段 = [b[i], b[i+1])。
    vars_ = plan["variations"]
    bounds = [0]
    for v in vars_[1:]:
        bounds.append(int(round(int(v["start_tick"]) / BAR)))
    bounds.append(total // BAR)

    for vi, v in enumerate(vars_):
        t = v["texture"]
        layers = set(t["layers"])
        vel = int(t["velocity"])
        reg = int(t["register"])
        dens = t["density"]
        harm = t["harmony"]
        motif_tx = t["motif"]
        perc = t["percussion"]

        chords = CHORDS_TENSE if ("borrowed" in harm or "modal" in harm) else CHORDS_SAFE

        bar0, bar1 = bounds[vi], bounds[vi + 1]
        # 段落占满自己的小节区间（用 bar1*BAR 截断，而不是 end_tick）——
        # 否则小节尾会留下半截空洞（end_tick 很少正好落在小节线上）。
        lim = bar1 * BAR
        for b in range(bar0, bar1):
            bs = b * BAR
            chord = chords[b % len(chords)]

            # ── pad：每小节一个持续和弦 ──
            if "pad" in layers:
                for n, k in enumerate(chord):
                    put("Pad", note(bs, k + reg, BAR - 6,
                                    vel - 6 + (2 if n == 1 else 0), -14 + n * 14))

            # ── bass：根音。密度越高拍点越密 ──
            if "bass" in layers:
                root = chord[0] - 24 + reg
                if dens == "high":
                    for beat in range(4):
                        put("Bass", note(bs + beat * TPB, root + (0 if beat % 2 == 0 else 0),
                                         TPB - 8, vel + (6 if beat == 0 else -6)))
                elif dens == "mid":
                    put("Bass", note(bs, root, TPB * 2 - 8, vel + 4))
                    put("Bass", note(bs + TPB * 2, root, TPB * 2 - 8, vel - 4))
                else:
                    put("Bass", note(bs, root, BAR - 10, vel))

            # ── lead：动机的变形（变奏的灵魂）──
            if "lead" in layers or "pluck" in layers:
                tn = "Lead" if "lead" in layers else "Pluck"
                base = chord[0] + reg
                # 动机变形：模进 = 从和弦的三音起；倒影 = 音程反向；增值 = 时值 ×2
                if motif_tx.startswith("sequence"):
                    seq = [d % 3 for d in range(3)]
                    offs = [MOTIF[i] for i in [1, 2, 0]]
                elif motif_tx.startswith("retrograde") or motif_tx.startswith("augmented + inverted"):
                    offs = [-o for o in MOTIF[::-1]]
                else:
                    offs = list(MOTIF)
                aug = 2 if "augmented" in motif_tx else 1
                if dens == "high":
                    step, ndur, reps = TPB // 2, TPB // 2 - 4, 2
                elif dens == "mid":
                    step, ndur, reps = TPB, TPB - 6, 1
                else:
                    step, ndur, reps = TPB * 2, TPB * 2 - 6, 1
                ndur = min(ndur * aug, BAR)
                for r in range(reps):
                    for i, o in enumerate(offs):
                        pos = bs + r * (len(offs) * step) + i * step
                        if pos >= lim:
                            break
                        put(tn, note(pos, base + o, ndur,
                                     vel + (8 if i == len(offs) - 1 else 0),
                                     -10 + i * 10))

            # ── counter：对位声部（强调段才有）——动机的倒影，低八度 ──
            if "counter" in layers:
                base = chord[0] - 12 + reg
                for i, o in enumerate([-o for o in MOTIF]):
                    pos = bs + i * TPB
                    if pos < lim:
                        put("Counter", note(pos, base + o, TPB - 6, vel - 14, 18))

            # ── 打击 ──
            if perc in ("kick + hat", "kick"):
                for beat in (0, 2):
                    put("Kick", note(bs + beat * TPB, 57, 18, vel - 10))
                if dens == "high":
                    put("Kick", note(bs + TPB, 57, 18, vel - 26))
            if perc in ("kick + hat", "soft hat", "hat"):
                step = TPB // 2 if perc == "kick + hat" else TPB
                v = vel - 30 if perc == "soft hat" else vel - 22
                for k in range(0, BAR, step):
                    put("Hat", note(bs + k, 57, step - 4, v - (10 if (k // step) % 2 else 0), 28))

    return tracks


# ── 重音：牵引注意力 ────────────────────────────────────────────────────
# 音乐不能只会「划分层次」，还要会「强调重点」。
# 读 bgm-plan.json 的 accents[]，每处做三件事：
#   ① 留白 —— 重音前 breath_ticks 内撤掉旋律，把注意力腾出来
#   ② 抬起 —— 重音所在小节内所有音符力度 +lift
#   ③ 重击 —— 落拍加一记 kick（力度随当前织体走，pp 段也压得住）
MELODY = ("Lead", "Pluck")
_NOTE_RE = re.compile(
    r'<note vol="(-?\d+)" pan="(-?\d+)" len="(-?\d+)" pos="(-?\d+)" key="(-?\d+)"/>')


def parse_note(s: str) -> dict | None:
    m = _NOTE_RE.fullmatch(s.strip())
    if not m:
        return None
    vol, pan, ln, pos, key = (int(g) for g in m.groups())
    return {"vol": vol, "pan": pan, "len": ln, "pos": pos, "key": key}


def apply_accents(tracks: dict[str, list[str]], plan: dict) -> list[dict]:
    """把 accents[] 落到音符上；返回逐条实测证据。"""
    accs = plan.get("accents") or []
    if not accs:
        return []

    spans = [(int(v["start_tick"]), int(v["end_tick"]), int(v["texture"]["velocity"]))
             for v in plan["variations"]]

    def vel_at(t: int) -> int:
        for a, b, v in spans:
            if a <= t < b:
                return v
        return 70

    ev = []
    for a in accs:
        tick = int(a["tick"])
        breath = int(a.get("breath_ticks", 24))
        lift = int(a.get("lift", 14))

        # ① 留白：把重音前的半拍清空。
        #    实测教训：只看「音的起点」落在窗口里没用 —— 重音前那半拍通常没有新音起，
        #    只有**正在延音**的音。所以判据改成「音尾跨进窗口」→ 截断（而非整音删掉）。
        gap_at = tick - breath
        breath_cut = 0
        for nm in MELODY:
            lst = tracks.get(nm)
            if not lst:
                continue
            keep = []
            for s in lst:
                n = parse_note(s)
                if not n:
                    keep.append(s)
                    continue
                if n["pos"] < tick and n["pos"] + n["len"] > gap_at:
                    new_len = gap_at - n["pos"]
                    breath_cut += 1
                    if new_len < TPB // 4:          # 截完太短（≈1/4 拍）就别留残音
                        continue
                    s = note(n["pos"], n["key"], new_len, n["vol"], n["pan"])
                keep.append(s)
            tracks[nm] = keep

        # ② 抬起：重音所在小节内整体加力（先抬起，再落重击 —— 否则重击会被再加一次）
        lifted = 0
        for nm, lst in tracks.items():
            for i, s in enumerate(lst):
                n = parse_note(s)
                if n and tick <= n["pos"] < tick + BAR:
                    lst[i] = note(n["pos"], n["key"], n["len"],
                                  min(127, n["vol"] + lift), n["pan"])
                    lifted += 1

        # ③ 重击
        imp = min(127, vel_at(tick) + 34)
        tracks.setdefault("Kick", []).append(note(tick, 57, 18, imp))

        ev.append({"cue": a.get("cue"), "tick": tick, "bar": tick // BAR + 1,
                   "breath_cut": breath_cut, "impact_vol": imp, "lifted": lifted,
                   "text": a.get("text", "")})
    return ev


ACCENT_EVIDENCE: list[dict] = []      # apply_accents 的实测证据，供 main 打印

TRACK_SPEC = [
    # 名字, 音量, pan, 音源, 包络, 效果
    ("Pad",     62,   0, instr_pad(),        "pad",  FX_REVERB),
    ("Lead",    72,   0, instr_lead(True),   "lead", FX_REVERB),
    ("Counter", 58,   0, instr_lead(False),  "lead", FX_DELAY),
    ("Pluck",   70,   0, instr_lead(True),   "lead", FX_DELAY),
    ("Bass",    84,   0, instr_bass(),       "bass", ""),
    ("Kick",    82,   0, instr_sampler("drums/kick01.ogg", 205), "drum", ""),
    ("Hat",     78,  28, instr_sampler("drums/hihat_closed02.ogg", 135), "drum", ""),
]


def build_mmp(plan: dict, master: float = 0.30) -> str:
    tracks_notes = build_notes(plan)
    evidence = apply_accents(tracks_notes, plan)
    # 重音会往轨道尾部追加音符 → 落盘前按 pos 排序（LMMS 靠 pos 定位不靠顺序，但乱序难查）
    for lst in tracks_notes.values():
        lst.sort(key=lambda s: (parse_note(s) or {"pos": 0})["pos"])
    ACCENT_EVIDENCE.extend(evidence)
    total = int(plan["total_ticks"])
    bpm = plan["bpm"]

    body = []
    for name, vol, pan, instr, env, fx in TRACK_SPEC:
        ns = tracks_notes.get(name, [])
        if not ns:
            continue                      # 全曲都没用到的声部不建轨
        body.append(track(name, vol, pan, instr, env, fx, ns, total))

    return f"""<?xml version="1.0"?>
<!DOCTYPE lmms-project>
<lmms-project version="1.0" type="song" creator="LMMS" creatorversion="1.2.2">
  <head bpm="{bpm}" timesig_numerator="4" timesig_denominator="4" mastervol="100" masterpitch="0"/>
  <song>
    <trackcontainer minimized="0" type="song" y="5" visible="1" maximized="0" width="600" height="300" x="5">
{''.join(body)}    </trackcontainer>
    <track type="6" muted="0" name="Automation track" solo="0">
      <automationtrack/>
      <automationpattern len="{BAR}" name="Tempo" tens="1" pos="0" prog="0" mute="0"/>
      <automationpattern len="{BAR}" name="Master volume" tens="1" pos="0" prog="0" mute="0"/>
    </track>
    <fxmixer minimized="0" y="310" visible="1" maximized="0" width="543" height="333" x="5">
      <fxchannel soloed="0" muted="0" num="0" name="Master" volume="{master:.2f}">
        <fxchain numofeffects="0" enabled="0"/>
      </fxchannel>
    </fxmixer>
    <projectnotes minimized="0" y="10" visible="0" maximized="0" width="800" height="400" x="700">Ideaform · BGM 变奏（由 bgm-plan.json 生成）</projectnotes>
    <timeline lp1pos="{total}" lp0pos="0" lpstate="0"/>
    <controllers/>
  </song>
</lmms-project>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="变奏计划 → LMMS 工程")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", default="bgm.mmp")
    ap.add_argument("--master", type=float, default=0.30,
                    help="Master 音量。渲染后必须实测峰值 < 0 dBFS 且有净空，"
                         "否则调小重渲（顶穿 0 dBFS 就是削顶，不可交付）")
    a = ap.parse_args()

    p = Path(a.plan)
    if not p.exists():
        print(f"✗ 找不到 {p}", file=sys.stderr)
        return 2
    plan = json.loads(p.read_text(encoding="utf-8"))

    mmp = build_mmp(plan, master=a.master)
    Path(a.out).write_text(mmp, encoding="utf-8")

    # 先自检再渲染（手写 XML 极易出错）
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(a.out).getroot()
    except ET.ParseError as e:
        print(f"✗ 生成的 XML 不合法: {e}", file=sys.stderr)
        return 1

    ns = root.findall(".//note")
    tk = root.findall(".//track[@type='0']")
    print(f"✓ 已生成 {a.out}")
    print(f"  bpm={plan['bpm']}  lp1pos={plan['total_ticks']}  轨道 {len(tk)}  音符 {len(ns)}")
    print(f"\n  各轨音符数（变奏是否落地，先看这张表）：")
    for t in tk:
        nm = t.get("name")
        cnt = len(t.findall(".//note"))
        print(f"    {nm:<10}{cnt:>5}")

    # 分段统计 —— 音高层漏加段落偏移时 XML 仍合法、总数正常，只有跨段统计能发现
    print(f"\n  段落 × 轨道 音符数矩阵：")
    bars = {}
    for v in plan["variations"]:
        bars[v["index"]] = (int(v["start_tick"]), int(v["end_tick"]))
    hdr = "    段  " + "".join(f"{t.get('name')[:7]:>8}" for t in tk)
    print(hdr)
    for idx, (t0, t1) in bars.items():
        row = f"    {idx}   "
        for t in tk:
            n = sum(1 for x in t.findall(".//note") if t0 <= int(x.get("pos")) < t1)
            row += f"{n:>8}"
        print(row)
    # ★ 空小节自检 —— 段落边界不落在小节线上时，边界处会漏掉整小节（音乐出现空洞）。
    #   这个错误在 XML 里完全合法、音符总数也正常，只有逐小节点名才能发现。
    nb = int(plan["total_ticks"]) // BAR
    per_bar = [0] * nb
    for t in tk:
        for x in t.findall(".//note"):
            i = int(x.get("pos")) // BAR
            if 0 <= i < nb:
                per_bar[i] += 1
    holes = [i + 1 for i, c in enumerate(per_bar) if c == 0]
    thin = [i + 1 for i, c in enumerate(per_bar) if 0 < c <= 1]
    if holes:
        print(f"\n  ✗ 空洞小节（完全没有音符）: {holes}"
              f"\n     → 段落边界没落在小节线上。见 build_notes 里 bounds[] 的注释。")
    else:
        print(f"\n  ✓ 无空洞小节（共 {nb} 小节，逐小节都有人声部）")
    if thin:
        print(f"  ⚠ 极稀薄小节（仅 1 个音符）: {thin}")

    # 重音证据 —— 光看"有没有加 kick"不够，要看到留白清了几音、抬了多大力
    if ACCENT_EVIDENCE:
        print(f"\n  重音点落地情况（牵引注意力）{len(ACCENT_EVIDENCE)} 处：")
        for e in ACCENT_EVIDENCE:
            print(f"    第{e['cue']:>2}条  第{e['bar']:>2}小节  "
                  f"留白清空 {e['breath_cut']} 音  重击 vel={e['impact_vol']}  "
                  f"小节内抬力 {e['lifted']} 音")
    else:
        print("\n  （无重音点 —— 音乐只做了「分段」，没做「强调」）")

    print("\n  下一步渲染：")
    print(f'    "$VW_LMMS_APPRUN" --allowroot render {a.out} -f wav -o out/bgm.wav')
    return 0


if __name__ == "__main__":
    sys.exit(main())
