import React from "react";
import { AbsoluteFill, Audio, Composition, staticFile } from "remotion";
import { CUES, TOTAL_FRAMES, FPS } from "./timeline";
import { CANVAS, FONT, MARGIN, PAL, TYPE } from "./theme";
import { IdeaformIntro, LAYERS } from "./IdeaformIntro";

/**
 * Demo episode —— 由 ideaform 工作流生产。
 *
 * 音轨集成走【路线 A】：Remotion 直接集成两条音轨，渲出的 mp4 自带声音。
 *   - voice.wav 原样
 *   - bgm.wav   volume 由实测 RMS 反推：旁白 -24.36 dBFS、BGM -22.50 dBFS、
 *               目标低 9 dB → gain -15.40 dB → volume 0.2862
 *               （见 skills/ideaform/scripts/mix-av.sh --plan-only）
 *   - BGM 侧另做了一道硬门槛：LMMS 渲染后实测峰值必须 < 0 dBFS 且 0 削顶样本，
 *     master 从 0.30 一路降到 0.18 才干净（0.30 时 1306 个削顶样本）。
 */
export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="IdeaformIntro"
        component={IdeaformIntro}
        durationInFrames={TOTAL_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{}}
      />
      <Composition
        id="IntroWithAudio"
        component={IntroWithAudio}
        durationInFrames={TOTAL_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{}}
      />
      <Composition
        id="Cover"
        component={Cover}
        durationInFrames={1}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{}}
      />
    </>
  );
};

/** 画面 + 两条音轨（路线 A） */
const IntroWithAudio: React.FC = () => (
  <AbsoluteFill>
    <IdeaformIntro />
    <Audio src={staticFile("voice.wav")} />
    <Audio src={staticFile("bgm.wav")} volume={0.2862} />
  </AbsoluteFill>
);

/** 封面：静态 composition（禁用动画 —— still 时 useCurrentFrame 恒为 0） */
const Cover: React.FC = () => {
  const y1 = CANVAS.h * 1.12;
  const y2 = CANVAS.h * 0.52;
  return (
    <AbsoluteFill style={{ background: PAL.paper }}>
      <svg width={CANVAS.w} height={CANVAS.h} style={{ position: "absolute", inset: 0 }}>
        <line x1={-160} y1={y1} x2={CANVAS.w + 160} y2={y2} stroke={PAL.ink} strokeWidth={3} />
        <line x1={-160} y1={y1 + 14} x2={CANVAS.w + 160} y2={y2 + 14} stroke={PAL.red} strokeWidth={10} />
      </svg>

      <div style={{ position: "absolute", left: MARGIN, top: MARGIN, display: "flex", alignItems: "center", gap: 20 }}>
        <div style={{ width: 56, height: 56, background: PAL.red }} />
        <div style={{ fontFamily: FONT.mono, fontSize: TYPE.caption, letterSpacing: 6, color: PAL.ink2 }}>
          INTRO · 01
        </div>
      </div>

      <div style={{ position: "absolute", left: MARGIN, top: CANVAS.h * 0.24, width: CANVAS.w - MARGIN * 2 - 420 }}>
        <div style={{ fontFamily: FONT.mono, fontSize: TYPE.caption, letterSpacing: 8, color: PAL.red, marginBottom: 28 }}>
          开源工具链 · 解说视频工作流
        </div>
        <div style={{ fontFamily: FONT.display, fontSize: 168, lineHeight: 1.04, color: PAL.ink, letterSpacing: -3 }}>
          Ideaform
        </div>
        <div style={{ fontFamily: FONT.display, fontSize: 92, lineHeight: 1.1, color: PAL.red, letterSpacing: 8, marginTop: 6 }}>
          构想
        </div>
        <div style={{
          marginTop: 40, paddingTop: 28, borderTop: `2px solid ${PAL.rule}`,
          fontFamily: FONT.body, fontSize: TYPE.body, color: PAL.ink2, maxWidth: 900,
        }}>
          文稿、音轨、画面、音乐 —— 四样开源工具各管一段，ideaform 负责编排。
        </div>
      </div>

      <div style={{ position: "absolute", right: 0, bottom: 0, width: 420, height: 300, background: PAL.ink }}>
        <div style={{
          position: "absolute", right: 40, bottom: 128, textAlign: "right",
          color: PAL.paper, fontFamily: FONT.mono, fontSize: 19, letterSpacing: 2, lineHeight: 1.95, opacity: 0.85,
        }}>
          AI 文稿 · edge-tts<br />Remotion · LMMS<br />ffmpeg 合成
        </div>
        <div style={{ position: "absolute", right: 40, bottom: 36, color: PAL.paper, fontFamily: FONT.mono, fontSize: TYPE.caption, letterSpacing: 4 }}>
          IDEAFORM / 构想
        </div>
      </div>
    </AbsoluteFill>
  );
};
