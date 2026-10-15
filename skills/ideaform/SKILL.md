---
name: ideaform
description: 生产「构造主义解说视频」的四阶段流水线：文稿 → TTS 解说音轨（时间主轴）→ LMMS BGM（用变奏标记论述层次）→ Remotion 渲染成片 + 封面。当用户要做解说视频/知识视频/口播视频，或要做"以解说配音为时间轴、BGM 随论述层次变奏"的成片时使用。前提：已由 ideaform-setup 配好环境并写出 toolchain.json 路径契约。
description_en: Four-stage pipeline for constructivist explainer videos - script, TTS narration track (the time master), LMMS BGM whose variations mark narrative layer changes, and Remotion render plus cover. Requires a toolchain.json path contract written by ideaform-setup.
license: MIT
agent_created: true
disable: false
---

# 构造主义解说视频 · 工作流

**一条时间主轴，三个下游全部从它派生。**

```
① 文稿            ② TTS 定轴                ③ BGM 变奏            ④ 成片
   文字    ──→   解说音轨（时间主轴）──→    LMMS 音乐（层次）──→   Remotion 画面 + 音轨集成 + 封面
                          │                        ▲
                          └──── 层次边界时间点 ─────┘
```

- **画面帧数**由 TTS 的自然语速长出（不是反过来压缩语速）
- **BGM 的变奏点**卡在解说的**层次切换点**上
- **成片**以解说音轨为基准对齐，BGM 只做衬底

---

## 0. 起步：先读路径契约（**这一步不能跳**）

本技能不自己找工具，一切路径来自环境配置技能写下的契约：

```
$VW_CONTRACT  （默认 ~/.config/ideaform/toolchain.json）
```

```bash
CONTRACT="${VW_CONTRACT:-$HOME/.config/ideaform/toolchain.json}"
source "$(dirname "$CONTRACT")/env.sh"     # 导出 VW_NODE / VW_VENV / VW_FFMPEG / …
```

**开工前必查三件事**：

1. 契约文件**存在吗**？不存在 → 让用户先跑 `ideaform-setup` 技能。
2. `schema_version` 是本技能认识的版本吗？不符 → 要求重跑环境配置技能。
3. `verified_at` 是 `null` 吗？是 → **警告用户"环境未通过冒烟校验"**，先修再干。
   另外 `tools.lmms.stkdir_ok` 必须是 `true`，否则 BGM 会**全程静音且不报错**。

关键字段速查：

| 用途 | 契约字段 |
|---|---|
| 跑 TTS 脚本（edge-tts 在 venv 里） | `tools.venv.python` |
| 合成音视频 | `tools.ffmpeg.path` / `tools.ffprobe.path` |
| 渲画面 | `tools.remotion.project` / `tools.remotion.browser.resolved` |
| 渲 BGM | `tools.lmms.apprun` |
| 落临时文件（**必须是大盘**） | `tmpdir` |

> ⚠️ **契约里的 `tmpdir` 不是可选项。** 本机 `/tmp` 只有 10MB，Remotion 打包 / pip 装包
> 都会写它 → `ENOSPC`。每条 Remotion 命令都要带 `TMPDIR`。

> ⚠️ **路径一律不做 `resolve`（软链解析）。** 托管工具链路径里含软链，
> 解析 venv 解释器会丢掉 venv 上下文，包全部 import 不到。见**仓库根** `docs/03-路径契约.md`。

---

## 1. 四阶段总览

| 阶段 | 干什么 | 入口 | 出口（都落到工作空间） | 参考 |
|---|---|---|---|---|
| ① 文稿 | 把用户的输入变成**分层**的解说稿 | 用户输入 | `script.md` + `台词.txt`（分层标好） | [`references/stage1-script.md`](references/stage1-script.md) |
| ② TTS 定轴 | 量自然语速 → 排时间轴 → 出配音音轨 | `台词.txt` | `plan.json` / `timeline.ts` / `voice.wav` | [`references/stage2-tts.md`](references/stage2-tts.md) |
| ③ BGM 变奏 | 层次边界 → 变奏计划 → LMMS 出音轨 | `plan.json` + 层次标注 | `bgm-plan.json` / `bgm.wav` | [`references/stage3-bgm.md`](references/stage3-bgm.md) |
| ④ 成片 | Remotion 排画面 + 集成音轨 + 渲染 + 封面 | `timeline.ts` + 音轨 + `bgm-plan.json` | `final.mp4` + `cover.png` | [`references/stage4-render.md`](references/stage4-render.md) · [`references/cover.md`](references/cover.md) |

