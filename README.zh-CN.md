# Tianma Work OS 1.0

**TWOS 1.0.2 / build 101.50**：Apple Silicon App 与 DMG 已完成 Developer ID 签名、Apple 公证、票据装订及 Gatekeeper 检查。[下载本版](https://github.com/loseyourself1978-blip/tianma-work-os/releases/tag/v1.0.2) · [源码、SHA-256 与验证回执](docs/release-1.0/release.json)。发布不代签 Owner 差量接受。

**R2 验证范围。** 签名候选 TWOS 1.0.2 / 101.50 已通过一次明确启动的真实 ChatGPT↔Claude 三往返：六次提交及六份对应完整回复，没有逐轮手动发送或检查。重开后保留完成状态且不重放。TXT、PNG 和简单文字层 PDF 已取得双方向内容可读证据；原生／合成边界测试另列。匹配完整主回归、新字节公证和制品 hash 见发行回执；公开发行以对应 GitHub Release 为准，工程结果不代签 Owner 接受。

[R2 操作](docs/release-1.0/BIDIRECTIONAL_R2.zh-CN.md)。此前已发布 [TWOS v1.0.1](https://github.com/loseyourself1978-blip/tianma-work-os/releases/tag/v1.0.1)；本版使用上方 v1.0.2 Release 与精确回执。


[English](README.md) · [安装](docs/release-1.0/INSTALL.zh-CN.md) · [操作指南](docs/release-1.0/USER_GUIDE.zh-CN.md) · [当前发行状态](docs/CURRENT_DELIVERY.md)

在一个 macOS 工作区中讨论目标、交接指令并执行。TWOS 将 ChatGPT、DeepSeek、Claude 官网与本机 Codex 客户端配对，把明确内容交给选定目标，再将结果带回原讨论。

- 确认任务目录，使用空文件夹或保留已有项目内容。
- 交接选定正文/附件，用 Steer 补充或可编辑 Queue 排队，查看真实工具、diff、错误和权限请求。
- 打开成果网页、查看文件、另存副本或在 Finder 定位原文件。
- 查看供应商额度窗口及独立标注的本任务用量、耗时、计划和有依据的估计。
- 使用同包内置 **夜璃 Nyra**：三服装、站姿/侧卧动画、透明舞台；只读最小任务状态，不执行或批准工作。

## 下载与首次使用

从上方链接下载 TWOS v1.0.2；打开 DMG 前核对 SHA256SUMS。匹配回执绑定源码、签名、公证和制品哈希。历史 v1.0.1 与 v1.0.0 保持不变。

打开对应 DMG，拖入应用程序并启动。登录所选供应商官网，连接已安装/登录的官方本机 Codex，再创建或接续一个绑定目录的任务。Nyra 在同一 App 内，无需第二个桌宠安装包或首次联网下载画稿；普通安装无需 Python、Node 或终端。

当前仅支持 macOS。Windows 版本开发中，尚无可下载版本。TWOS 包为 Apple Silicon，工程实测 macOS 27.0.1 / Safari 27.0.1。平台覆盖与签名状态以最终回执为准。

## 边界

TWOS 使用官方 Codex App Server 协议实现客户端，不是嵌入官方 macOS Codex 整个 GUI。各供应商网页保留自己的登录、模型、用量与条款。网页返回代码不等于本机文件已生成，落盘需要独立明确授权。不会静默切换计费 API 或自动购买。

只交接选定内容；选择目录不等于读取全部文件。Nyra 仅接收状态和不透明标识，不接收聊天、代码、账号或凭据。执行结束、业务验证和 Owner 接受分别记录。

[隐私权限](docs/release-1.0/PRIVACY_AND_PERMISSIONS.zh-CN.md) · [故障排查](docs/release-1.0/TROUBLESHOOTING.zh-CN.md) · [升级卸载](docs/release-1.0/UPGRADE_AND_UNINSTALL.zh-CN.md) · [更新说明](docs/release-1.0/RELEASE_NOTES.zh-CN.md) · [许可说明](LICENSE.zh-CN.md) · [资源与声音](ASSET_AND_VOICE_PROVENANCE.zh-CN.md)

独立桌宠见 [Nyra 仓库](https://github.com/loseyourself1978-blip/Nyra)。最终候选截图/录像可用性随媒体回执记录，不用历史截图证明新功能。

<details><summary>高级与历史资料</summary>

[详细操作指南](docs/OWNER_GUIDE.md) · [仓库地图](docs/REPOSITORY_MAP.md) · [原本机项目](docs/LEGACY_OWNER_GUIDE.md) · [高级源码安装](docs/ADVANCED_INSTALLATION.md)。旧设计和阶段记录不代表当前安装包或接受状态。

</details>
