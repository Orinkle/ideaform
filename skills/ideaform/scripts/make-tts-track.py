#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS 音轨生成器 —— 把台词/SRT 变成一条与视频等长、逐条严格对齐的解说音轨。
（ideaform · 阶段二：以解说音轨为时间主轴）

产出「解说音轨 = 时间主轴」：它决定画面帧数、BGM 变奏点、成片长度。
所以**永远先跑本脚本定轴，再去写 Remotion 的 composition**（顺序铁律）。

两段式调速（都是为了音质）
  第一段：逐条以「该条自己的原生语速」重新合成 —— 调的是神经网络合成语速，
          不是后期变速，音质几乎无损。天然就够用的条目原速合成，不动。
  第二段：对残余缺口做小幅 atempo 修正（正常只有 ±10% 量级，听不出来）。
  ⇒ 每条语音严格落在自己的槽位内，零重叠、零漂移。

用法
  # ★ 首选：只有台词、还没定时间轴 —— 量自然语速、排出时间轴 + 出音轨（全程原速）
  <venv>/bin/python make-tts-track.py --lines 台词.txt --fps 30 --audio
  # 已有 SRT、时间码定死了，只能反过来适配 —— 两段式调速出音轨
  <venv>/bin/python make-tts-track.py --measure   # 只测：合成 + 报总时长，不拼轨
  <venv>/bin/python make-tts-track.py             # 完整出轨
  VOICE=zh-CN-YunyangNeural <venv>/bin/python make-tts-track.py

⚠️ 必须用 venv 的解释器跑（edge-tts 装在 venv 里）：
   venv 路径见契约 tools.venv.python

⚠️ 顺序铁律：**渲染前先匹配自然语速**。先按台词量出真实时长 → 用它定 Remotion 帧数 → 再渲染。
   先写死时间码、再把 TTS 硬塞进固定槽位，是反的（实测会被迫压缩 1.218x）。

可配置项（全部走环境变量；未设时优先从 toolchain.json 取）
  VOICE        声线，默认 zh-CN-YunxiNeural
  SRT          字幕文件，默认 $PWD/out/ideaform-intro.srt
  OUTDIR       产出目录，默认 $PWD/out
  BASENAME     产出文件名（不含扩展名）
  WORKDIR      中间缓存目录，默认 $PWD/.tts（保留它可让重跑只花几秒）
  RATE_MAX     原生语速上限%（默认 55，超出交给 atempo）
  TEMPO_MAX    残余 atempo 上限（默认 1.20）
  SKIP_NATIVE  倍率低于此值视为天然够用、保持原速（默认 1.02）
  TARGET_PEAK  目标峰值 dBFS（默认 -1.0）
  FFMPEG/FFPROBE  显式指定可执行文件（默认契约 → Remotion 自带 → 系统 PATH）
