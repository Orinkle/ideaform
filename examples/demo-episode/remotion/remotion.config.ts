import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);

// ⚠️ 刻意不写死 setBrowserExecutable("<绝对路径>")。
// 写死了换机器 / 清缓存就会变成死路径，渲染直接报
//   "browserExecutable was specified as ... but the path doesn't exist"
// 需要指定时走环境变量（由环境配置技能写入契约的 VW_CHROME）：
if (process.env.VW_CHROME) {
  Config.setBrowserExecutable(process.env.VW_CHROME);
}
