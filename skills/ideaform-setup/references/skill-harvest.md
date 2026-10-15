# Skill 收割协议（拿来主义）

> **新工具入场，先找社区成熟 skill；找不到合格的，才自己写。**
> 你写的是胶水，不是轮子。

入口脚本：[`../scripts/harvest-skills.py`](../scripts/harvest-skills.py)。

---

## 1. 什么时候收割

| 时机 | 命令 |
|---|---|
| **首次配环境**（契约写完，链上工具已确定） | `harvest-skills.py --from-contract` |
| **生产中引入新开源工具**（例：要做化学结构式绘制 → RDKit；要画电路 → KiCad） | `harvest-skills.py rdkit` |
| 想看候选名单再决定 | 加 `--dry-run` |
| 已收割过、想升级 | 加 `--force` |

契约工具名 → 搜索词的映射写在脚本里（`CONTRACT_SEARCH_TERMS`）。
**太泛的词（python、node）不映射、不搜索** —— 捞回来的只会是噪音。

## 2. 流水线（每个工具跑一遍）

```
GitHub code search: filename:SKILL.md <tool>
  → 去重（repo + skill 目录）
  → 拉仓库元数据（stars / license / 是否归档 / 最近推送）
  → 拉 SKILL.md 解析 frontmatter（name / description）
  → 评分排序
  → 逐候选：下载整个 skill 目录 → 安全扫描
      通过 → 落盘 ~/.workbuddy/skills/<name>/
      命中 → 落盘 ~/.workbuddy/skills/_quarantine/<name>-<repo>/，换下一候选
  → 写 _PROVENANCE.md（来源凭证）→ 记 install-manifest.jsonl
```

**评分**（越大越好）：

| 项 | 分值 |
|---|---|
| stars | `log10(stars+1) × 10` |
| 有明确许可证（SPDX 非 NOASSERTION） | +15 |
| name/description 命中工具名 | +10 |
| 18 个月内有提交 | +5 |
| 仓库已归档（archived） | **直接淘汰** |

## 3. 安全扫描（不过就隔离）

只列**明确危险**的模式：管道进 shell（`curl|sh`）、`base64 -d|sh`、`rm -rf /`或家目录、
`dd of=/dev/`、碰 `~/.ssh`/`~/.aws`/凭据目录、环境变量/token 外发嫌疑。

**原则：宁可漏报，不可误报。** 误报把好 skill 扔进隔离区，破坏信任；
漏报的由 `_PROVENANCE.md` 里的来源信息支撑用户人工复查。
隔离区里的东西**不会被任何 skill 加载**，用户看完决定删还是手动转正。

## 4. 落盘规约

```
~/.workbuddy/skills/<name>/
├── SKILL.md            # 第三方原文（落盘后就归你改，见 §4.1）
├── …（原仓库 skill 目录的全部文件）
├── _PROVENANCE.md      # 收割凭证：来源 URL / commit / stars / 许可证 / SHA256 / 安检结论
└── _harvest.json       # 机器锚点：逐文件 SHA256，分叉检测用
```

- 每个 skill 带 `_PROVENANCE.md` —— **从哪来的、什么时候拿的、安不安全，一眼可查**。
- 每次收割/隔离都追加一条 manifest 记录（`kind: skill-harvest` / `skill-harvest-quarantine`），
  卸载 = 删目录，`rollback.sh --list` 也能看到。
- 收割回来的 skill 是**第三方资产**，许可证以其仓库内 LICENSE 为准。

### 4.1 分叉保护：本地进化 > 上游更新

**落盘之后的 skill 就归你了** —— 随使用改、随生产节奏进化，和上游仓库从此是两条线。
脚本用 `_harvest.json` 的逐文件 SHA256 识别"本地动没动过"，行为矩阵：

| 目标目录状态 | 默认 | `--force` | `--clobber` |
|---|---|---|---|
| 不存在 | 安装 | 安装 | 安装 |
| 收割落的、**没动过**（clean） | 跳过 | **覆盖升级** | 备份后覆盖 |
| 收割落的、**本地已进化**（evolved） | 跳过 | **不覆盖**：上游新版落 `_upstream/<name>-<ts>/`，自行 diff 合并 | 本地版备份到 `_upstream/`后覆盖 |
| 非本脚本落的（无 `_harvest.json`，**你的私产**） | 跳过 | **不碰** | 备份后覆盖 |

> 没有 `_harvest.json` 的目录一律视为私产，`--force` 也碰不了它 ——
> 防的就是把你自己写/改的东西当上游垃圾刷掉。

## 5. 限额与网络事实（本机实测）

- 未认证 GitHub API：**60 次/小时**；有 `gh auth token` 或 `GITHUB_TOKEN` 走认证通道
  （且 code search API **必须认证**，未认证时脚本退化到仓库搜索，候选质量差一档）。
- `raw.githubusercontent.com` 被拦 → 一律走 contents API + `Accept: …raw`。
- 不打 tarball（codeload 大包会被杀）；逐文件拉，单文件 >512KB 或总量 >5MB 直接放弃
  （skill 是文本资产，超了基本不是 skill）。
- 批量收割前留意脚本打印的 `X-RateLimit-Remaining`。

## 6. 找不到怎么办

找不到合格候选 = 这个工具的 skill **真得自己写** —— 这正是本仓库
`skills/ideaform*` 存在的理由。自己写的若够通用，发布后别人也能收割你的。
收割与自写不对立：**先收割，不够再写，写完反哺。**

## 7. 与 detect.py 的分工

| 管什么 | 谁管 |
|---|---|
| 工具**在哪**（路径、版本、能不能跑） | `detect.py` → 路径契约 |
| 工具**怎么用**（社区沉淀的现成知识） | `harvest-skills.py` → 技能目录 |

两者都把账记进同一份 `install-manifest.jsonl`。