**风格统一由 [`references/constructivist-style.md`](references/constructivist-style.md) 管**，
画面与封面共用同一套调色板 / 字体 / 栅格，所以天然一致。

---

## 2. 阶段一 · 文稿（分层是硬要求）

用户给的是**输入**（一个主题 / 一段材料 / 口头想法）。产出是：

- `script.md` —— 完整文稿，**显式标出论述层次**
- `台词.txt` —— 一行一句的口播台词，供 TTS 消费

**分层不是为了好看，是阶段三的输入。** 没有层次标注，BGM 变奏就没有着力点。

```
## 层次 1 · 引入
这是《文稿即时间轴》的第一层。
解说音轨才是整条流水线的时间主轴。
## 层次 2 · 展开
画面帧数由它决定，不是反过来。
...
```

- 一句 = 一个语义单元，**别把两件事塞进一句**（TTS 按句排轴，塞了会拖长槽位）
- 单句建议 **8–30 字**；过长拆句，过短合句
- 标点用句号/问号收尾，帮助 TTS 断句

细节见 [`references/stage1-script.md`](references/stage1-script.md)。

---

## 3. 阶段二 · TTS 定轴（**顺序铁律**）

```bash
"$VW_VENV/bin/python" skills/ideaform/scripts/make-tts-track.py \
    --lines 台词.txt --fps 30 --audio \
    --plan-out out/plan.json --ts-out out/timeline.ts
```

**先配音、后定轴。** 时间轴从 TTS 的真实语速里长出来：

```
① 写台词
② make-tts-track.py --lines 台词.txt --fps 30 --audio   ← 量自然语速，排出时间轴
③ 拿输出的 TOTAL_FRAMES 去写 Remotion composition       ← 帧数由此确定
④ 再渲染
```

**反例代价（实测）**：先按分镜写死 43 条时间码，TTS 自然语速合计 212.90s，
而视频只有 174.80s → **被迫压缩 1.218x**。这妥协本来完全可以避免。

同一个脚本也能做反过来的事（已有 SRT、时间码定死时用两段式调速适配），
但那是**补救**不是首选。详见 [`references/stage2-tts.md`](references/stage2-tts.md)。

> ⚠️ **禁止向用户索取"成片多少分钟"。** 时长 = 语速 × 台词量，是**输出**，不是**输入**；
> 开工时既不该问、也不该给"标准版 X 分钟"这类选项。只报「按这份文稿，实测 X 分 Y 秒」。
> 用户要更长/更短 → 改的是**文稿**，不是时间。（2026-10-15 桂花片踩过，记 E16）

**出口**：`plan.json` 里每条有 `start/end/dur/frameStart/frameEnd`；
`timeline.ts` 可直接 `cp` 进 Remotion 工程当 `src/timeline.ts`。

---

## 4. 阶段三 · BGM 变奏（本工作流的灵魂）

**要点：论述每进入一个新层次，音乐换一次形态 —— 但不换曲子。**

```bash
# ① 把文稿的层次落到 cue 号上，标出每层的叙事功能
"$VW_VENV/bin/python" skills/ideaform/scripts/bgm-plan.py \
    --plan out/plan.json \
    --layers "1:present,4:develop,6:resolve" \
    --key "A minor" --out out/bgm-plan.json

# ② 按 bgm-plan.json 生成 LMMS 工程并渲染（走 electronic-music-production 的 composer.py）
#    契约里的 tools.lmms.apprun 渲染；bpm 与 timeline lp1pos 必须按 mmp_hints 写
```

六个**叙事功能**（每层选一个）：

| 功能 | 意图 | 变了什么 |
|---|---|---|
| `present` | 呈现·引入 | 只露动机、单声部、留白 |
| `develop` | 展开·深入 | +bass +律动，动机模进 |
| `intensify` | 强调·冲突 | 全声部、升八度、借用和弦、力度抬档 |
| `contrast` | 对照·转折 | **换质地不加音量**：撤层、换音色、转调式 |
| `resolve` | 收束·回归 | 做减法、回主调、动机增值 |
| `sustain` | 持续·过渡 | **不动**（层次未变时别乱变奏，会稀释对比） |

**铁律**：