"""
import argparse, array, asyncio, hashlib, json, math, os, re, shutil, subprocess, sys, wave

VOICE = os.environ.get("VOICE", "zh-CN-YunxiNeural")
RATE_MAX = float(os.environ.get("RATE_MAX", "55"))   # 原生语速上限（%），超过交给 atempo
RATE = os.environ.get("RATE", "+0%")                 # --lines 模式用的语速；+0% 即真·自然语速
CONC = int(os.environ.get("CONC", "3"))
TEMPO_MAX = float(os.environ.get("TEMPO_MAX", "1.20"))  # 残余 atempo 上限
SKIP_NATIVE = float(os.environ.get("SKIP_NATIVE", "1.02"))  # 低于此倍率视为天然够用
TARGET_PEAK = float(os.environ.get("TARGET_PEAK", "-1.0"))  # 目标峰值 dBFS
# 说明：本机 ffmpeg 是 Remotion 附带的精简版（仅 volume/atempo/loudnorm/apad/atrim/concat…），
#       没有 acompressor / volumedetect，故收尾只做「静态峰值归一化」——零延迟，不破坏字幕对齐。
COMPRESS = os.environ.get("COMPRESS", "0") == "1"   # 默认关（本机无 acompressor）

HERE = os.path.dirname(os.path.abspath(__file__))
CWD = os.getcwd()
SRT = os.environ.get("SRT") or os.path.join(CWD, "out", "ideaform-intro.srt")
OUTDIR = os.environ.get("OUTDIR") or os.path.join(CWD, "out")
BASENAME = os.environ.get("BASENAME") or "ideaform-intro-voice"
WORK = os.environ.get("WORKDIR") or os.path.join(CWD, ".tts")
C1 = os.path.join(WORK, "clips")    # 第一段：原速
C2 = os.path.join(WORK, "clips2")   # 第二段：逐条最优语速


# ─────────────────────────────────────────────────────────────────────────
# 契约衔接：优先从 toolchain.json 取工具路径（由 ideaform-setup 写入）
# 契约里没有 / 不存在时，退回本脚本自带的自动发现逻辑（见 _resolve_exe）。
# 用 setdefault 是为了让显式环境变量仍然最高优先。
# ─────────────────────────────────────────────────────────────────────────
def _load_contract():
    cp = os.environ.get("VW_CONTRACT") or os.path.expanduser(
        "~/.config/ideaform/toolchain.json")
    if not os.path.exists(cp):
        return None
    try:
        with open(cp, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


_CONTRACT = _load_contract()
if _CONTRACT:
    _t = _CONTRACT.get("tools", {})
    _lmm = _t.get("lmms") or {}
    for env_key, val in (
        ("FFMPEG", (_t.get("ffmpeg") or {}).get("path")),
        ("FFPROBE", (_t.get("ffprobe") or {}).get("path")),
        ("TMPDIR", _CONTRACT.get("tmpdir")),
    ):
        if val and not os.environ.get(env_key):
            os.environ[env_key] = val


def _find_compositor():
    """向上找 Remotion 自带的 ffmpeg 目录，找不到再退到常见位置。"""
    d = CWD
    for _ in range(6):
        c = os.path.join(d, "node_modules", "@remotion", "compositor-linux-x64-gnu")
        if os.path.isdir(c):
            return c
        d = os.path.dirname(d)
    c = os.path.expanduser("~/tools/remotion-app/node_modules/@remotion/compositor-linux-x64-gnu")
    return c if os.path.isdir(c) else None


def _resolve_exe(name):
    """优先级：环境变量 → Remotion 自带 → 系统 PATH。"""
    for cand in (os.environ.get(name.upper()),):
        if cand and os.access(cand, os.X_OK):
            return cand
    d = _find_compositor()
    if d and os.access(os.path.join(d, name), os.X_OK):
        return os.path.join(d, name)
    return shutil.which(name) or name


# 注意：Remotion 附带的 ffmpeg 是精简版（无 acompressor/volumedetect）。
# 若本机装了完整 ffmpeg，用环境变量 FFMPEG=/usr/bin/ffmpeg 覆盖即可。
FFMPEG = _resolve_exe("ffmpeg")
FFPROBE = _resolve_exe("ffprobe")


def ts2sec(s):
    h, m, rest = s.split(":")
    sec, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def parse_srt(path):
    raw = open(path, encoding="utf-8").read().replace("\r\n", "\n")
    cues = []
    for blk in [b for b in raw.split("\n\n") if b.strip()]:
        lines = [x for x in blk.split("\n") if x.strip()]
        mt = re.match(r"(\d+:\d+:\d+,\d+)\s*-->\s*(\d+:\d+:\d+,\d+)", lines[1])
        if mt:
            cues.append({"start": ts2sec(mt.group(1)), "end": ts2sec(mt.group(2)),
                         "text": " ".join(lines[2:]).strip()})
    return cues


def dur(path):
    o = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path],
                       capture_output=True, text=True).stdout.strip().strip(",")
    try:
        return float(o)
    except ValueError:
        return 0.0


def peak_dbfs(path):
    """用标准库直接读样本测峰值。
    注意：Remotion 自带的精简版 ffmpeg 不含 volumedetect，
    用它的输出做归一化会静默失效 —— 故此处自己算。"""
    w = wave.open(path, "rb")
    nf = w.getnframes()
    raw = w.readframes(nf)
    w.close()
    a = array.array("h")
    a.frombytes(raw)
    if not a:
        return -99.0
    pk = max(max(a), -min(a)) / 32768.0
    return 20 * math.log10(pk) if pk > 1e-9 else -99.0


async def synth(text, rate, path, sem, label=""):
    """合成单条；成功返回时长，失败抛异常。rate 形如 '+35%'。"""
    import edge_tts
    async with sem:
        last = "?"
        for attempt in range(5):
            try:
                await edge_tts.Communicate(text, VOICE, rate=rate).save(path)
                d = dur(path)
                if os.path.getsize(path) > 1500 and d > 0.05:
                    return d
                last = "空/过短音频"
            except Exception as e:
                last = type(e).__name__
            await asyncio.sleep(0.8 * (attempt + 1))
        raise RuntimeError(f"合成失败({label}): {last}")


def clip_name(i, text, rate):
    """缓存文件名带内容哈希。
    ⚠️ 只用序号做键是危险的：一旦改动/删减台词，后面的序号整体平移，
    旧音频会被当成"这条已合成过"而复用 —— 结果就是画面对、声音全错，且不报错。"""
    h = hashlib.md5(f"{rate}|{text}".encode("utf-8")).hexdigest()[:8]
    return f"{i:02d}-{h}.mp3"


async def stage_synth(cues, outdir, rates, tag):
    """按给定语速表批量合成（缓存命中则跳过）。returns list[音频路径]"""
    os.makedirs(outdir, exist_ok=True)
    sem = asyncio.Semaphore(CONC)
    paths = [None] * len(cues)

    async def w(i):
        name = clip_name(i, cues[i]["text"], rates[i])
        p = os.path.join(outdir, name)
        if os.path.exists(p) and dur(p) > 0.05:
            paths[i] = p
            return
        await synth(cues[i]["text"], rates[i], p, sem, label=f"#{i+1} {rates[i]}")
        paths[i] = p

    await asyncio.gather(*(w(i) for i in range(len(cues))))
    print(f"  [{tag}] 合成完成，总时长 {sum(dur(p) for p in paths):.2f}s")
    return paths


def fmt_rate(pct):
    return f"{'+' if pct >= 0 else ''}{int(round(pct))}%"


def make_silence(path, seconds, sr=48000, ch=2):
    """用标准库生成静音 WAV（不依赖 ffmpeg 的 anullsrc，避免又踩滤镜缺失的坑）。"""
    n = max(1, round(seconds * sr))
    with wave.open(path, "wb") as w:
        w.setnchannels(ch); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"\x00" * (n * ch * 2))
    return path


def fmt_ts(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(rows, total, path):
    """从排好的时间轴导出 SRT（与音轨、画面同源，天然对齐）。"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(f"{r['i']}\n{fmt_ts(r['start'])} --> {fmt_ts(r['end'])}\n{r['text']}\n\n")
    return path


