# 工具链矩阵 —— 探测法 / 下载法 / 校验法

> 本表是本技能的事实来源。**所有路径与数值均为实测**（WSL2 / Ubuntu 26.04 / x86_64）。
> 换平台时按同结构替换来源，但**校验方法必须保留**。

---

## 0. 总表

| 工具 | 必需? | 探测判据 | 缺失时从哪来 | 校验判据 |
|---|---|---|---|---|
| Node.js | ✅ | `node -v` ≥ 18 | 机器托管版本优先 | `node -v` 能打印 |
| npm/npx | ✅ | `npm -v` | 随 Node | `npm -v` 能打印 |
| Python | ✅ | `python3 -V` ≥ 3.10 | 机器托管版本优先 | `python3 -V` 能打印 |
| venv 包：`edge-tts` | ✅ | `<venv>/bin/edge-tts --version` | PyPI | **≥ 7.3.1**（见 §2） |
| venv 包：`soundfile` | ✅ | `python -c "import soundfile"` | PyPI | import 不报错（MP3 转码用） |
| venv 包：`numpy` | ○ | 同上 | PyPI | import 不报错（电平量测用） |
| ffmpeg | ✅ | 契约可不来自 PATH | ① Remotion 自带精简版 ② 静态包 | `-filters` 能列出 ≥ 30 项 |
| ffprobe | ✅ | 同 ffmpeg | 同上 | 能读出一个 mp4 的 `nb_frames` |
| Remotion 工程 | ✅ | 有 `remotion.config.ts` 且 `npx remotion --version` 可跑 | ① 已有工程 ② 本项目模板 | 能 `still` 出一张 PNG |
| LMMS | ✅ | 有 `squashfs-root/AppRun` | GitHub Release（走代理） | ① 能渲非静音 WAV ② `stkdir` 正确 |
| 中文字体 | ✅ | `fc-list` 含 `Noto Sans CJK SC` | 系统包 / 用户级 ttf | `fc-match "Noto Sans CJK SC"` 命中 |
| git / gh | ○ | `git --version` | 系统包 | 打印版本（仅发布时需要） |

图例：✅ 必需 · ○ 可选

---

## 1. Node / Python：先找托管版本，再退 PATH

探测顺序（`detect.py` 已实现）：

```
Node:   $VW_NODE → ~/.workbuddy/binaries/node/versions/*/bin/node → which node
Python: $VW_PYTHON → ~/.workbuddy/binaries/python/versions/*/bin/python3 → which python3
venv:   $VW_VENV → ~/.workbuddy/binaries/python/envs/default → 自建
```

**用托管版本的理由**：路径稳定、不与系统包冲突、可写（自建 venv 需要写权限）。

自建 venv：

```bash
<python3> -m venv "$VW_CONFIG_ROOT/venv"
export TMPDIR=<大盘>/tmp            # ★ 装包也吃 TMPDIR，见 §7
"$VW_CONFIG_ROOT/venv/bin/pip" install -U pip
```

---

## 2. edge-tts：**先升级版本，再排网络**（实测踩过）

`WSServerHandshakeError: 403, message='Invalid response status'` 出现在 WebSocket
**握手**阶段 —— 此时 `curl https://speech.platform.bing.com/` 返回 **400**（即网络是通的），
`http_proxy` 摘掉也一样 403。**根因是客户端版本太老，微软拒绝了身份令牌。**

```bash
"$VENV/bin/pip" install --upgrade "edge-tts>=7.3.1"
```

- 实测 `7.2.8` 全量 403 → 升到 **`7.3.1` 立刻恢复**。
- 排查顺序固定：**① 升级 edge-tts → ② 校准系统时钟**（令牌按 5 分钟窗口算，偏差 > 1 分钟必挂）
  **→ ③ 才考虑代理**。别一上来就怀疑 IP 被封。

