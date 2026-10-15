/**
 * 构造主义视觉系统 · 单一事实来源
 *
 * 所有颜色 / 字体 / 栅格都从这里取，组件不写死数值。
 * 换配色或换字体只改这一个文件。
 */

/** 主调色板 —— 与既有成片一致（paper / ink / red 三色体系） */
export const PAL = {
  paper: "#EFE8DB", // 纸白（偏暖）
  paper2: "#E2D7C2", // 次级纸色（块面）
  ink: "#17140F", // 墨黑（主文字 / 主色块）
  ink2: "#3A342C", // 次级墨（注释 / 细线）
  red: "#CE2A1D", // 强调红（唯一的彩色，克制使用）
  rule: "#C9BFA9", // 栅格线
} as const;

/**
 * 字体 —— 中文必须写完整族名，否则会掉进 tofu（豆腐块）。
 * 探测：fc-list :lang=zh family | grep -i "noto sans cjk"
 */
export const FONT = {
  display: '"Noto Sans CJK SC Black", "Noto Sans CJK SC", sans-serif',
  body: '"Noto Sans CJK SC", "Noto Sans CJK JP", sans-serif',
  mono: '"Noto Sans Mono CJK SC", "Noto Sans Mono", monospace',
} as const;

/** 画布与栅格 */
export const CANVAS = { w: 1920, h: 1080, fps: 30 } as const;
export const GRID = 60; // 栅格步长(px)，构图对齐用
export const MARGIN = 120; // 安全边距

/** 常用尺寸 */
export const TYPE = {
  hero: 132,
  h1: 84,
  h2: 56,
  body: 34,
  caption: 24,
} as const;