def build(cues, clips, out_wav, out_mp3, prefix=None):
    parts, warns = [], []
    for i, (c, p) in enumerate(zip(cues, clips)):
        slot = round(c["end"] - c["start"], 3)
        d = dur(p)
        tempo = d / slot if d > slot else 1.0
        if tempo > TEMPO_MAX:
            warns.append(f"#{i+1} 残余提速 {tempo:.3f}x 超上限，语音被裁切：{c['text'][:26]}")
            tempo = TEMPO_MAX
        seg = os.path.join(WORK, "seg", f"{i:02d}.wav")
        os.makedirs(os.path.dirname(seg), exist_ok=True)
        af = []
        if tempo > 1.002:
            t = tempo
            while t > 2.0:
                af.append("atempo=2.0"); t /= 2.0
            af.append(f"atempo={t:.6f}")
        af += ["aresample=48000", "aformat=sample_fmts=s16:channel_layouts=stereo",
               "apad", f"atrim=0:{slot:.3f}", "asetpts=N/SR/TB"]
        subprocess.run([FFMPEG, "-y", "-v", "error", "-i", p, "-af", ",".join(af),
                        "-c:a", "pcm_s16le", seg], check=True)
        parts.append(seg)

    lst = os.path.join(WORK, "concat.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.writelines(f"file '{p}'\n" for p in (list(prefix or []) + parts))
    raw_wav = os.path.join(WORK, "raw.wav")
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c:a", "pcm_s16le", raw_wav], check=True)
    total = dur(raw_wav)

    # —— 收尾：静态峰值归一化（只改音量，零延迟，不动时序）——
    src = raw_wav
    if COMPRESS:
        comp = os.path.join(WORK, "comp.wav")
        subprocess.run([FFMPEG, "-y", "-v", "error", "-i", raw_wav, "-af",
                        "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=180",
                        "-c:a", "pcm_s16le", comp], check=True)
        src = comp

    pk = peak_dbfs(src)
    gain = TARGET_PEAK - pk
    print(f"  归一化：实测峰值 {pk:.2f} dBFS → 目标 {TARGET_PEAK:.2f} dBFS（增益 {gain:+.2f} dB）")
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", src,
                    "-af", f"volume={gain:.2f}dB", "-c:a", "pcm_s16le", out_wav],
                   check=True)
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", out_wav, "-c:a", "libmp3lame",
                    "-b:a", "192k", out_mp3], check=True)
    return total, warns


