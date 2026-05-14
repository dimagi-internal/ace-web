import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setCodec("h264");
Config.setCrf(22);
Config.setPixelFormat("yuv420p");
Config.setConcurrency(null); // use all cores
Config.setOverwriteOutput(true);

Config.overrideWebpackConfig((current) => ({
  ...current,
  module: {
    ...current.module,
    rules: [
      ...(current.module?.rules ?? []),
      { test: /\.ya?ml$/, type: "asset/source" },
    ],
  },
}));
