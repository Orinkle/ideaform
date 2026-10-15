import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { CUES, TOTAL_FRAMES } from "./timeline";
import { CANVAS, FONT, MARGIN, PAL, TYPE } from "./theme";

/**
 * v2 · Ideaform 介绍片
 *
 * 与 v1 的差别：v1 只讲"工作流四步"，v2 讲清**每一样开源工具各管哪段、原理是什么**，
 * ideaform 的位置是**编排者**（配置工具 + 协调调用），不是生产者。
 *
 * 新增两件视觉装置，与"讲工具"这件事对齐：
 *   ① 底部流水线导轨 —— 文稿 / 声音 / 画面 / 音乐 / 成片 五个工位，
 *      当前工位红、已过墨、未到描边。解说走到哪一站，导轨就亮到哪。
 *   ② 右侧工具铭牌 —— 当前工位的工具名 + 一行原理（它到底怎么干活）。
 *
 * 保留的构造主义语言：纸/墨/红三色、栅格、对角轴（走在文字下方）、
 * 层次切换的几何扫过、进度条。层次变化只改**形态**（底色反相 / 栅格密度 /
 * 能量条数），不改身份 —— 和 BGM 的"变奏而非切歌"是同一个思路。
 */

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** 层次边界 —— 与 bgm-plan.py --layers "1:present,5:develop,8:intensify,15:contrast,22:resolve" 一致 */
export const LAYERS = [
  { from: CUES[0].start, to: CUES[4].start, tag: "01 问题", fn: "present" },
  { from: CUES[4].start, to: CUES[7].start, tag: "02 四件套", fn: "develop" },
  { from: CUES[7].start, to: CUES[14].start, tag: "03 逐站展开", fn: "intensify" },
  { from: CUES[14].start, to: CUES[21].start, tag: "04 编排", fn: "contrast" },
  { from: CUES[21].start, to: TOTAL_FRAMES, tag: "05 收束", fn: "resolve" },
] as const;

/** 每层的视觉形态 —— 只变形态，不变身份（纸/墨/红 + 栅格 + 对角轴） */
const LOOKS = [
  { bg: PAL.paper, fg: PAL.ink, sub: PAL.ink2, grid: 0.0, axisW: 3, bars: 1, invert: false },
  { bg: PAL.paper, fg: PAL.ink, sub: PAL.ink2, grid: 0.14, axisW: 4, bars: 2, invert: false },
  { bg: PAL.ink, fg: PAL.paper, sub: "#B8AE99", grid: 0.22, axisW: 11, bars: 5, invert: true },
  { bg: PAL.paper, fg: PAL.ink, sub: PAL.ink2, grid: 0.06, axisW: 3, bars: 1, invert: false },
  { bg: PAL.paper, fg: PAL.ink, sub: PAL.ink2, grid: 0.09, axisW: 3, bars: 2, invert: false },
] as const;

/** 五个工位 —— 起止帧取自解说时间轴（CUES），与 bgm-plan 的小节边界同源 */
const STATIONS = [
  {
    id: "01", name: "文稿", tool: "AI 大模型",
    from: CUES[7].start, to: CUES[7].end,
    principle: "把一句想法展开成分层的解说稿",
  },
  {
    id: "02", name: "声音", tool: "edge-tts",
    from: CUES[8].start, to: CUES[10].end,
    principle: "Edge 朗读服务 · 在线神经语音，无需密钥",
  },
  {
    id: "03", name: "画面", tool: "Remotion",
    from: CUES[11].start, to: CUES[13].end,
    principle: "React 描述画面 · 无头浏览器逐帧渲染",
  },
  {
    id: "04", name: "音乐", tool: "LMMS",
    from: CUES[14].start, to: CUES[19].end,
    principle: "开源 DAW · 照时间轴写小曲，离线渲染",
  },
  {
    id: "05", name: "成片", tool: "ffmpeg",
    from: CUES[20].start, to: CUES[20].end,
    principle: "音视频封装 · 两条流合成一个文件",
  },
] as const;

/** ideaform 自己的铭牌 —— 第 5 层（收束段）出现 */
const ORCHESTRATOR = {
  id: "·", name: "编排", tool: "ideaform",
  principle: "不生产内容 —— 配置工具、协调调用，用像素与分贝验收",
} as const;
const ORCHESTRATOR_AT = CUES[22].start;

/** 重音点帧号 —— 与 bgm-plan.py --accents "4,14,20,22,24,27" 一致（音乐在此抬力） */
const ACCENTS = [343, 1786, 2628, 2931, 3179, 3586] as const;
const ACCENT_LEN = 26;

