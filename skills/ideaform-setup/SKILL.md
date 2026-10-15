---
name: ideaform-setup
description: 构造主义解说视频工作流的**一次性环境配置**技能。下载项目后首次使用：只读探测本机工具链（Node/Python/ffmpeg/Remotion/LMMS/中文字体），对缺失项检索下载源并补装，把解析出的绝对路径写成「路径契约」toolchain.json，再按契约去开源社区收割各工具的成熟 Agent Skill（拿来主义，harvest-skills.py），做端到端冒烟校验，最后询问是否禁用/归档/删除本技能。当用户刚下载本项目、说"配环境""装工具链""跑不起来/命令找不到"，或生产中引入新开源工具要找现成 skill 时使用。
description_en: One-time environment setup for the constructivist video workflow. Probes the local toolchain read-only, installs what is missing, runs an end-to-end smoke test, then writes a resolved-path contract (toolchain.json) for the workflow skill and offers to disable/archive/delete itself.
license: MIT
agent_created: true
disable: false
---

# 环境配置 Skill（一次性）

**目标**：把"这台机器上这些工具到底在哪"这件事问清楚，写成一份**路径契约**，
然后功成身退。

> **本技能的生命周期是"用完即弃"。** 不要让它常驻 —— 收尾时必须走 §7 的确认流程。

---

## 0. 三条硬规矩（先读）

1. **探测阶段只读。** `scripts/detect.py` **绝不**创建/修改/删除任何系统文件。
   它只 `which` / `stat` / 版本查询 / 列目录。任何写入都必须发生在 §4 的 `install.sh` 里，
   且**逐条记录进 manifest**。
2. **绝不写用户盘。** 不碰 `/mnt/c`、`/mnt/d`、Windows 盘。
   一切产出与临时文件落**当前工作空间**或 `~/.config/ideaform/`。
3. **不要试 sudo。** 沙箱内进程永远拿不到 root（内核 `NoNewPrivs=1`），
   试了纯浪费时间。需要 root 的活**交给用户在自己终端跑**，并给出确切命令。
   本项目所有工具都设计了**用户级安装**（解包 AppImage、venv 装包、本地字体），无需 root。

---

## 1. 契约文件（本技能唯一的对外产出）

**位置**（固定，两个 Skill 之外的第三方位置）：

```
$VW_CONFIG_ROOT/toolchain.json          # 默认 ~/.config/ideaform/
$VW_CONFIG_ROOT/env.sh                  # shell 可直接 source 的导出脚本
$VW_CONFIG_ROOT/install-manifest.jsonl   # 装了什么，供回滚
$VW_CONFIG_ROOT/logs/
$VW_CONFIG_ROOT/backup/                 # 任何覆盖前的原文件备份
```

`$VW_CONFIG_ROOT` 默认 `~/.config/ideaform`，可用环境变量覆盖。
**契约文件放在 Skill 目录之外，是刻意设计** —— 这样删掉本技能后，工作流技能照样能读到。

**schema_version 1** 的字段（工作流技能按这些键取值）：

```jsonc
{
  "schema_version": 1,
  "generated_at": "ISO8601",
  "generated_by": "ideaform-setup@1.0.0",
  "verified_at": "ISO8601 | null",       // 冒烟测试通过后才盖章
  "host": { "os": "linux", "distro": "...", "arch": "x86_64", "in_wsl": true },
  "config_root": "/abs/path",
  "tmpdir": "/abs/path/to/big/disk/tmp", // ★ 必须指向大盘，不能是 10MB 的 /tmp
  "tools": {
    "node":     { "path": "/abs", "version": "22.x", "status": "ok|missing|degraded" },
    "python":   { "path": "/abs", "version": "3.13.x", "status": "..." },
    "venv":     { "path": "/abs", "python": "/abs/bin/python", "pip": "/abs/bin/pip" },
    "ffmpeg":   { "path": "/abs", "version": "...", "flavor": "full|remotion-minimal", "status": "..." },
    "ffprobe":  { "path": "/abs", "status": "..." },
    "remotion": { "project": "/abs", "version": "4.x", "status": "..." },
    "lmms":     { "apprun": "/abs", "root": "/abs", "version": "1.2.2",
                  "stkdir": "/abs", "status": "..." },
    "fonts":    { "cjk_families": ["Noto Sans CJK SC"], "status": "..." }
  },
  "env_file": "/abs/env.sh",
  "manifest": "/abs/install-manifest.jsonl"
}
```

