#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen-structures.py —— SMILES → 确定性 2D 化学结构 SVG → 帧驱动的 Remotion 组件

为什么要有它：**结构式和通路图绝不能交给 AI 生成图片去画**（必然画错、不可复现、
还带着肉眼看不出的幻构键）。本脚本用 RDKit 做确定性描绘：同一 SMILES 永远得到
同一张图，分子式可离线校验。

════════════════════════════════════════════════════════════════════════════
本脚本是「拿来主义」的产物，不是从零造的。来源与许可（均为 OSI 许可，可合法抄改）：

 · ghutchis/chem-skill  · MIT
   —— 名字 → SMILES 的解析链与优先级（本地表 → OPSIN 离线 → PubChem 联网）。
   https://github.com/ghutchis/chem-skill
 · synthetic-sciences/openscience  · Apache-2.0
   —— molecule-visualization 的发表级绘制基线（bondLineWidth / fixedBondLength /
      Kekulize 容错写法）与 CPK 色板、字号、线宽规范。
   backend/cli/skills/chemistry/molecule-visualization/{SKILL.md,scripts/draw_2d.py,
   references/style_guide.md}
 · VectorSpaceLab/AREX-Skill  · Apache-2.0
   —— conformers-drawing 的绘制路由训示：SVG 输出优先 rdMolDraw2D.MolDraw2DSVG。
 · RDKit 官方 MolDrawOptions
   —— useBWAtomPalette / setSymbolColour / setBackgroundColour / singleColourBonds /
      fixedBondLength / padding。本机 2026.09.1 已逐项核实接口存在。

★ 本脚本相对上述来源**唯一新增**的东西：帧驱动动画钩子（见下「SVG 清理规则 3/4」）。
  这一件确实没有现成方案 —— 因为别人的用途是「出一张静止的图」，
  而我们的用途是「在 Remotion 里逐笔描出来」。除此之外一律不自己造。

⚠️ 反面教训（别再犯）：**不要用正则按颜色去后处理 RDKit 的 SVG**。
   颜色分类既脆弱（RDKit 改版就会把颜色从 style 挪到属性）、又是重复造轮子。
   配色一律走官方 options（`useBWAtomPalette` 等）在**落笔前**定好；
   后处理只负责「挂动画钩子」，而分类依据必须是官方 class 语义。

════════════════════════════════════════════════════════════════════════════
输入：一个 TSV（tab 分隔，带表头；表头顺序随意，列名固定）
    key <TAB> name <TAB> smiles <TAB> formula
  · key     ASCII 短名，做文件名/组件名（如 lutein / bcarotene）
  · name    显示名，可中文（仅用于注释与 manifest；smiles 留空时也拿它去 PubChem 查）
  · smiles  SMILES（推荐带立体标记，如 /C=C/ 或 @）
  · formula 期望分子式（Hill 记法，如 C40H56O2）；留空则跳过校验

输出（默认 ./structures）：
    svg/<key>.svg                  清理过的 SVG（见下）
    components/<Pascal>.tsx        **帧驱动**的 Remotion 组件（自带动画）
    components/index.ts            barrel
    manifest.json                  key → name/smiles/formula/组件名/路径

════════════════════════════════════════════════════════════════════════════
SVG 后处理规则（只做动画钩子 + 两处保险，不做任何颜色分类）：
  1. 删掉可能存在的整幅背景 <rect>（`clearBackground=False` 之后本不该有，纯保险）
  2. 单色模式下把 SVG 里残留的颜色 token 整幅换成目标色。单色模式下 RDKit
     只会吐一个颜色，所以这里是「一个 token 换一次」，不是颜色分类。
     `--theme cpk` 时**跳过本步**（要保留 O 红 / N 蓝）。
  3. 键线（`class` 以 `bond-` 开头）→ 加 `pathLength='1'` 并挂
     `stroke-dasharray:1; stroke-dashoffset:var(--mol-dash,0)`  ← 描线动画钩子
  4. 原子字符（`class` 以 `atom-` 开头）→ 挂 `opacity:var(--mol-text,1)` ← 字符淡入钩子
     ★ 分类**只看官方 class 语义**。RDKit 给键打 `bond-<n> atom-a atom-b`、
     给原子字符打 `atom-<n>`，这是稳定契约。绝不要按"有没有 fill"或颜色去猜：
     原子字符的形态随 RDKit 版本变（风格上是填充块还是描边轮廓），猜必错。
  5. 根 <svg> 的 width/height 改 100%，保留 viewBox → 由外层容器缩放

