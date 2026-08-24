# 更新日志

每次代码、配置、文档、自动化脚本或部署行为更新都必须记录在这里，方便后续维护者追踪更新时间、更新内容和受影响路径。记录统一使用中文。

日期写在 `## YYYY-MM-DD` 标题中；同一天内有多条更新时，必须在日期标题下用 `### HH:MM - 更新标题` 分隔。条目正文不再重复日期和时间。

## 2026-08-25

### 04:07 - Watch 完全切换为 gpu104 本地数据源

- 更新内容：Power Database 日志来源切换为 `gpu104:/data3/kow/CM_Power_Database/runtime/logs/automation`，四个受监测项目现在全部读取 gpu104 本地目录。
- 更新内容：移除同步器的 SSH/远端回退逻辑；本地源目录缺失时直接失败，防止迁移后静默读取旧服务器数据。
- 更新内容：扫描器增加中文“成功、完成、失败、错误、异常、警告、超时、重试”等状态识别，并排除常见的零计数和“无异常”描述。
- 更新内容：发布脚本默认明确使用 gpu104 的 `python3.9`，同时允许通过 `CM_WATCH_PYTHON` 覆盖，避免定时任务因 PATH 差异选中不兼容解释器。
- 更新内容：同步更新项目说明和维护规则，明确日常运行不再依赖旧服务器。
- 验证：通过 Python 3.9 编译；中文成功、失败、未完成、超时及零错误/零警告样例通过；8 月 25 日 Power 实际日志识别为 `ok`；四项目本地同步与 14 天静态数据重建完成；本地首页和 `/api/summary` 均返回 HTTP 200，四项目均显示为 `gpu104`。
- 影响路径：`config.json`、`scanner.py`、`tools/sync_logs.py`、`tools/sync_and_publish.sh`、`README.md`、`agents.md`、`UPDATE_LOG.md`。

## 2026-08-15

### 00:31 - 适配 gpu104 部署与跨服务器日志同步

- 更新内容：复制项目到 `gpu104:/data3/kow/Carbon_Monitor_Watch`；同步工具现在会把当前主机上的数据源作为本地路径读取，并在本地路径不存在时按项目的 `server` 字段回退到 SSH 来源，避免 gpu104 SSH 回自身失败，同时让 Power Database 日志继续从 cm47 同步。
- 更新内容：补充 Python 3.9 以上版本要求以及 gpu104 的运行解释器说明。
- 验证：本地通过 Python 编译与静态数据构建；远端同步和 HTTP 服务验证完成后补充结果。
- 影响路径：`tools/sync_logs.py`、`README.md`、`UPDATE_LOG.md`，以及 gpu104 部署目录。

## 2026-07-12

### 21:49 - 补充跨服务器日志监测规则

- 更新内容：在 `agents.md` 中新增跨服务器日志监测与项目维护流程，明确后续检查 `cm47` 和 `gpu104` 相关项目日志时，需要优先查看最近几天异常信号，并在定位项目后先阅读项目级 `agents.md` / `AGENTS.md` 与 `UPDATE_LOG.md` / `update_log.md`，再检查代码、配置、数据和上下游日志。
- 更新内容：明确 `gpu104` 可使用免密码 SSH 直接检查；如相关项目发生代码、配置、文档、自动化脚本、数据处理逻辑或部署行为更新，需要同步更新该项目自己的更新日志。
- 验证：未运行代码测试，本次只改文档规则。
- 影响路径：`agents.md`、`UPDATE_LOG.md`

## 2026-06-22

### 15:22 - 规范更新日志时间格式

- 更新内容：借鉴 `/data/xuanrenSong/CM_Power_Database/UPDATE_LOG.md` 风格，统一本项目更新日志格式：日期只保留一个二级标题，同一天多条更新使用带时间的小标题分隔；同步更新 `agents.md` 的记录要求，明确新记录必须精确到分钟。
- 验证：人工检查 `UPDATE_LOG.md` 同一天记录已按 `### HH:MM - 更新标题` 分隔；未运行代码测试，本次只改文档规则。
- 影响路径：`UPDATE_LOG.md`、`agents.md`

### 15:15 - 修复 Power 日志显示不完整

- 更新内容：将静态站和本地 API 的默认日志展示窗口从 200 行提高到 1000 行，避免 Power Database 当前日志从 Turkey 附近才开始显示；重新生成 `static/data/`，让当前 Power 日志包含 Turkey 之前的 China、India、Japan、South Korea 等内容。
- 验证：通过 `python tools/build_static_data.py`；检查 `static/data/logs/power_database/abd847f178ea66f2.json` 已包含 `## China` 和 `## Turkey`。
- 影响路径：`tools/build_static_data.py`、`static/app.js`、`static/data/`、`UPDATE_LOG.md`

### 时间未记录 - 中文化项目更新记录和代理规则

- 更新内容：将 `agents.md` 和 `UPDATE_LOG.md` 的内容改为中文；明确以后这个项目的代码、配置、文档、自动化脚本和行为变更，都需要同步记录到 `UPDATE_LOG.md`；新建项目级 `agents.md` 和项目人类可读更新记录。
- 验证：未运行；本次是文档规则变更。
- 影响路径：`agents.md`、`UPDATE_LOG.md`
