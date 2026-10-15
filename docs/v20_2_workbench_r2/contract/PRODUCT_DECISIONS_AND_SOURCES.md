# R2 决策、资料与边界
核对日期：2026-10-13。以下公开资料是接入和事实核对依据，不是Owner Mac已连接、邮件已送达或产品实测成功的证据。

## 来自本次Owner的要求
- R1尚未执行，本R2替代，不组合执行。
- 注册登录后新账号项目为空；初始两栏，左侧仅新建/导入主要入口；右侧slogan和想法输入框。
- 邮箱注册、验证、登录完整流程；既有项目保留三栏工作台。
- 反思范围过大，先完成最小真实对话→Codex协作，再逐步扩展。

## 对R1的明确调整
- 删除默认dev/ldd/dashu示例数据；演示项目仅在用户主动选择“项目工作台示例”时装入。
- 增加无项目直接聊天和显式归档Project，不为首句创建假项目。
- 增加TWOS自有邮箱账号路径，与模型OAuth分离。
- 将自动路由、常驻云端和再生成子候选作为未来工作，不把它们捆绑为20.2入门子Gate。
- 保留三栏、五导航及返回、图片/文件/最小只读工具、真实交接、身份/权限/数据保护。
- 删除任何“外部ChatGPT普通对话无限免费”的默认假设。

## 官方资料
1. ChatGPT Work and Codex — desktop整合但入口/历史有区分，Work与Codex共享用量；Codex Cloud可在用户电脑休眠时继续云端任务。
   https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex
2. Using your ChatGPT plan in other apps and sites — 外部合资格请求计入Work/Codex额度；每App限制不创造新额度池；与身份授权分离。
   https://help.openai.com/en/articles/20001542-using-your-chatgpt-plan-in-other-apps-and-sites
3. About ChatGPT Pro tiers — 不同模型/套餐有用量限制，context、推理、工具及速度影响消耗；不能假定近乎无限。
   https://help.openai.com/en/articles/9793128-about-chatgpt-pro-tiers
4. Long-running work — /goal、同会话进展、pause/resume及云端长期工作；并非官方只能一次回答。
   https://learn.chatgpt.com/docs/long-running-work
5. Scheduled tasks — 本机文件任务要求电脑开启、App运行；Web事件触发与本机目录能力不同；CLI没有相同调度管理界面。
   https://learn.chatgpt.com/docs/automations
6. Plan usage overview — 开源/本机渠道及商业适用范围需核对；不授予旧ChatGPT对话和记忆读取。
   https://developers.openai.com/siwc/token-sharing-open-source
7. Preview limitations — HTTP history需显式提供；特定字段/托管工具受限，不能照搬普通API能力。
   https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
8. Codex App Server — 自定义产品的会话、事件与审批集成，以本机CLI协议为准。
   https://learn.chatgpt.com/docs/app-server
9. ChatGPT与API独立计费。
   https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform
10. Plan usage UI要求 — 实际计划使用状态与用量入口，不承诺无限。
    https://developers.openai.com/siwc/ui-ux-guidelines

## 战略判断（本次分析，不是外部事实）
TWOS小切口应是“把一件工作从讨论接到执行并返回结果”，不是重造官方App。先手工模型绑定和最小必要上下文，再以数据判断自动路由；之后增加第二供应商和可靠连续任务。邮箱验证是本次明确需求，但应复用成熟服务，不变成自建身份平台工程。

## 原型技术边界
- 无外部依赖，CSP禁止connect-src与表单外发，邮件/AI/执行均模拟。
- 演示账号与密码摘要仅当前页面内存；实际业务绝不可复用这一演示认证实现。
- 只尝试持久化语言偏好；页面重载会丢演示账号/项目，不等于正式产品持久化设计。
- 顶部“流程预览”和#home/#work是设计捷径，不能出现在生产认证通道。
- 原型通过Chromium对本地HTML字节的set_content检查。容器禁止导航，未改变此策略；未做Safari或真实TWOS安装测试。