工作流技能启动时会检查 `schema_version` 与 `verified_at`：
版本不符 → 要求重跑本技能；`verified_at` 为 null → 警告"未通过冒烟测试"。

---

## 2. 执行顺序（照做，别跳）

### 第 1 步 · 只读探测

```bash
python3 skills/ideaform-setup/scripts/detect.py            # 人类可读报告
python3 skills/ideaform-setup/scripts/detect.py --json     # 机器可读
```

对照 [`references/toolchain-matrix.md`](references/toolchain-matrix.md) 逐项核对。
每一项的状态是 `ok` / `missing` / `degraded`（在但能力不全，例如 ffmpeg 是 Remotion 精简版）。

### 第 2 步 · 出计划，问用户

把探测结果整理成一张表**给用户看**：哪些 ok、哪些 missing、哪些 degraded，
以及**每个 missing 项打算怎么装、装到哪、需要多少磁盘**。
**等用户确认再动手。** 别自作主张装东西。

### 第 3 步 · 补装（只在用户确认后）

```bash
bash skills/ideaform-setup/scripts/install.sh --only <tool1,tool2>
```

不传 `--only` 则装所有 missing 项。脚本：
- 装之前把将被覆盖的已有文件备份到 `$VW_CONFIG_ROOT/backup/<时间戳>/`
- 每完成一步就向 `install-manifest.jsonl` 追加一条记录
- 全部落用户级路径，**不需要 root**

若某项必须用 root（极少见），脚本会**停下来打印命令**，让你转交用户在自己终端执行。

### 第 4 步 · 写契约

```bash
python3 skills/ideaform-setup/scripts/detect.py --write
```

把解析结果落到 `toolchain.json` + `env.sh`。此时 `verified_at` 仍为 `null`。

### 第 5 步 · 收割社区 Skill（拿来主义）

契约写完，链上有哪些工具就确定了。**别急着靠自己那点存量知识上手，**
**先把社区踩过坑的成熟 skill 拿过来：**

```bash
python3 skills/ideaform-setup/scripts/harvest-skills.py --from-contract            # 为链上工具逐个收割
python3 skills/ideaform-setup/scripts/harvest-skills.py --from-contract --dry-run  # 先看候选名单再决定
```

脚本对每个工具：GitHub 搜 `filename:SKILL.md` → 按 stars/许可证/新鲜度评分 →
安全扫描（命中危险模式的进 `_quarantine/` 隔离区，换下一个候选）→
落盘 `~/.workbuddy/skills/<name>/`（附 `_PROVENANCE.md` 来源凭证）→ 记进 manifest。

- **找不到合格候选 = 这个工具真得自己写 skill** —— 这正是本仓库 `skills/ideaform*` 存在的理由。
- **落盘后的 skill 归你进化。** 脚本有分叉保护（`_harvest.json` 逐文件哈希）：
  本地改过的默认不覆盖，`--force` 只升级没动过的，分叉的上游新版进 `_upstream/` 供人工合并。
  见 [`references/skill-harvest.md`](references/skill-harvest.md) §4.1。
- 完整协议（评分细则 / 安检模式 / 限额）见 [`references/skill-harvest.md`](references/skill-harvest.md)。

> 这一步不只属于首次配置。**以后生产中引入任何新开源工具**（比如要做化学结构式
> 绘制，想到 RDKit），第一件事都是 `harvest-skills.py rdkit` —— **先收割，再动手**。

### 第 6 步 · 端到端冒烟校验（**必做，不许跳**）

```bash
python3 skills/ideaform-setup/scripts/verify.py
```

真的跑一遍最小闭环，四项全过才盖章：

