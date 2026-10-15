import React from "react";
import { Composition } from "remotion";
import { Cover } from "./Cover";

/**
 * 封面 composition —— 构造主义版式。
 *
 * ⚠️ durationInFrames={1} 且组件内**不要用动画**（useCurrentFrame 恒为 0，
 * 动画初值会让元素不可见）。见 headless-visual-verify 的说明。
 */
export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Cover"
        component={Cover}
        durationInFrames={1}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{
          kicker: "构造主义解说视频",
          title: "标题占位",
          subtitle: "副标题 / 一句话主张",
          episode: "01",
        }}
      />
    </>
  );
};