★ 生成的组件**必须帧驱动**（useCurrentFrame → CSS 变量）。
  **绝对不要用 CSS @keyframes**：Remotion 渲染时时间由帧给，@keyframes 跟的是墙钟，
  在离屏渲染里不前进 —— 元素会永远停在初始（隐藏）状态，看起来像"分子没渲染"。

════════════════════════════════════════════════════════════════════════════
用法：
  PY=<venv>/bin/python
  $PY gen-structures.py --tsv smiles.tsv --out structures
  $PY gen-structures.py --tsv smiles.tsv --check            # 只校验，不出图
  $PY gen-structures.py --tsv smiles.tsv --theme cpk        # 保留元素异色（发表级观感）
  $PY gen-structures.py --tsv smiles.tsv --pubchem          # 联网交叉核对分子式
  $PY gen-structures.py --tsv smiles.tsv --lookup           # smiles 留空的用名字去 PubChem 补
  $PY gen-structures.py --help

退出码：0 全通过；1 有分子未通过校验（分子式不符 / 无法解析 / 结构为空）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# ── RDKit ────────────────────────────────────────────────────────────────
try:
    from rdkit import Chem, RDLogger
    from rdkit.Chem import rdMolDescriptors
    from rdkit.Chem.Draw import rdMolDraw2D
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "缺少 rdkit。装它：\n"
        "  TMPDIR=<大盘> <venv>/bin/pip install rdkit\n"
        "（本机 /tmp 只有 10MB，TMPDIR 不指大盘会 ENOSPC）\n"
    )
    raise SystemExit(2)

RDLogger.DisableLog("rdApp.*")  # 别让 RDKit 把 warning 刷到 stderr

HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?\b")  # 6 位或 8 位（带 alpha）
PATH_RE = re.compile(r"<path\b[^>]*?/>", re.S)
RECT_RE = re.compile(r"<rect\b[^>]*>\s*</rect>|<rect\b[^>]*/>", re.S)
SVG_OPEN_RE = re.compile(r"<svg\b[^>]*>", re.S)
STYLE_RE = re.compile(r"style='([^']*)'")
CLASS_RE = re.compile(r"class='([^']*)'")

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"


# ══════════════════════════════════════════════════════════════════════════
# 1. 输入
# ══════════════════════════════════════════════════════════════════════════
def load_tsv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8-sig") as fh:   # utf-8-sig：吃掉 BOM（Windows/编辑器常带）
        header: list[str] | None = None
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cells = line.split("\t")
            if len(cells) == 1:                     # 容忍只有空格没有 tab 的"伪 TSV"
                cells = re.split(r" {2,}", line)
            if header is None:
                header = [c.strip().lower() for c in cells]
                if "key" not in header:
                    raise SystemExit(
                        f"{path}:{lineno} 表头缺列 `key`（需要 key/name/smiles/formula）"
                    )
                continue
            row = {h: (cells[i].strip() if i < len(cells) else "") for i, h in enumerate(header)}
            if not row.get("key"):
                continue
            rows.append(row)
    if not rows:
        raise SystemExit(f"{path}: 没读到任何数据行（表头要写 key/name/smiles/formula）")
    return rows


def pascal(key: str) -> str:
    parts = re.split(r"[^0-9A-Za-z]+", key)
    out = "".join(p[:1].upper() + p[1:] for p in parts if p)
    if not out:
        raise SystemExit(f"key `{key}` 不是合法 ASCII 短名")
    if out[0].isdigit():
        out = "Mol" + out
    return out


# ══════════════════════════════════════════════════════════════════════════
# 2. 名字 → SMILES（抄 chem-skill 的解析链，去掉 pubchempy/py2opsin 依赖，
#    只用标准库 urllib 直连 PubChem REST；OPSIN 是 Java jar，此处不引入）
# ══════════════════════════════════════════════════════════════════════════
def _pubchem(name: str, prop: str, timeout: int = 15):
    """按名字取 PubChem 属性。离线/查不到一律返回 None，不抛异常、不中断主流程。"""
    url = PUBCHEM + urllib.parse.quote(name, safe="") + f"/property/{prop}/JSON"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["PropertyTable"]["Properties"][0].get(prop)
    except Exception:
        return None


