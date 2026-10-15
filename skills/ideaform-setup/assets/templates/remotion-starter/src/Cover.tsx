import React from "react";
import { AbsoluteFill } from "remotion";
import { CANVAS, FONT, MARGIN, PAL, TYPE } from "./theme";

/**
 * 构造主义封面 —— 静态版式（无动画）。
 *
 * 语言：纸色底 + 墨黑重体字 + 一条红；
 *      一条对角轴贯穿画面，几何块面压住四角，其余留白。
 * 所有数值来自 theme.ts，不写死。
 */

const Axis: React.FC = () => {
  // 对角轴：从下边缘偏左穿到右边缘中部，**整体走在文字块下方**。
  // 版式铁律：轴线不得穿过任何文字（走廊纯净度）。
  // 文字块底边约 0.65H，轴线在该处的 y 必须 > 0.72H。
  const y1 = CANVAS.h * 1.12;
  const y2 = CANVAS.h * 0.52;
  return (
    <svg
      width={CANVAS.w}
      height={CANVAS.h}
      viewBox={`0 0 ${CANVAS.w} ${CANVAS.h}`}
      style={{ position: "absolute", inset: 0 }}
    >
      <line x1={-160} y1={y1} x2={CANVAS.w + 160} y2={y2}
            stroke={PAL.ink} strokeWidth={3} />
      <line x1={-160} y1={y1 + 14} x2={CANVAS.w + 160} y2={y2 + 14}
            stroke={PAL.red} strokeWidth={10} />
    </svg>
  );
};

const CornerBlock: React.FC = () => (
  // 右下墨块：几何压角，制造非对称张力
  <div
    style={{
      position: "absolute",
      right: 0,
      bottom: 0,
      width: 420,
      height: 300,
      background: PAL.ink,
    }}
  >
    <div
      style={{
        position: "absolute",
        right: 40,
        bottom: 36,
        color: PAL.paper,
        fontFamily: FONT.mono,
        fontSize: TYPE.caption,
        letterSpacing: 4,
      }}
    >
      IDEAFORM / 构想
    </div>
  </div>
);

const Series: React.FC<{ episode: string }> = ({ episode }) => (
  <div
    style={{
      position: "absolute",
      left: MARGIN,
      top: MARGIN,
      display: "flex",
      alignItems: "center",
      gap: 20,
    }}
  >
    <div style={{ width: 56, height: 56, background: PAL.red }} />
    <div
      style={{
        fontFamily: FONT.mono,
        fontSize: TYPE.caption,
        letterSpacing: 6,
        color: PAL.ink2,
      }}
    >
      EP {episode}
    </div>
  </div>
);

export const Cover: React.FC<{
  kicker: string;
  title: string;
  subtitle: string;
  episode: string;
}> = ({ kicker, title, subtitle, episode }) => {
  return (
    <AbsoluteFill style={{ background: PAL.paper }}>
      <Axis />

      <Series episode={episode} />

      {/* 主文字区：左对齐、压在栅格上。
          高度压到 ~0.66H 以内，给下方对角轴留出净空。 */}
      <div
        style={{
          position: "absolute",
          left: MARGIN,
          top: CANVAS.h * 0.26,
          width: CANVAS.w - MARGIN * 2 - 420,
        }}
      >
        <div
          style={{
            fontFamily: FONT.mono,
            fontSize: TYPE.caption,
            letterSpacing: 8,
            color: PAL.red,
            marginBottom: 28,
          }}
        >
          {kicker}
        </div>
        <div
          style={{
            fontFamily: FONT.display,
            fontSize: TYPE.hero,
            lineHeight: 1.08,
            color: PAL.ink,
            letterSpacing: -2,
          }}
        >
          {title}
        </div>
        <div
          style={{
            marginTop: 36,
            paddingTop: 28,
            borderTop: `2px solid ${PAL.rule}`,
            fontFamily: FONT.body,
            fontSize: TYPE.body,
            color: PAL.ink2,
            maxWidth: 900,
          }}
        >
          {subtitle}
        </div>
      </div>

      <CornerBlock />
    </AbsoluteFill>
  );
};