- **身份要素不许变** —— 动机细胞、调中心、基本速度。变了就是切歌，不是变奏。
- **每段至少变 1 项形态要素**；`bgm-plan.md` 里会列出每段的「变奏证据」，
  相邻两段若证据为空，说明层次标注漏了。
- **变奏点必须落在解说的层次边界上**（可用 `--lead-in` 让音乐略提前）。

完整方法与 LMMS 侧落地见 [`references/stage3-bgm.md`](references/stage3-bgm.md)。

---

## 5. 阶段四 · 成片

### 5.1 画面：以解说音轨为时间主轴

```bash
cp out/timeline.ts <remotion项目>/src/timeline.ts     # 帧数/幕边界都从 CUES 推导
cd <remotion项目>
export TMPDIR="$VW_TMPDIR"                             # ★ 必须
npx remotion studio                                    # 先给用户看预览
```

**画面侧的幕边界不要手写帧号**，从 `CUES` 推导：

```ts
export const SCENES = {
  s1: { from: 0,            dur: CUES[2].start },
  s2: { from: CUES[2].start, dur: CUES[4].start - CUES[2].start },
} as const;
```

**结构式 / 信号通路 / 机理图 → 一律确定性生成，绝不用 AI 出图。**
AI 画化学结构必然幻构键，而且**看不出错**——这类素材必须可复现、可校验。
用 [`scripts/gen-structures.py`](scripts/gen-structures.py)：SMILES → RDKit 确定性描绘
→ 帧驱动的 Remotion 组件。

```bash
python3 scripts/gen-structures.py --tsv structures.tsv --out structures
#   → svg/*.svg  +  components/*.tsx（自带动画）  +  manifest.json
#   → 分子式离线校验（RDKit CalcMolFormula），不符则非零退出，可直接串 `&&`
```

- 配色走 **RDKit 官方 options**（`useBWAtomPalette` / `singleColourBonds` / `setSymbolColour`），
  **不要正则后处理 SVG 的颜色**——那是重复造轮子且随 RDKit 改版就碎（见错题本 E20）。
- 生成的组件靠 CSS 变量 `--mol-dash` / `--mol-text` 驱动描线动画，**外层必须给 `color`**。
- 需要网格图 / 骨架高亮 / 3D 构象 / 蛋白-配体相互作用图等**更广**的分子可视化，
  先去找现成 skill（见 §7），别在视频流水线里硬塞。

### 5.2 音轨集成（两条路线，默认 A）

**A. Remotion 集成（推荐）** —— composition 里用 `<Audio>`，渲出的 mp4 自带音轨：

```tsx
<Audio src={staticFile("voice.wav")} />
<Audio src={staticFile("bgm.wav")} volume={0.1694} />
```

`volume` 那个数**不要拍脑袋**，用实测 RMS 反推：

```bash
bash scripts/mix-av.sh --plan-only --voice voice.wav --bgm bgm.wav --drop 9
# 解说 RMS = -23.46 dBFS   BGM RMS = -17.04 dBFS
# → BGM 需加 -15.42 dB  →  volume = 0.1694
```

**B. 后合成**（视频已渲好 / 要重配音）：

```bash
bash scripts/mix-av.sh --video silent.mp4 --voice voice.wav --bgm bgm.wav --out final.mp4
```

> ⚠️ **路线 B 必须显式 `-map 0:v:0 -map 1:a:0`。** Remotion 输出的 mp4 **自带一条静音 AAC 轨**，
> 不加 `-map` 时 ffmpeg 会自动选中它 → 成品**退出码 0、时长正确、能播放、就是没声音**。
> `mix-av.sh` 已内置这个 `-map`。

### 5.3 渲染与封面

```bash
export TMPDIR="$VW_TMPDIR"
npx remotion render <CompositionId> out/video.mp4 --concurrency=3
npx remotion still Cover out/cover.png --props='{...}'    # 封面：静态 composition，勿用动画
```

- **长片分段渲染**：7 分钟片单次渲染会因内存被打爆而超时。`--frames=A-B` 分段 → `concat -c copy` 无损拼。
- **封面用 `durationInFrames={1}` 的静态 composition**，组件内**不要用 `useCurrentFrame`**（still 时恒为 0，动画初值会让元素不可见）。
- 封面版式见 [`references/cover.md`](references/cover.md)，风格规范见 [`references/constructivist-style.md`](references/constructivist-style.md)。

---

## 6. 无目视交付：每个阶段都要过校验器