连通性自检（400 = 通，不是错）：

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://speech.platform.bing.com/
```

---

## 3. ffmpeg / ffprobe：系统通常没有，用 Remotion 自带的

本机实测：`which ffmpeg` → **空**。但 Remotion 包里有一份：

```bash
find <remotion_project>/node_modules/@remotion -maxdepth 2 -type f -name ffmpeg
# 实测: <remotion工程>/node_modules/@remotion/compositor-linux-x64-gnu/ffmpeg
#       .../compositor-linux-x64-gnu/ffprobe
```

**它是精简版**，`-filters` 只有约 35 项：

- **可用**：`volume` `atempo` `apad` `atrim` `aresample` `concat` `amix` `adelay`
  `silencedetect` `loudnorm` `scale` `crop` `format` `trim` …
- **没有**：`volumedetect` `acompressor` `dynaudnorm` `alimiter` `speechnorm`
  → **音频电平检测自己算**（Python `wave` + `array`），别指望它。
- **`loudnorm` 有前瞻延迟**，会平移整条音轨、破坏字幕对齐 → 对时间敏感的音轨**只用 `volume`**。

→ 因此探测到它时标 **`degraded`**，契约里写 `"flavor": "remotion-minimal"`。
`verify.py` 会据此决定用哪种方法量电平。

**可选：装完整版**（无需 root）：

```bash
# 静态构建，解到用户级目录
mkdir -p ~/.local/bin && cd "$VW_CONFIG_ROOT"
# 来源示例（按平台选；本机未实测完整版下载，标注为"未验证"）
# curl -L -o ffmpeg.tar.xz https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
```

> ⚠️ 上游静态包地址**未在本机实测**，标注为未验证。若精简版够用就别装 —— 少一个变量。

### ffprobe 取值：`-of csv=p=0` 会带尾逗号（实测）

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=nb_frames -of csv=p=0 f.mp4
# 实测输出: 2592,      ← 尾逗号！字符串比较 "2592," != "2592" 恒真
```

**正解**：用 `-of default=nw=1:nk=1`，并清一遍：

```bash
nbframes() { ffprobe -v error -select_streams v:0 -show_entries stream=nb_frames \
             -of default=nw=1:nk=1 "$1" 2>/dev/null | tr -d ' ,\r\n'; }
```

---

## 4. Remotion 工程

```bash
node <project>/node_modules/.bin/remotion --version   # 或 npx --no-install remotion --version
```

实测本机版本 **4.0.515**，`package.json` 关键依赖：

```json
{ "@remotion/cli": "4.0.515", "@remotion/transitions": "^4.0.515",
  "react": "19.2.3", "react-dom": "19.2.3", "remotion": "4.0.515",
  "tailwindcss": "4.0.0", "@remotion/tailwind-v4": "4.0.515" }
```

**没有现成工程** → 用本技能自带的 `assets/templates/remotion-starter/` 复制一份，然后：

```bash
cd <新工程>
export TMPDIR=<大盘>/tmp && mkdir -p "$TMPDIR"    # ★ 必须
npm install
```

⚠️ **每一条 `npx remotion *` 都要带 `TMPDIR`**。没设时打包写 `/tmp`（本机 10MB tmpfs）
→ `ENOSPC: no space left on device`。另外 `npx remotion render --help` 也会**先打包整个工程**
再输出帮助 —— 查参数优先读 `node_modules/@remotion/cli/dist/` 源码。

---

## 5. LMMS

**目标产物**：一个能跑的 `AppRun`。

```bash
LMMS_ROOT="$VW_CONFIG_ROOT/lmms"
mkdir -p "$LMMS_ROOT" && cd "$LMMS_ROOT"

# ① 下载（走代理！直连 GitHub 只有 ~10 KB/s，92MB 要 152 分钟）
curl -L --retry 3 -o lmms.AppImage \
  "https://gh-proxy.com/https://github.com/LMMS/lmms/releases/download/v1.2.2/lmms-1.2.2-linux-x86_64.AppImage"
# 实测：19.85 MB/s，4.6 秒；正确字节数 96,362,536

# ② 校验字节数
[ "$(stat -c %s lmms.AppImage)" = "96362536" ] || echo "字节数不符，重下"

# ③ 解包（沙箱无 /dev/fuse，AppImage 不能直接跑）
chmod +x lmms.AppImage && ./lmms.AppImage --appimage-extract    # → squashfs-root/

# ④ 运行入口
./squashfs-root/AppRun --allowroot render x.mmp -f wav -o x.wav
```