> **★ 验收标准**：跑完这一步，再在**零环境变量**下重跑一次 ——
> `env -u TMPDIR -u VW_TMPDIR -u VW_CHROME python3 scripts/verify.py`
> 仍然全过，才说明**契约真的自洽**（工具链、TMPDIR、chrome 路径全都从契约里读到了）。
> 靠手动 `export` 才过 = 契约有漏，工作流技能换台机器就会挂。

| 校验 | 做什么 | 通过判据 |
|---|---|---|
| ① TTS | 合成一句中文 | 产出音频 > 2 KB 且 RMS > 阈值 |
| ② 画面 | Remotion 渲 1 帧 still | PNG 尺寸正确、文件 > 20 KB |
| ③ 音频渲染 | LMMS 渲一个 1 秒工程 | WAV 峰值 > 1000 且非静音 |
| ④ 音视频合流 | ffmpeg 把静音视频 + 音轨合起来 | 输出音轨码率 > 64000 bps |

全过 → 把 `verified_at` 盖进 `toolchain.json`。
有不过 → **停下来报告哪一项、为什么**，修好再重跑。**不要盖章。**

### 第 7 步 · 交接确认 + 收尾

见 §7。

---

## 3. 各项工具怎么找（摘要）

完整表格在 [`references/toolchain-matrix.md`](references/toolchain-matrix.md)。要点：

- **Node / Python**：优先本机托管版本路径（`~/.workbuddy/binaries/...`），再退 `PATH`。
- **ffmpeg / ffprobe**：系统通常**没有**。Remotion 包内自带一份**精简版**
  （`node_modules/@remotion/compositor-linux-x64-gnu/ffmpeg`）—— 够用，但滤镜少
  （没有 `volumedetect` / `acompressor`，`loudnorm` 有延迟）。找到就标 `degraded` 而不是 `missing`，
  并在契约里注明 `flavor`。
- **Remotion 工程**：优先 `$VW_REMOTION_PROJECT`，再找 `~/tools/remotion-app`，
  再扫工作空间里的 `remotion.config.ts`，都没有就用本技能自带的
  `assets/templates/remotion-starter/` 起一个。
- **LMMS**：找 `squashfs-root/AppRun`（AppImage 解包后的运行入口）。
  注意 `~/.lmmsrc.xml` 里的 `stkdir` **必须**指向该解包目录下的 `rawwaves/`，
  否则**全程静音且不报错** —— 这是本工作流最贵的坑，`verify.py` ③ 就是为它设的。
- **中文字体**：`fc-list` 查 `Noto Sans CJK SC` 之类。缺了就装用户级字体到 `~/.local/share/fonts/`。

---

## 4. 安装阶段的落点

| 工具 | 装到哪 | 手段 |
|---|---|---|
| Node / Python | 缺才装 | 优先用机器已有的托管版本；否则提示用户 |
| `edge-tts` / `soundfile` / `numpy` | venv | `<venv>/bin/pip install`，必须 `export TMPDIR=<大盘>` |
| ffmpeg 完整版 | `~/.local/bin/` | 从镜像下静态包解出，无需 root（可选，精简版够用就别装） |
| LMMS | `$VW_CONFIG_ROOT/lmms/` | AppImage 走代理下载 → `--appimage-extract` 解包 |
| Remotion 依赖 | 工程目录 | `npm install`，`TMPDIR` 指大盘 |
| 中文字体 | `~/.local/share/fonts/` | 解包 `.ttc` → `fc-cache -f` |

⚠️ **每个下载都要校验**：字节数 / SHA256 / 解包后能否运行。下载失败宁可重试也不要留半个文件。

---

## 5. 回滚

`install-manifest.jsonl` 是唯一事实来源，形如：

```json
{ "entries": [
  { "ts": "...", "kind": "pip-install", "target": "<venv>", "detail": "edge-tts==7.3.1",
    "undo": "<venv>/bin/pip uninstall -y edge-tts" },
  { "ts": "...", "kind": "mkdir", "target": "$VW_CONFIG_ROOT/lmms", "undo": "rm -rf ..." },
  { "ts": "...", "kind": "backup-file", "target": "~/.lmmsrc.xml",
    "backup": "$VW_CONFIG_ROOT/backup/<ts>/lmmsrc.xml", "undo": "cp 备份回原位" }
] }
```