**模型看不到图像、听不到声音。** 所以「渲染成功」≠「画面对、声音对」。
每一步都用数值实测，不过关就**拒绝交付**：

```bash
# 音频自检（TTS 音轨、BGM）：峰值/RMS/削波/时长偏差
# 画面自检：像素对色 / 走廊纯净度 / 文字像素计数
#   --layout 必选对：cover=封面板式；scene=视频场景（默认）。
#   取样带按版式定，用错了正确封面也会被判失败（见 05-故障排查 D2）。
python3 scripts/verify-video.py cover out/cover.png --layout cover

# 成片自检：帧数 / 时长 / 音轨码率（防静音轨）
# ffprobe 定位顺序：VW_FFPROBE → 路径契约 toolchain.json → 系统
VW_FFPROBE="$VW_FFPROBE" python3 scripts/verify-video.py video out/final.mp4 --frames 732 --fps 30
```

脚本以**非零退出码**表示失败，可直接串进 `&&` 流水线。

常用判据速查：

| 对象 | 判据 | 阈值 |
|---|---|---|
| 音频 | 非静音 | 峰值 > 1000 且 RMS > 100 |
| 音频 | 无削波 | 满刻度样本 < 0.01% |
| 音频 | 时长对齐 | 与规划偏差 < 50 ms |
| 封面 | 尺寸 | 1920×1080 |
| 封面 | 文字渲染 | 文字区墨色像素 > 300 |
| 封面 | 轴线不穿字 | 标题区内红色像素 < 60 |
| 成片 | 帧数 | 严格等于规划值 |
| 成片 | 音轨非静音 | 码率 > 64000 bps |
| BGM | 衬底电平 | 比旁白低 8–12 dB |

---

## 7. 与本技能配合的其它能力

| 需要什么 | 用哪个 |
|---|---|
| 环境探测 / 补装 / 契约 | `ideaform-setup`（一次性） |
| **化学结构式 / 通路图的确定性图形** | 本技能的 `scripts/gen-structures.py`（RDKit → SVG → Remotion 组件） |
| 更广的分子可视化（网格图 / 骨架高亮 / 3D 构象 / 蛋白-配体） | 外部现成 skill：`synthetic-sciences/openscience` 的 `molecule-visualization`（Apache-2.0）、`ghutchis/chem-skill`（MIT） |
| LMMS 工程格式、插件参数、`eldata` 包络 | `electronic-music-production` + 其 `references/05` |
| 作曲法（和声、动机、无听觉作曲、涌现） | `electronic-music-production` 的 `references/06`–`10` |
| Remotion 语法与渲染细节 | `remotion-best-practices` |
| 像素级无目视校验的完整方法 | `headless-visual-verify` |
| WSL 环境坑（/mnt、gh 抓取、音频通路） | `wsl-pitfalls` |

---

## 8. 交付清单

一条视频做完，工作空间里应该有：

```
<工作空间>/
├── script.md            分层文稿
├── 台词.txt             口播台词
├── out/
│   ├── plan.json        时间主轴（每条 cue 的秒/帧）
│   ├── timeline.ts      可直接进 Remotion 的时间轴
│   ├── voice.wav        解说音轨母版
│   ├── bgm-plan.json    变奏计划 + bgm-plan.md（变奏证据）
│   ├── bgm.wav          BGM 音轨
│   ├── video.mp4        无声画面（或已集成音轨的成片）
│   ├── final.mp4        ★ 最终成片
│   └── cover.png        ★ 封面
└── .tts/                TTS 缓存（保留，重跑只花几秒）
```

交付前**必须**跑完第 6 节的全部校验，并如实报告哪几项通过、哪几项没测。

---

## 9. 自进化：踩坑就记账

本工作流是**可变的复合 skill**——用着用着，它应该越来越贴合你的生产节奏：

- 踩了坑、修完那一刻 → 记进**仓库根** `docs/06-错题本.md`（六栏格式，编号顺延）。
  ⚠️ **不要**在 `skills/ideaform/` 下另建 `docs/`——那是第二本账，会与正本编号撞车（2026-10-15 踩过，记 E19）。
- 某条坑被脚本/文档**永久修好**（不是绕开）→ 把该条状态改 `已根治` 并注明修法。
- 同一类坑踩到第二次 → 别记第三条，直接把防线写进脚本（校验器 / 默认值 / 契约）。
- 会话结束前扫一眼：有没有"修了但没记账"的。