def pubchem_smiles(name: str) -> str | None:
    # ⚠️ 属性名必须是 `SMILES`。写 `IsomericSMILES` 会 KeyError（PubChem 返回的
    #    JSON key 就是请求串本身，而 IsomericSMILES 不在 PUG-REST 的 property 表里）。
    return _pubchem(name, "SMILES")


def pubchem_formula(name: str) -> str | None:
    return _pubchem(name, "MolecularFormula")


# ══════════════════════════════════════════════════════════════════════════
# 3. 校验
# ══════════════════════════════════════════════════════════════════════════
def check_mol(smiles: str, expected_formula: str) -> tuple[Chem.Mol | None, str, str]:
    """返回 (mol, 计算分子式, 结论)。结论 ∈ ok / 公式不符 / 解析失败"""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None, "", "解析失败"
    Chem.SanitizeMol(mol)
    calc = rdMolDescriptors.CalcMolFormula(mol)
    if expected_formula:
        a = calc.replace("+", "").replace("-", "").replace(" ", "")
        b = expected_formula.replace("+", "").replace("-", "").replace(" ", "")
        if a != b:
            return mol, calc, "公式不符"
    return mol, calc, "ok"


# ══════════════════════════════════════════════════════════════════════════
# 4. 描绘 —— 配色全部在**落笔前**用官方 options 定好（不做颜色后处理）
# ══════════════════════════════════════════════════════════════════════════
# 发表级绘制基线（数值取自 openscience molecule-visualization 的 style_guide.md）
BOND_LINE_WIDTH = 2.2        # 规范区间 1.5–2.5，推荐 2.0；线上视频用 2.2 更抗压缩
FIXED_BOND_LENGTH = 30.0     # 固定键长 → 多张图之间观感一致
LABEL_PAD = 0.06
PADDING = 0.10


def render_svg(mol: Chem.Mol, width: int, height: int, theme: str,
               font: float, kekulize: bool) -> str:
    # PrepareMolForDrawing：补 H、加楔形键、可选 Kekulize，返回**新的** mol
    m = rdMolDraw2D.PrepareMolForDrawing(mol, kekulize=kekulize)

    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    o = drawer.drawOptions()

    o.clearBackground = False            # 透明底：纸色版式 / 墨色版式上都不会糊一块白板
    o.padding = PADDING
    o.bondLineWidth = BOND_LINE_WIDTH
    o.fixedBondLength = FIXED_BOND_LENGTH
    o.additionalAtomLabelPadding = LABEL_PAD
    o.minFontSize = 12                   # 规范：原子标号 ≥ 10pt
    o.maxFontSize = int(font * 40)

    if theme == "paper-ink":
        # ★ 官方单色：这一步取代了旧版「按颜色正则替换」的全部逻辑
        o.useBWAtomPalette()             # 所有元素同一色
        o.singleColourBonds = True       # 双键、楔键也用同一色
        o.setSymbolColour((0.0, 0.0, 0.0, 1.0))   # 原子字符色（后续整幅换成 --ink）
    else:                                # cpk
        o.useDefaultAtomPalette()        # O 红 / N 蓝 / S 黄，发表级观感

    drawer.DrawMolecule(m)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def clean_svg(raw: str, ink: str, theme: str) -> tuple[str, int, int]:
    """按文件头「SVG 后处理规则」改写。返回 (svg, 键线条数, 字符 glyph 条数)"""
    svg = RECT_RE.sub("", raw)                       # 规则 1（保险）

    if theme != "cpk":                               # 规则 2（单色模式下 token 唯一）
        svg = HEX_RE.sub(ink, svg)

    n_bonds = n_glyphs = 0

    def fix_path(m: re.Match) -> str:
        nonlocal n_bonds, n_glyphs
        tag = m.group(0)
        sm = STYLE_RE.search(tag)
        style = sm.group(1) if sm else ""

        # 规则 3/4 的分类：**只认官方 class 语义**
        cm = CLASS_RE.search(tag)
        cls = cm.group(1) if cm else ""
        is_bond = cls.startswith("bond-")
        if not cls:
            # 没 class 的 path（RDKit 只对少数装饰线如此）→ 按描边特征兜底
            is_bond = "fill:none" in style.replace(" ", "")

        if is_bond:
            n_bonds += 1
            new_style = (style + ";stroke-dasharray:1;stroke-dashoffset:var(--mol-dash,0)").lstrip(";")
            tag = tag.replace("<path", "<path pathLength='1'", 1)
        else:
            n_glyphs += 1
            new_style = (style + ";opacity:var(--mol-text,1)").lstrip(";")

        if sm:
            tag = tag.replace(sm.group(0), f"style='{new_style}'")
        else:
            # 原本没有 style 属性（新版 RDKit 的原子字符）→ 新插一个
            tag = tag.replace("<path", f"<path style='{new_style}'", 1)
        return tag

    svg = PATH_RE.sub(fix_path, svg)

    def fix_root(m: re.Match) -> str:                                            # 规则 5
        tag = m.group(0)
        tag = re.sub(r"width='[^']*'", "width='100%'", tag, count=1)
        tag = re.sub(r"height='[^']*'", "height='100%'", tag, count=1)
        return tag

    svg = SVG_OPEN_RE.sub(fix_root, svg, count=1)
    if "viewBox" not in svg:
        raise SystemExit("SVG 没有 viewBox，缩放会失真 —— RDKit 版本可能变了，检查 render_svg()")
    return svg, n_bonds, n_glyphs