```bash
bash skills/ideaform-setup/scripts/rollback.sh --list      # 看会撤销什么
bash skills/ideaform-setup/scripts/rollback.sh --dry-run   # 演习，不动手
bash skills/ideaform-setup/scripts/rollback.sh --yes       # 真回滚（逆序）
```

**覆盖用户已有文件之前必须先备份** —— 尤其是 `~/.lmmsrc.xml`。
回滚默认**不删**契约文件（那是工作流技能要用的），除非用户明确要求 `--purge-contract`。

---

## 7. ★ 收尾：禁用 / 归档 / 删除（必须让用户选）

冒烟测试通过后，**不要自动删自己**。按下面流程走：

### ① 先汇报

对用户说明：

- 环境已配置完成，`toolchain.json` 已就位（给出路径）
- 冒烟测试四项结果
- 工作流技能**不需要**本技能在场也能工作（因为契约文件在 Skill 之外）

### ② 给出三档，让用户选

| 档 | 做什么 | 可逆性 | 适用 |
|---|---|---|---|
| **A. 禁用**（推荐） | 把本 SKILL.md frontmatter 的 `disable: false` 改成 `true` | 改回 `false` 即恢复 | 想留着以后换机器/换环境重跑 |
| **B. 归档** | 整个 skill 目录移到 `$VW_CONFIG_ROOT/archive/ideaform-setup-<ts>/` | 移回来即恢复 | 不想让它出现在技能列表，但留着备用 |
| **C. 删除** | 真删目录 | 靠自动备份恢复 | 确定不再需要 |

**推荐 A**：禁用最安全，成本最低，且保留了"环境变了再跑一次"的能力。

### ③ 动手前的铁律

无论哪一档，**先备份、后动手、再确认**：

1. **备份**：`cp -r <skill 目录> $VW_CONFIG_ROOT/backup/skill-ideaform-setup-<ts>/`
2. **列清单**：把**将被删/改的每一个路径**列出来给用户看
3. **二次确认**：等用户明确说"删吧"之类，**不要**用默认值或推断代替确认
4. **执行**：删用 `mv` 到备份再删，**不要**直接 `rm -rf`
5. **验证**：确认工作流技能仍能读到 `toolchain.json` 并正常启动

### ④ 删除后自检

```bash
test -f "$VW_CONFIG_ROOT/toolchain.json" && echo "契约仍在 ✓"
```

契约在 → 工作流不受影响。契约没了 → 说明误删，用备份恢复。

> 用户问"能不能直接删"时，**回答三档并解释取舍**，别只答"能"。

---

## 8. 常见错误

| 现象 | 真因 | 处理 |
|---|---|---|
| LMMS 渲染出来全程静音、日志无报错 | `~/.lmmsrc.xml` 的 `stkdir` 没指向解包目录的 `rawwaves/` | 改 `stkdir`，并跑 `verify.py` ③ 复验 |
| `npm install` / `pip install` 报 `ENOSPC` | `TMPDIR` 落在 10MB 的 `/tmp` tmpfs | `export TMPDIR=<大盘>`，契约里的 `tmpdir` 就是这个用途 |
| Remotion 渲染中途超时 / 页面卡死 | 并发太高把内存顶爆（4×1080p 页面） | 降 `--concurrency`，长片分段渲染 |
| AppImage 跑不起来 | 沙箱无 `/dev/fuse` | `--appimage-extract` 解包后用 `AppRun` |
| LMMS 拒绝启动 | 沙箱内 `id` 显示 root | 加 `--allowroot` |
| edge-tts 报 `WSServerHandshakeError 403` | 版本太老（非网络问题） | `pip install --upgrade edge-tts`，再校准系统时钟 |

更多见 [`docs/05-故障排查.md`](../../docs/05-故障排查.md)。

---

## 9. 交接给谁

配置完成后，**下一步是工作流技能**：

```
skills/ideaform/SKILL.md
```

它第一步会读本技能写下的 `toolchain.json`。交接话术：

> 环境已配好并校验通过，契约在 `<路径>`。接下来切到工作流技能开始生产。
