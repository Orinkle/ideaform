# Ideaform · 构想

> **Idea + Form** —— 把想法构造成看得见的形态。
> 「构」承构造主义（form / 构造）的血统，「想」就是 idea。中文名**构想**。

一套「**文稿 → TTS 解说 → LMMS BGM → Remotion 成片 + 封面**」的端到端工作流，
打包成两个互相衔接的 Agent Skill。下载后交给 Agent，自动配好环境即可生产视频；
成片风格为**构造主义、干净简约**。

**它解决的核心问题**：让一个想法被**形象、有效**地表达并分享出去 ——
不需要你会剪辑、会作曲、会排版，只需要把想法说清楚。

> 🧬 姊妹项目：[bio_ideaform](https://github.com/Orinkle/bio_ideaform) —— 本工作流的**生物特化版**：
> 画面层升级为三维分子动画（Blender + PyMOL），适合把论文 / 分子机制做成科普视频。

| Skill | 角色 | 生命周期 |
|---|---|---|
| `ideaform-setup` | **环境配置**：探测工具链 → 补装缺失 → 写路径契约 → **收割社区成熟 skill** → 端到端冒烟校验 | **一次性**。配置完即禁用/归档/删除 |
| `ideaform` | **工作流**：读路径契约 → 跑四阶段流水线 | **长期**。每次都靠它生产视频 |

两个 Skill 之间靠一个**中立的路径契约文件**通信，而不是靠互相 import。
所以第一个 Skill 被删掉之后，第二个照常工作 —— 这是本项目的核心设计。

---

## 自证：这条介绍片就是它自己做出来的

`examples/demo-episode/` 里的成片**由本工作流端到端生产**，不是手工剪的。
它同时是**回归样本** —— 换机器重跑一遍，就知道工具链有没有真通。

| 实测项 | 数值 |
|---|---|
| 文稿 → 解说音轨 | 27 句（`台词.txt`），`zh-CN-YunxiNeural`，自然语速 **126.56 s / 3797 帧 @30fps**，零变速 |
| BGM | A minor · **94.8 BPM**（反推使小节数落整）· 50 小节 · 五段变奏 · **6 处重音**（留白 → 重击 → 力度 +14） |
| BGM 整轨（实测） | RMS **−22.50 dBFS**、峰值 **−1.02 dBFS**、**0 削顶** |
| 混音音量 | 由实测 RMS 反推：旁白 −24.36 dBFS、BGM −22.50 dBFS → `10^(−15.40/20)` = **0.2862**（BGM 低于旁白 9 dB） |
| 成片（2026-10-15 复测） | 3797 帧 / 126.567 s / H.264 1080p，AAC **317 kbps**（非静音轨） |
| 成片电平（实测） | 整轨 **−23.92 dBFS**，峰值 **−0.41 dBFS** |
| 封面（复测） | P1–P7 全过，**P5 标题区内红色像素 0**（轴线不穿字） |

> 复现步骤与完整证据链见 `examples/demo-episode/README.md`；成品被 `.gitignore` 排除，仓库只留可复现的源。

---

## 介绍视频

▶ **[观看 / 下载项目介绍片 final.mp4（126 s，8.3 MB）](https://github.com/Orinkle/ideaform/releases/download/v0.1.0/final.mp4)**
—— 这条片子本身就是用本工作流端到端生产的（见上节「自证」）。
封面 [cover.png](https://github.com/Orinkle/ideaform/releases/download/v0.1.0/cover.png) ·
全部附件见 [Releases](https://github.com/Orinkle/ideaform/releases)。

> **项目视频怎么放上 GitHub**（本仓库的做法）：
> 成品 mp4/png 被 `.gitignore` 排除（仓库只留可复现的源），成品作为 **Release 附件**分发。
> 若想让视频在 README 里**内嵌播放**：在 github.com 网页上编辑 README，把 mp4 直接拖进编辑框，
> GitHub 会生成 `user-attachments` 链接——该通道只支持网页拖拽，API / git 都传不了。

---

## 目录结构

```
ideaform/
├── README.md                       # 你在看的这份
├── LICENSE
├── .gitignore
├── docs/
│   ├── 01-快速开始.md               # 5 分钟跑通第一个视频
│   ├── 02-工作流总览.md             # 四阶段各干什么、产出什么
│   ├── 03-路径契约.md               # 工具链路径如何在两个 Skill 间传递
│   ├── 04-安全与回滚.md             # 禁用 / 归档 / 删除 三档，以及怎么撤销
│   └── 05-故障排查.md
├── skills/
│   ├── ideaform-setup/              # ★ Skill A —— 环境配置（用完即弃）
│   │   ├── SKILL.md
│   │   ├── references/
│   │   │   ├── toolchain-matrix.md  # 每种工具的探测法 / 下载法 / 校验法
│   │   │   └── skill-harvest.md     # 拿来主义协议：评分 / 安检 / 分叉保护
│   │   └── scripts/
│   │       ├── detect.py            # 只读探测，绝不改系统
│   │       ├── install.sh           # 补装缺失项，全程记录 manifest
│   │       ├── harvest-skills.py    # ★ 拿来主义：GitHub 收割成熟 skill → 安检 → 落盘
│   │       ├── verify.py            # 端到端冒烟测试
│   │       └── rollback.sh          # 按 manifest 逆序撤销
│   └── ideaform/                    # ★ Skill B —— 工作流（长期）
│       ├── SKILL.md
│       ├── references/
│       │   ├── stage1-script.md     # 文稿（构造主义文案 + 分层）
│       │   ├── stage2-tts.md        # TTS 定轴（时间主轴）
│       │   ├── stage3-bgm.md        # LMMS BGM + 变奏表层次 ★
│       │   ├── stage4-render.md     # Remotion 渲染 + BGM 混音
│       │   ├── cover.md             # 封面（构造主义）
│       │   └── constructivist-style.md  # 构造主义视觉规范
│       ├── assets/templates/        # Remotion composition 骨架 / 封面模板
│       └── scripts/
│           ├── make-tts-track.py    # SRT/台词 → 时间对齐配音音轨
│           ├── bgm-plan.py          # 解说时间轴 → BGM 变奏计划
│           ├── mix-av.sh            # 无声成片 + 解说 + BGM → 成片
│           └── verify-video.py      # 无目视校验
└── examples/
    └── demo-episode/                # 一条真实跑通的示例（含全部实测数据 + 证据链 README）
```

---

## 快速开始

把整个仓库交给 Agent，说：

> 用 `skills/ideaform-setup` 把环境配好，然后用 `skills/ideaform` 给我做一条视频。

Agent 会：

1. **读环境配置 Skill** → 只读探测本机工具链（绝不动系统）
2. 对缺失项**检索下载源** → 按 `references/toolchain-matrix.md` 补装
3. **写路径契约** → `~/.config/ideaform/toolchain.json` + `env.sh`
4. **收割社区成熟 skill** → `harvest-skills.py --from-contract` 给链上每个工具找现成 skill
   （评分 → 安检 → 落盘；找不到合格的才自己写）
5. **端到端冒烟校验** → 真的合成 1 秒语音、渲 1 帧画面、渲 1 秒音频
6. **询问是否禁用/归档/删除**环境配置 Skill（附回滚方案）
7. 切换到工作流 Skill，**读契约**，开始四阶段生产

细节见 [`docs/01-快速开始.md`](docs/01-快速开始.md)。

---

## 四阶段流水线

```
① 文稿          ② TTS 定轴              ③ BGM 变奏            ④ 成片
   文字   ─→   解说音轨（时间主轴）─→   LMMS 音乐（层次变化）─→  Remotion 画面 + 混音 + 封面
                       │                      ▲
                       └──── 层次边界时间点 ───┘
```

**时间主轴永远是解说音轨。** 三个下游全部从它派生：

- 画面帧数由 TTS 自然语速定（不反过来压语速）
- BGM 的**变奏点**卡在解说的**层次切换点**上
- 成片以解说音轨为基准对齐，BGM 只做衬底

### 阶段三的关键：用变奏表达层次

这是本工作流区别于「随便配个 BGM」的地方：

> **论述每进入一个新层次，音乐换一次形态。**

`bgm-plan.py` 从解说时间轴里抽出层次边界（由文稿的分层结构标定），
映射成一份**变奏计划**（调式 / 配器 / 密度 / 和声张力 / 速度的变与不变），
再喂给 LMMS 侧的 `composer.py` 出 `.mmp`，无头渲染成 BGM 音轨。
详见 [`skills/ideaform/references/stage3-bgm.md`](skills/ideaform/references/stage3-bgm.md)。

---

## 设计要点

### 1. 路径传递：靠契约文件，不靠互相依赖

环境配置 Skill 把解析出的**绝对路径**写进 `~/.config/ideaform/toolchain.json`；
工作流 Skill 的**第一步**就是读它。契约文件在两个 Skill 之外，所以：

- 删掉环境配置 Skill → 契约仍在 → 工作流照跑
- 换机器 → 重跑环境配置 Skill → 契约被覆盖 → 工作流自动跟上新路径

契约里带 `schema_version` 与 `verified_at`，工作流会校验版本、过期会提醒重跑。
详见 [`docs/03-路径契约.md`](docs/03-路径契约.md)。

### 2. 安全的收尾：三档 + 回滚

环境配置 Skill 完工后**不会自己消失**，而是让你选：

| 档位 | 做什么 | 可逆性 |
|---|---|---|
| **禁用**（推荐） | frontmatter 置 `disable: true` | 改回 `false` 即恢复 |
| **归档** | 移到 `~/.config/ideaform/archive/` | 移回来即恢复 |
| **删除** | 真删目录（先自动备份） | 用备份恢复 |

任何一档都**先备份再动手**，并写 `install-manifest.jsonl` 供 `rollback.sh` 逆序撤销。
详见 [`docs/04-安全与回滚.md`](docs/04-安全与回滚.md)。

### 3. 无目视交付：一切都用数值自检

模型看不到图像、听不到声音。所以每个阶段都有**客观校验器**：
音频查 RMS/削波/哑条，画面查像素/走廊纯净度，成片查帧数与音轨码率。
任何一项不过关就**拒绝交付**，不靠形容词。

### 4. 拿来主义：新工具先收割，找不到才自己写

配环境时 `harvest-skills.py` 会按契约给每个工具去 GitHub 找**社区成熟的 Agent Skill**
（`filename:SKILL.md` 搜索 → stars/许可证/新鲜度评分 → 危险模式安检 → 落盘
`~/.workbuddy/skills/` 并附 `_PROVENANCE.md` 来源凭证）。
以后生产中引入任何新开源工具（如化学结构式绘制 → RDKit），同样先收割再动手。

**落盘后的 skill 归你进化**：脚本用逐文件哈希做分叉检测，本地改过的绝不覆盖
（上游新版放 `_upstream/` 供人工合并）。找不到合格候选的工具，才轮到自己写 ——
本项目自身的两个 Skill 就是这么来的。
协议详见 [`skills/ideaform-setup/references/skill-harvest.md`](skills/ideaform-setup/references/skill-harvest.md)。

---

## 环境要求

- **Linux / WSL2**（本工作流在 WSL2 内实测；macOS 需自行替换下载源）
- 可联网（TTS 走微软 Edge 接口；LMMS 走代理下载）
- ~1 GB 空闲磁盘（LMMS 解包后约 356 MB + Remotion 依赖）
- Node.js ≥ 18、Python ≥ 3.10 —— 缺了环境配置 Skill 会装

> **不下载、不安装、不运行任何游戏；不碰联机与反作弊。** 本工作流只处理自产素材。

## 许可

MIT，见 [LICENSE](LICENSE)。
本仓库的资料性内容改写自作者本机的私有 Skill（`srt-tts-voiceover` / `electronic-music-production` /
`remotion-best-practices` / `headless-visual-verify`），所有实测数值与踩坑记录均来自真实复现。
Remotion 相关部分的上游是 [remotion-dev/skills](https://github.com/remotion-dev/skills)。