# ══════════════════════════════════════════════════════════════════════════
# 5. 生成 Remotion 组件
# ══════════════════════════════════════════════════════════════════════════
TSX_TPL = r"""/**
 * 自动生成 · 请勿手改 —— 改 SMILES 请改 .tsv 后重跑 gen-structures.py
 *
 * 分子：__NAME__（__SMILES__）
 * 分子式：__FORMULA__
 * 生成器：skills/ideaform/scripts/gen-structures.py
 *
 * ★ 动画是**帧驱动**的：useCurrentFrame → CSS 变量 --mol-dash / --mol-text。
 *   不要在 SVG 里塞 CSS @keyframes —— Remotion 离屏渲染不推进墙钟动画，
 *   元素会永远停在初始（隐藏）态，看起来像"分子没渲染出来"。
 */
import React from "react";
import { interpolate, useCurrentFrame } from "remotion";

const RAW = `__RAW__`;

export type MolProps = {
  /** 边长 px。SVG 自带 viewBox，等比铺满 */
  size?: number;
  /** 线/字颜色，默认继承父级 color（构造主义墨色体系里就靠这个统一） */
  color?: string;
  /** 起始帧（相对所在 Sequence） */
  at?: number;
  /** 画完用多少帧 */
  dur?: number;
  /** draw = 逐笔描线（默认）；fade = 整体淡入 */
  mode?: "draw" | "fade";
};

export const __PASCAL__: React.FC<MolProps> = ({
  size = 320,
  color = "currentColor",
  at = 0,
  dur = 45,
  mode = "draw",
}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [at, at + Math.max(1, dur)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  // 骨架先描出来，原子符号/双键补线在后 65% 淡入
  const dash = mode === "draw" ? 1 - p : 0;
  const text = mode === "draw" ? Math.min(1, Math.max(0, (p - 0.35) / 0.65)) : p;

  const style: React.CSSProperties = { width: size, height: size, color };
  (style as Record<string, string>)["--mol-dash"] = String(dash);
  (style as Record<string, string>)["--mol-text"] = String(text);

  return <div style={style} dangerouslySetInnerHTML={{ __html: RAW }} />;
};

export default __PASCAL__;
"""


def write_component(comp_dir: Path, key: str, row: dict, svg: str) -> str:
    name = pascal(key)
    raw = svg.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    tsx = (
        TSX_TPL.replace("__PASCAL__", name)
        .replace("__NAME__", row.get("name") or key)
        .replace("__SMILES__", row["smiles"])
        .replace("__FORMULA__", row.get("_calc") or "—")
        .replace("__RAW__", raw)
    )
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / f"{name}.tsx").write_text(tsx, encoding="utf-8")
    return name