**两个必需参数**：`--allowroot`（沙箱内 `id` 显示 root，LMMS 默认拒绝以 root 启动）；
日志里 `Carla` / `JACK` / `VST` 类警告**无害**。

### ⚠️ 最贵的坑：`stkdir`

`~/.lmmsrc.xml` 的 `<paths stkdir="..."/>` **必须**指向解包目录下的实际波表位置：

```xml
<paths stkdir="$LMMS_ROOT/squashfs-root/usr/share/stk/rawwaves/"
       workingdir="$LMMS_ROOT/"/>
```

指向不存在的目录 → **全程静音且不报错**。`verify.py` ③ 就是为它设的守门人。
若 `~/.lmmsrc.xml` 已存在，**先备份再改**（记进 manifest）。

---

## 6. 中文字体

```bash
fc-list : family | grep -i "noto sans cjk"        # 探测
fc-match "Noto Sans CJK SC"                        # 确认命中（不是 fallback）
```

本机实测已装 `Noto Sans CJK SC / TC / HK / JP / KR`（Serif 亦全），共 278 个字族。
缺失时**用户级安装**（无需 root）：

```bash
mkdir -p ~/.local/share/fonts && cp *.ttc ~/.local/share/fonts/ && fc-cache -f
```

**中文一定要在样式里写完整族名**（例如 `"Noto Sans CJK SC Black"`），
只写 `"Noto Sans"` 会掉进 tofu（豆腐块）。

---

## 7. 磁盘与 TMPDIR（贯穿全局）

本机 `/tmp` 是 **10MB tmpfs**。凡是解包、装包、打包都会写它 → `ENOSPC`。

**契约里的 `tmpdir` 字段就是解决这个的**。所有脚本读 `$VW_TMPDIR`，
工作流技能也靠它。默认指到当前工作空间下的 `.tmp/`（大盘）。

```bash
export TMPDIR="$VW_TMPDIR"; mkdir -p "$TMPDIR"
```

`pip install` **也吃 TMPDIR** —— "No space left on device" 不一定是磁盘满。

### ⚠️ `tmpdir` 必须**传给子进程**，不能只当"报告目录"

实测踩坑：`verify.py` 曾把 `TMPDIR` 写死成 `/tmp`，只用契约的 `tmpdir` 决定
"报告放哪"。结果在 10MB tmpfs 上，② 画面 still 直接 ENOSPC 失败，
提示语还反过来怪契约 —— 而其它脚本（`make-tts-track.py` / `mix-av.sh`）明明都读了契约。

**规矩**：凡是要 spawn 子进程（`npm` / `npx remotion` / `pip` / `edge-tts` / `lmms`）的地方，
一律 `env = dict(os.environ, TMPDIR=str(resolve_tmpdir(ct)))` 显式继承。
**每一个** 会打包的 remotion 子命令都要带（`compositions` 也会打包，别漏）。

定位顺序统一为：`VW_TMPDIR` 环境变量 → 契约 `tmpdir` → `/tmp` 兜底。
自检：`env -u TMPDIR -u VW_TMPDIR python3 scripts/verify.py`
—— **能在零环境变量下全过，才说明契约真的自洽**。

---

## 8. 下载校验的通用规矩

1. **字节数**先于内容校验（快、便宜）：`stat -c %s`。
2. **SHA256**（若上游提供）：`sha256sum -c`。
3. **可运行性**是最终判据：解包后真的跑一次 `--version` / 渲一个最小产物。
4. **失败不留残骸**：半个文件比没文件更危险（会被后续误判为"已装"）。
   下载失败先删残骸再重试。
5. **大文件走代理**，并**分段并行**校验长度（单连接长下载易被超时杀）。