const layerAt = (f: number) => {
  for (let i = LAYERS.length - 1; i >= 0; i--) if (f >= LAYERS[i].from) return i;
  return 0;
};
const cueAt = (f: number) => {
  for (let i = CUES.length - 1; i >= 0; i--) if (f >= CUES[i].start) return i;
  return 0;
};
const accentAt = (f: number) => {
  for (const a of ACCENTS) if (f >= a && f < a + ACCENT_LEN) return a;
  return null;
};

/** 元素入场：左→右揭幕（constructivist 的"扫过"），不用缩放弹跳 */
const reveal = (f: number, at: number, dur = 9) =>
  interpolate(f, [at, at + dur], [0, 1], clamp);

const Grid: React.FC<{ opacity: number; color: string }> = ({ opacity, color }) => {
  if (opacity <= 0) return null;
  const step = 120;
  const lines: React.ReactNode[] = [];
  for (let x = step; x < CANVAS.w; x += step)
    lines.push(<line key={`v${x}`} x1={x} y1={0} x2={x} y2={CANVAS.h} stroke={color} strokeWidth={1} />);
  for (let y = step; y < CANVAS.h; y += step)
    lines.push(<line key={`h${y}`} x1={0} y1={y} x2={CANVAS.w} y2={y} stroke={color} strokeWidth={1} />);
  return (
    <svg width={CANVAS.w} height={CANVAS.h} style={{ position: "absolute", inset: 0, opacity }}>
      {lines}
    </svg>
  );
};

/** 对角轴 —— 刻意走在文字块下方（版式铁律：不得穿过文字） */
const Axis: React.FC<{ width: number; ink: string; red: string }> = ({ width, ink, red }) => {
  const y1 = CANVAS.h * 1.12;
  const y2 = CANVAS.h * 0.52;
  return (
    <svg width={CANVAS.w} height={CANVAS.h} style={{ position: "absolute", inset: 0 }}>
      <line x1={-160} y1={y1} x2={CANVAS.w + 160} y2={y2} stroke={ink} strokeWidth={2} />
      <line x1={-160} y1={y1 + 14} x2={CANVAS.w + 160} y2={y2 + 14} stroke={red} strokeWidth={width} />
    </svg>
  );
};

/**
 * 流水线导轨 —— 五个工位。
 * 状态：已过（墨填充）/ 当前（红填充 + 重音时红环）/ 未到（仅描边）。
 * 解说走到哪一站，导轨就亮到哪；音乐重音时当前节点额外脉冲。
 */
