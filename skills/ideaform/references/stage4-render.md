# 阶段四 · Remotion 渲染与音轨集成

> Remotion 只负责三件事：**画面组织、音轨集成、最终渲染**。
> 语法细节见 `remotion-best-practices` 技能；本篇只讲本工作流特有的部分。

---

## 1. 画面：以解说音轨为时间主轴

```bash
cp out/timeline.ts <remotion项目>/src/timeline.ts
cd <remotion项目>
export TMPDIR="$VW_TMPDIR"        # ★ 必须（本机 /tmp 只有 10MB）
npx remotion studio               # 先给用户看预览，别急着渲
```

### 幕边界从 `CUES` 推导，**不要手写帧号**

```ts
import { CUES, TOTAL_FRAMES, FPS } from "./timeline";

export const SCENES = {
  s1: { from: 0,              dur: CUES[2].start },
  s2: { from: CUES[2].start,  dur: CUES[4].start - CUES[2].start },
  s3: { from: CUES[4].start,  dur: TOTAL_FRAMES - CUES[4].start },
} as const;
```

写死帧号的后果：改一句台词 → 时间轴整体平移 → 画面错位且**不报错**。

### composition 必须与时间轴对齐

```tsx
<Composition id="Ep07" component={Ep07}
             durationInFrames={TOTAL_FRAMES}   // ← 来自时间轴
             fps={FPS} width={1920} height={1080} />
```

---

## 2. 音轨集成（两条路线）

### 路线 A · Remotion 集成（推荐，默认）

```tsx
import { Audio, staticFile } from "remotion";

<Audio src={staticFile("voice.wav")} />
<Audio src={staticFile("bgm.wav")} volume={0.1694} />
```

渲出的 mp4 **自带音轨**，不需要再合流。
`volume` 那个数用实测 RMS 反推：

```bash
bash scripts/mix-av.sh --plan-only --voice out/voice.wav --bgm out/bgm.wav --drop 9
# 解说 RMS = -23.46 dBFS   BGM RMS = -17.04 dBFS
# → BGM 需加 -15.42 dB  →  volume = 0.1694
```

> 音轨文件要放进工程的 `public/` 目录，`staticFile()` 才能找到。

### 路线 B · 后合成（视频已渲好 / 要重配音）

```bash
bash scripts/mix-av.sh --video silent.mp4 --voice out/voice.wav --bgm out/bgm.wav --out out/final.mp4
```

### 🔴 路线 B 的铁律：**必须显式 `-map`**

```bash
ffmpeg -y -i silent.mp4 -i voice.wav \
       -map 0:v:0 -map 1:a:0 \
       -c:v copy -c:a aac -b:a 192k -ar 48000 -ac 2 -shortest final.mp4
```

**根因 `[实测]`**：Remotion 输出的 mp4 **自带一条静音 AAC 轨**。
不加 `-map` 时 ffmpeg 自动选中的是 `0:a:0` —— 也就是**那条静音轨**，
于是把真正的配音整个丢掉，输出音轨只有约 **2275 bps**。

症状极阴：**命令退出码 0、文件完整、时长正确、播放器正常打开 —— 就是没声音。**
（唯一线索是成品体积反而比无音轨版小。）

**自检（必做）**：

```bash
AB=$(ffprobe -v error -select_streams a:0 -show_entries stream=bit_rate \
     -of default=nw=1:nk=1 final.mp4 | tr -d ' ,\r\n')
[ "${AB:-0}" -gt 64000 ] || echo "音轨疑似静音（${AB} bps）→ 检查 -map"
```

`mix-av.sh` 与 `verify-video.py` 都已内置这条自检。

---

## 3. 渲染

```bash
export TMPDIR="$VW_TMPDIR"
npx remotion render Ep07 out/video.mp4 --concurrency=3 --log=info
```

### 长片必须分段渲染 + 无损拼接 `[实测]`

**症状**：7 分钟片（12959 帧 @30fps）单次渲染跑到一半挂了：

```
TimeoutError: waiting for the page to render the React component at frame 5824 failed:
timeout 33000ms exceeded
```

**根因不是代码**（故障点那个场景单独渲染 100 帧完全正常）。
是 **`--concurrency=4` 时 4 个 chrome 各开 1920×1080 页面，把内存顶到边缘**
→ 事件循环被 GC/换页卡住 → 超过 Remotion 默认的 `delayRender` 30s 超时被判死。
（本机 16 核 / 7.6GB；**内存是瓶颈，不是 CPU**。）

**正解**：

```bash
# 逐段：--frames=A-B 是闭区间；并发降到 2~3
npx remotion render Ep07 out/chunk_00.mp4 --frames=0-2591     --concurrency=3
npx remotion render Ep07 out/chunk_01.mp4 --frames=2592-5183  --concurrency=3
# 每段渲完立刻用 ffprobe 核 nb_frames 是否等于期望值

# 拼接（同编码参数 → -c copy 无损、秒级）
printf "file 'chunk_00.mp4'\nfile 'chunk_01.mp4'\n" > list.txt
ffmpeg -y -f concat -safe 0 -i list.txt -c copy out/video-silent.mp4
```

要点：

- `--frames=A-B` 是**闭区间**（`5824-5923` = 恰好 100 帧）。
- 分段的好处是**炸一段只重跑一段**；脚本里做「已存在且帧数正确 → 跳过」，天然可断点续跑。
- 段边界不会导致画面断裂（动画按绝对帧号索引，拼接处天然连续）。
- **拼完必须再核一次总帧数**。

### ⚠️ 两个 Remotion CLI 的坑

1. **每一条 `npx remotion *` 都要带 `TMPDIR`**。没设时打包写 `/tmp`（本机 10MB tmpfs）
   → `ENOSPC: no space left on device`。
2. **`npx remotion render --help` 也会先打包整个项目**。查参数优先读
   `node_modules/@remotion/cli/dist/` 源码，别依赖 `--help`。

---

## 4. 封面

封面是一个**独立的静态 composition**（`durationInFrames={1}`）：

```bash
npx remotion still Cover out/cover.png \
    --props='{"kicker":"...","title":"...","subtitle":"...","episode":"07"}'
```

⚠️ **组件内不要用动画**（`useCurrentFrame()` 在 still 时恒为 0，
动画初值会让元素不可见）。版式与自检见 [`cover.md`](cover.md)。

---

## 5. 交付前自检（**必做，不许跳**）

```bash
# 成片
VW_FFPROBE="$VW_FFPROBE" python3 scripts/verify-video.py \
    video out/final.mp4 --frames 732 --fps 30
# 封面
python3 scripts/verify-video.py cover out/cover.png --layout cover
```

判据：

| 项 | 阈值 |
|---|---|
| 帧数 | 严格等于规划值 |
| 时长 | 与 帧数/fps 偏差 ≤ 2 帧 |
| 音轨码率 | > 64000 bps（防静音轨） |
| 封面尺寸 | 1920×1080 |
| 封面文字 | 文字区墨色像素 > 300 |
| 封面轴线 | 标题区红色像素 < 60 |

**任一项不过 → 拒绝交付**，不靠形容词描述"应该没问题"。

---

## 6. 交付形态

- **成片 MP4**（H.264 + AAC 192k，1920×1080）—— 首选，体积可控。
- **封面 PNG**（1920×1080）—— 与成片同视觉系统。
- 若用户要长期保存母版，另给 WAV 母版音轨（见 `stage2-tts.md` §9）。
- ⚠️ **别交付 ≥30MB 的 WAV** —— 大文件在传输中易被截断，用户会误报"文件损坏"。