# ══════════════════════════════════════════════════════════════════════════
# 6. main
# ══════════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(
        description="SMILES → 确定性化学结构 SVG → 帧驱动的 Remotion 组件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--tsv", required=True, help="输入 TSV：key/name/smiles/formula")
    ap.add_argument("--out", default="structures", help="输出目录（默认 ./structures）")
    ap.add_argument("--check", action="store_true", help="只校验分子式，不出图不出组件")
    ap.add_argument("--theme", choices=["paper-ink", "cpk"], default="paper-ink",
                    help="paper-ink=单色墨（默认，配构造主义唯一强调色）；cpk=保留元素异色")
    ap.add_argument("--ink", default="currentColor",
                    help="单色模式下颜色 token 换成什么（默认 currentColor，由外层 color 决定）")
    ap.add_argument("--kekulize", action="store_true",
                    help="芳香环画成交替单双键（style_guide 推荐用于出版物；默认关）")
    ap.add_argument("--lookup", action="store_true",
                    help="smiles 列留空时，用 name 去 PubChem 补 SMILES（需联网）")
    ap.add_argument("--pubchem", action="store_true",
                    help="联网用 PubChem 交叉核对分子式（默认关）")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--font", type=float, default=0.9, help="原子字号系数（0.5~1.5）")
    args = ap.parse_args()

    tsv = Path(args.tsv).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    rows = load_tsv(tsv)
    comp_dir = out / "components"

    print(f"输入 {tsv}  ·  {len(rows)} 个分子")
    print("-" * 78)
    print(f"{'key':<14}{'计算分子式':<16}{'期望':<16}{'结果':<8}{'键':>4}{'字':>4}{'PubChem':>10}")
    print("-" * 78)

    failed: list[str] = []
    manifest: list[dict] = []

    for row in rows:
        key = row["key"]

        if not row.get("smiles"):
            if args.lookup and row.get("name"):
                got = pubchem_smiles(row["name"])
                if got:
                    row["smiles"] = got
                else:
                    row["_calc"] = ""
                    print(f"{key:<14}{'—':<16}{'—':<16}{'无 SMILES':<8}"
                          f"{0:>4}{0:>4}{'查不到':>10} ✘")
                    failed.append(f"{key}: 无 SMILES 且 PubChem 查不到（name={row['name']}）")
                    continue
            else:
                print(f"{key:<14}{'—':<16}{'—':<16}{'缺 SMILES':<8}{0:>4}{0:>4}{'':>10} ✘")
                failed.append(f"{key}: smiles 列留空（加 --lookup 用 name 去 PubChem 补）")
                continue

        mol, calc, verdict = check_mol(row["smiles"], row.get("formula", ""))
        row["_calc"] = calc
        pc = ""
        if args.pubchem and row.get("name"):
            got = pubchem_formula(row["name"])
            pc = got or "查不到"
            if got and calc and got.replace(" ", "") != calc:
                verdict = "公式不符"
                pc += " ✗"

        if verdict == "ok" and calc:
            # 自证：SMILES 往返一次仍可解析（防手抄错）
            if Chem.MolFromSmiles(Chem.MolToSmiles(mol)) is None:
                verdict = "解析失败"

        n_bonds = n_glyphs = 0
        if verdict == "ok" and not args.check:
            svg = render_svg(mol, args.width, args.height, args.theme, args.font, args.kekulize)
            svg, n_bonds, n_glyphs = clean_svg(svg, args.ink, args.theme)
            if n_bonds == 0:
                verdict = "结构为空"
            else:
                (out / "svg").mkdir(parents=True, exist_ok=True)
                (out / "svg" / f"{key}.svg").write_text(svg, encoding="utf-8")
                cname = write_component(comp_dir, key, row, svg)
                manifest.append({
                    "key": key, "name": row.get("name", ""), "smiles": row["smiles"],
                    "formula": calc, "component": cname,
                    "svg": f"svg/{key}.svg", "tsx": f"components/{cname}.tsx",
                })

        mark = "✔" if verdict == "ok" else "✘"
        print(f"{key:<14}{calc or '—':<16}{(row.get('formula') or '—'):<16}{verdict:<8}"
              f"{n_bonds:>4}{n_glyphs:>4}{pc:>10} {mark}")
        if verdict != "ok":
            failed.append(f"{key}: {verdict}")

    print("-" * 78)

    if not args.check and manifest:
        barrel = "// 自动生成 · gen-structures.py（barrel）\n" + "".join(
            f'export * from "./{m["component"]}";\n' for m in manifest
        )
        (comp_dir / "index.ts").write_text(barrel, encoding="utf-8")
        (out / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"产出 {len(manifest)} 组：{out}/svg/*.svg  +  {out}/components/*.tsx  +  manifest.json")
        print("接进 Remotion：把 components/ 拷进工程 src/，再")
        print("  import { Lutein } from \"./components\";")
        print("  <Lutein at={60} dur={30} color={PAL.ink} />")
        print("⚠ 外层记得给 color（分子用 currentColor）；别用 CSS @keyframes 做动画。")

    if failed:
        print("\n未通过：")
        for f in failed:
            print("  ·", f)
        return 1
    print("\n全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