const Rail: React.FC<{
  frame: number; fg: string; sub: string; red: string; accent: boolean; bg: string;
}> = ({ frame, fg, sub, red, accent, bg }) => {
  const y = 918;
  const x0 = 150;
  const x1 = 1770;
  const step = (x1 - x0) / (STATIONS.length - 1);
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {/* 导轨主线 */}
      <div style={{ position: "absolute", left: x0, top: y - 1, width: x1 - x0, height: 2, background: fg, opacity: 0.3 }} />
      {STATIONS.map((s, i) => {
        const cx = x0 + i * step;
        const done = frame >= s.to;
        const active = frame >= s.from && frame < s.to;
        const box = 26;
        return (
          <React.Fragment key={s.id}>
            {/* 已过区间的导轨染墨，让"走到哪"一眼可读 */}
            {done && i < STATIONS.length - 1 && (
              <div style={{ position: "absolute", left: cx, top: y - 3, width: step, height: 6, background: fg, opacity: 0.55 }} />
            )}
            <div style={{
              position: "absolute", left: cx - box / 2, top: y - box / 2, width: box, height: box,
              background: done ? fg : active ? red : "transparent",
              border: `2px solid ${done || active ? "transparent" : `${fg}66`}`,
              boxShadow: active && accent ? `0 0 0 8px ${red}33` : "none",
            }} />
            <div style={{
              position: "absolute", left: cx - 90, top: y + 26, width: 180, textAlign: "center",
              fontFamily: FONT.mono, fontSize: 22, letterSpacing: 2,
              color: active ? red : done ? fg : `${fg}80`,
              background: bg, padding: "2px 0",
            }}>
              {s.id} {s.name}
            </div>
            <div style={{
              position: "absolute", left: cx - 90, top: y + 56, width: 180, textAlign: "center",
              fontFamily: FONT.mono, fontSize: 18, letterSpacing: 1,
              color: active ? red : sub, opacity: active ? 1 : 0.65,
              background: bg, padding: "2px 0",
            }}>
              {s.tool}
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
};

/**
 * 右侧工具铭牌 —— 当前工位的工具名 + 一行原理。
 * 这是 v2 新增的核心信息件：告诉观众"这一站到底是谁在干活、它怎么干"。
 */
const Plate: React.FC<{
  frame: number; at: number; fg: string; sub: string; red: string; invert: boolean;
  data: { id: string; tool: string; principle: string };
}> = ({ frame, at, fg, sub, red, invert, data }) => {
  const p = reveal(frame, at, 12);
  const line = invert ? "#5A5346" : PAL.rule;
  return (
    <div style={{
      position: "absolute", right: MARGIN, top: 300, width: 400,
      opacity: p, transform: `translateX(${(1 - p) * 36}px)`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{ width: 10, height: 10, background: red }} />
        <div style={{ fontFamily: FONT.mono, fontSize: 20, letterSpacing: 5, color: red }}>
          STATION {data.id}
        </div>
      </div>
      <div style={{
        marginTop: 18, paddingTop: 20, borderTop: `2px solid ${line}`,
        fontFamily: FONT.display, fontSize: 58, color: fg, letterSpacing: -1, lineHeight: 1.1,
      }}>
        {data.tool}
      </div>
      <div style={{ marginTop: 10, fontFamily: FONT.body, fontSize: 27, lineHeight: 1.5, color: sub }}>
        {data.principle}
      </div>
      {/* 几何记号：三条长度不等的横条，暗示"分层/分轨" */}
      <div style={{ marginTop: 26, display: "flex", flexDirection: "column", gap: 8 }}>
        {[0.42, 0.72, 1.0].map((w, i) => (
          <div key={i} style={{ width: 400 * w, height: 6, background: i === 2 ? red : fg, opacity: i === 2 ? 1 : 0.55 }} />
        ))}
      </div>
    </div>
  );
};

/** 能量计 —— 视觉上呼应 BGM 的力度弧；重音时整体涨一档 */
const EnergyMeter: React.FC<{
  n: number; fg: string; red: string; frame: number; layerStart: number; accent: boolean;
}> = ({ n, fg, red, frame, layerStart, accent }) => {
  const grow = (i: number) => interpolate(frame, [layerStart + 4 + i * 3, layerStart + 18 + i * 3], [0, 1], clamp);
  return (
    <div style={{ position: "absolute", left: MARGIN, top: 600, width: 400 }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "baseline",
        fontFamily: FONT.mono, fontSize: 18, letterSpacing: 4, marginBottom: 16,
        color: accent ? red : fg, opacity: accent ? 1 : 0.6,
      }}>
        <span>力度 / DYNAMICS</span>
        <span>{accent ? "▲ 重音" : `${n} / 5`}</span>
      </div>
      {[0, 1, 2, 3, 4].map((i) => {
        const active = i < n;
        const w = (active ? 0.34 + i * 0.15 + (accent ? 0.1 : 0) : 0.07) * 400 * grow(i);
        return (
          <div key={i} style={{ marginBottom: 10 }}>
            <div style={{
              width: Math.max(4, w), height: 14,
              background: active ? (i === n - 1 ? red : fg) : "transparent",
              border: `2px solid ${active ? "transparent" : `${fg}44`}`,
            }} />
          </div>
        );
      })}
    </div>
  );
};

/** 层次切换的扫过块 —— 用几何位移做转场，不用淡入淡出 */
const Sweep: React.FC<{ frame: number; at: number; red: string; ink: string }> = ({ frame, at, red, ink }) => {
  const p = interpolate(frame, [at - 12, at + 6], [0, 1], clamp);
  if (p <= 0 || p >= 1) return null;
  const w = CANVAS.w * 0.55;
  const x = -w + p * (CANVAS.w + w);
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <div style={{ position: "absolute", left: x, top: 0, width: w, height: CANVAS.h, background: ink }} />
      <div style={{ position: "absolute", left: x - 18, top: 0, width: 18, height: CANVAS.h, background: red }} />
    </div>
  );
};

export const IdeaformIntro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const li = layerAt(frame);
  const ci = cueAt(frame);
  const look = LOOKS[li];
  const cue = CUES[ci];
  const layer = LAYERS[li];
  const prog = frame / (TOTAL_FRAMES - 1);

  // 当前工位 / 铭牌内容
  let plate: { id: string; tool: string; principle: string } | null = null;
  let plateAtFrame = 0;
  if (frame >= ORCHESTRATOR_AT) {
    plate = ORCHESTRATOR;
    plateAtFrame = ORCHESTRATOR_AT;
  } else {
    for (const s of STATIONS) {
      if (frame >= s.from && frame < s.to) {
        plate = { id: s.id, tool: s.tool, principle: s.principle };
        plateAtFrame = s.from;
        break;
      }
    }
  }

  const accent = accentAt(frame);
  const accentP = accent === null ? 0 : interpolate(
    frame, [accent, accent + 5, accent + 12, accent + ACCENT_LEN], [0, 1, 1, 0], clamp,
  );

  const text = cue.text;
  const fs = text.length > 20 ? 66 : text.length > 16 ? 76 : text.length > 12 ? 86 : text.length > 8 ? 100 : 112;
  const p = reveal(frame, cue.start, 9);

  return (
    <AbsoluteFill style={{ background: look.bg }}>
      <Grid opacity={look.grid} color={look.invert ? "#5A5346" : PAL.rule} />
      <Axis width={look.axisW} ink={look.fg} red={PAL.red} />

      {/* 左上：系列标识 */}
      <div style={{ position: "absolute", left: MARGIN, top: MARGIN, display: "flex", alignItems: "center", gap: 20 }}>
        <div style={{ width: 48, height: 48, background: PAL.red }} />
        <div style={{ fontFamily: FONT.mono, fontSize: TYPE.caption, letterSpacing: 6, color: look.sub }}>
          IDEAFORM
        </div>
      </div>

      {/* 右上：当前层次标签（重音时整块转红） */}
      <div style={{ position: "absolute", right: MARGIN, top: MARGIN, display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{
          width: 14, height: 14,
          background: accentP > 0.5 ? PAL.red : look.sub, opacity: accentP > 0.5 ? 1 : 0.5,
        }} />
        <div style={{
          fontFamily: FONT.mono, fontSize: TYPE.caption, letterSpacing: 4,
          color: accentP > 0.5 ? PAL.red : look.sub,
        }}>
          {layer.tag}
        </div>
        <div style={{ width: 120, height: 2, background: look.sub, opacity: 0.5 }} />
      </div>

      {/* 主文字：左对齐，按句揭幕（宽度避开右侧铭牌区） */}
      <div style={{
        position: "absolute", left: MARGIN, top: CANVAS.h * 0.32,
        width: 1240, overflow: "hidden",
      }}>
        <div style={{
          clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`,
          fontFamily: FONT.display, fontSize: fs, lineHeight: 1.22,
          color: look.fg, letterSpacing: -1, whiteSpace: "pre-wrap",
        }}>
          {text}
        </div>
      </div>

      {/* 右侧：工具铭牌 */}
      {plate && (
        <Plate
          frame={frame} at={plateAtFrame} fg={look.fg} sub={look.sub}
          red={PAL.red} invert={look.invert} data={plate}
        />
      )}

      {/* 右侧：力度计 */}
      <EnergyMeter
        n={look.bars} fg={look.fg} red={PAL.red}
        frame={frame} layerStart={layer.from} accent={accent !== null}
      />

      {/* 左缘重音条 —— 音乐抬力时同步闪一下（刻意避开文字块） */}
      <div style={{
        position: "absolute", left: 0, top: 250, width: 14, height: 580,
        background: PAL.red, opacity: accentP,
      }} />

      {/* 底部：流水线导轨 */}
      <Rail frame={frame} fg={look.fg} sub={look.sub} red={PAL.red} accent={accent !== null} bg={look.bg} />

      {/* 左下：版式署名（避开导轨标签与进度条） */}
      <div style={{
        position: "absolute", left: 40, bottom: 24, fontFamily: FONT.mono, fontSize: 19,
        letterSpacing: 3, color: look.sub, opacity: 0.75,
      }}>
        构造主义版式
      </div>

      {/* 进度条 */}
      <div style={{ position: "absolute", left: 0, bottom: 0, width: CANVAS.w, height: 8, background: look.invert ? "#2A251E" : PAL.paper2 }}>
        <div style={{ width: `${prog * 100}%`, height: "100%", background: PAL.red }} />
      </div>
      <div style={{ position: "absolute", right: 40, bottom: 24, fontFamily: FONT.mono, fontSize: 20, color: look.sub, opacity: 0.6 }}>
        {String(Math.floor(frame / fps)).padStart(2, "0")}s / {Math.round(TOTAL_FRAMES / fps)}s
      </div>

      {/* 层次切换的扫过块 */}
      {LAYERS.slice(1).map((l, i) => (
        <Sweep key={i} frame={frame} at={l.from} red={PAL.red} ink={look.invert ? PAL.paper : PAL.ink} />
      ))}
    </AbsoluteFill>
  );
};