def plan_lines(lines_path, fps, lead, gap, tail, plan_out, ts_out, audio=False):
    """【渲染前先定轴】只量自然语速并排出时间轴，不产出音轨。

    这是推荐的工作流第一步：拿到台词就先把自然语速量出来，
    用它来定 Remotion 的帧数，而不是先拍脑袋定时间码再硬塞 TTS。
    """
    texts = [l.strip() for l in open(lines_path, encoding="utf-8-sig").read().splitlines()
             if l.strip()]
    if not texts:
        sys.exit(f"台词文件是空的：{lines_path}")

    cues = [{"text": t, "start": 0.0, "end": 0.0} for t in texts]
    print(f"台词 {len(texts)} 条 | 声线 {VOICE} | 自然语速 | fps {fps:g}")
    print(f"留白：首 {lead}s / 条间 {gap}s / 末 {tail}s（可用 --lead/--gap/--tail 调）\n")
    paths = asyncio.run(stage_synth(cues, os.path.join(WORK, "lines"),
                                    [RATE] * len(cues), "自然语速"))
    ds = [dur(p) for p in paths]

    t = lead
    rows = []
    clip_paths = []
    for i, (txt, p, d) in enumerate(zip(texts, paths, ds), 1):
        start, end = t, t + d
        rows.append({"i": i, "text": txt, "start": round(start, 3), "end": round(end, 3),
                     "dur": round(d, 3),
                     "frameStart": round(start * fps), "frameEnd": round(end * fps),
                     "frames": round(d * fps)})
        clip_paths.append(p)
        print(f"  {i:>2}  {d:5.2f}s  {round(d*fps):>4}帧   「{txt[:30]}」")
        t = end + gap
    total = t - gap + tail
    print(f"\n自然语速合计 {sum(ds):.2f}s")
    print(f"加留白后成片时长 {total:.2f}s = {round(total*fps)} 帧 @ {fps:g}fps")
    print(f"→ 这个帧数才是 Remotion composition 该用的总长；{round(total*fps)} 帧 / {fps:g} = {total:.2f}s")

    os.makedirs(OUTDIR, exist_ok=True)
    json.dump({"voice": VOICE, "fps": fps, "lead": lead, "gap": gap, "tail": tail,
               "total_sec": round(total, 3), "total_frames": round(total * fps),
               "cues": rows},
              open(plan_out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(ts_out, "w", encoding="utf-8") as f:
        f.write(f"// 由 make-tts-track.py --lines 生成：自然语速实测，勿手改时间码\n")
        f.write(f"export const FPS = {fps:g};\n")
        f.write(f"export const TOTAL_FRAMES = {round(total * fps)};\n")
        f.write("export const CUES = [\n")
        for r in rows:
            txt = r["text"].replace("\\", "\\\\").replace('"', '\\"')
            f.write(f'  {{ start: {r["frameStart"]}, end: {r["frameEnd"]}, '
                    f'text: "{txt}" }},\n')
        f.write("] as const;\n")
    print(f"\n已写出：\n  {plan_out}\n  {ts_out}")

    if audio:
        # 关键：每段必须带上"到下一句开始为止"的留白（= 语音 + gap），最后一段带上 tail，
        # 前面再补 lead 的静音。否则音轨只有纯语音长度，整条与画面错位（踩过这个坑）。
        slots = []
        for i, r in enumerate(rows):
            nxt = rows[i + 1]["start"] if i + 1 < len(rows) else total
            slots.append(round(nxt - r["start"], 3))
        b_cues = [{"start": rows[i]["start"], "end": rows[i]["start"] + slots[i],
                   "text": rows[i]["text"]} for i in range(len(rows))]
        lead_wav = make_silence(os.path.join(WORK, "lead.wav"), lead)
        out_wav = os.path.join(OUTDIR, BASENAME + ".wav")
        out_mp3 = os.path.join(OUTDIR, BASENAME + ".mp3")
        got, warns = build(b_cues, clip_paths, out_wav, out_mp3, prefix=[lead_wav])
        srt = write_srt(rows, total, os.path.join(OUTDIR, BASENAME + ".srt"))
        print("\n音轨（全程原速，零变速）：")
        for p in (out_wav, out_mp3):
            print(f"  {os.path.basename(p)}  {os.path.getsize(p)/1048576:.2f} MB  {dur(p):.3f}s")
        print(f"  共 {len(rows)} 段；字幕 {os.path.basename(srt)}（与音轨同源，天然对齐）")
        print(f"  与规划时长核对：{got:.3f}s vs {total:.3f}s  偏差 {abs(got-total)*1000:.1f} ms "
              f"→ {'✔ 通过' if abs(got-total) < 0.05 else '✘ 超限'}")
        for w in warns:
            print("  ⚠ " + w)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--lines", metavar="FILE",
                    help="纯台词文件（每行一条）。只做自然语速测量 + 时间轴规划，不产出音轨。")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--lead", type=float, default=0.3, help="首条前留白秒")
    ap.add_argument("--gap", type=float, default=0.25, help="条与条之间的静默秒")
    ap.add_argument("--tail", type=float, default=1.0, help="末条后留白秒")
    ap.add_argument("--plan-out", default=None)
    ap.add_argument("--ts-out", default=None)
    ap.add_argument("--audio", action="store_true",
                    help="--lines 模式下顺带产出音轨（全程原速，零变速）")
    args = ap.parse_args()

    for exe in (FFMPEG, FFPROBE):
        if not (exe and os.access(exe, os.X_OK)):
            sys.exit(f"缺少可执行文件：{exe}（可用环境变量 FFMPEG/FFPROBE 指定）")

    if args.lines:
        plan_out = args.plan_out or os.path.join(OUTDIR, BASENAME + ".plan.json")
        ts_out = args.ts_out or os.path.join(OUTDIR, BASENAME + ".plan.ts")
        plan_lines(args.lines, args.fps, args.lead, args.gap, args.tail, plan_out, ts_out,
                   audio=args.audio)
        return

    if not os.path.exists(SRT):
        sys.exit(f"找不到字幕文件：{SRT}（可用环境变量 SRT 指定）")

    cues = parse_srt(SRT)
    total = sum(c["end"] - c["start"] for c in cues)
    print(f"字幕 {len(cues)} 条 | 视频全长 {total:.2f}s | 声线 {VOICE} | 并发 {CONC}\n")

    print("第一段：原速合成，量出每条的自然时长")
    paths1 = asyncio.run(stage_synth(cues, C1, ["+0%"] * len(cues), "原速"))
    d1 = [dur(p) for p in paths1]

    # 逐条最优原生语速
    rates, keep_native = [], 0
    for c, d in zip(cues, d1):
        slot = c["end"] - c["start"]
        r = d / slot
        if r <= SKIP_NATIVE:
            rates.append("+0%"); keep_native += 1
        else:
            pct = min((r - 1) * 100 * 0.98, RATE_MAX)   # ×0.98 留一点给 atempo
            rates.append(fmt_rate(pct))

    print(f"\n第二段：{len(cues)-keep_native} 条按各自语速重合成（{keep_native} 条天然够用、保持原速）")
    paths2 = asyncio.run(stage_synth(cues, C2, rates, "调优"))
    d2 = [dur(p) for p in paths2]

    resid = [d2[i] / (cues[i]["end"] - cues[i]["start"]) for i in range(len(cues))]
    over = [(i + 1, resid[i], cues[i]["text"][:26]) for i in range(len(cues))
            if resid[i] > TEMPO_MAX]
    print(f"\n合成总时长 {sum(d2):.2f}s vs 视频 {total:.2f}s "
          f"→ 净需压缩 {sum(d2)/total:.3f}x")
    print(f"残余 atempo：均值 {sum(resid)/len(resid):.3f}x  最大 {max(resid):.3f}x  "
          f"超上限 {len(over)} 条")
    for i, r, t in over:
        print(f"   ★ #{i:>2} {r:.3f}x  {t}")

    if args.measure:
        return

    print("\n第三段：裁到槽位 → 顺序拼接 → 归一化")
    os.makedirs(OUTDIR, exist_ok=True)
    out_wav = os.path.join(OUTDIR, BASENAME + ".wav")
    out_mp3 = os.path.join(OUTDIR, BASENAME + ".mp3")
    got, warns = build(cues, paths2, out_wav, out_mp3)

    print("\n=== 产出 ===")
    for p in (out_wav, out_mp3):
        print(f"  {os.path.basename(p)}  {os.path.getsize(p)/1048576:.2f} MB  {dur(p):.3f}s")
    delta = abs(got - total)
    print(f"时长核对：{got:.3f}s vs 视频 {total:.3f}s  偏差 {delta*1000:.1f} ms → "
          f"{'✔ 通过' if delta < 0.05 else '✘ 超限'}")
    if warns:
        print("\n⚠ 顶格提速仍溢出槽位（已裁切）：")
        for w in warns:
            print("  " + w)

    json.dump({"voice": VOICE, "rate_max": RATE_MAX, "cues": len(cues),
               "video_sec": total, "audio_sec": got,
               "rates": rates, "durations": d2},
              open(os.path.join(WORK, "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
