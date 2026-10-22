# OpenCLI 完整能力与融合入口

需要 OpenCLI 的平台能力、浏览器接口、开发或维护工具时读取对应部分。Lookup 统一触发、选路、授权和验收；OpenCLI 提供具体执行能力。只读本任务需要的指南和帮助，不把完整注册表加载进上下文。

## 完整基线

正式版 [OpenCLI v2.0.2](https://github.com/jackwener/opencli/tree/deca0fee85016be2e58836eeca974825e09c9076)，固定 commit `deca0fee85016be2e58836eeca974825e09c9076`。全部2,346个源码文件及正式 npm 包的1,579个文件分别登记在 [完整来源回执](../upstream/opencli.json)，原 [Apache-2.0 许可](../upstream/LICENSE-opencli) 保留。

完整 [能力清单](../upstream/opencli-capabilities.json) 覆盖170个站点、1,223条站点命令和66条内置命令，共1,289条公开命令，以及5套 Skill 和所有 docs／Skill 参考。清单用于完整性核验；执行时使用当前安装版本的注册表和帮助，不把基线数目当作所有后续版本或所有账号已验收。

原始源码和指南以固定来源、完整文件指纹和可恢复下载维护，首次读取时下载完整源码到 `XDG_CACHE_HOME/lookup/opencli/<commit>/source.tar.gz`，未设置时位于 `~/.cache/lookup/opencli/`。缓存前校验压缩包及全部文件，再按需输出一份原文；不解包到 Skill 自动发现目录，不执行源码，不安装 npm 包、不连接浏览器或查询业务站点。缓存损坏时保留原文件并报错，不覆盖未知内容。离线时可使用已验证缓存或已安装包的对应指南；缺少来源时如实报告。

```bash
python3 scripts/opencli-source.py fetch
python3 scripts/opencli-source.py reference skills/opencli-usage/SKILL.md
python3 scripts/opencli-source.py reference docs/guide/plugins.md
python3 scripts/opencli-source.py verify --archive /absolute/source.tar.gz
python3 scripts/opencli-source.py verify --kind package --archive /absolute/package.tgz
```

源基线与安装版本分别核对。已安装版本的执行指南优先通过以下入口读取；维护到新版后不能用旧源中的参数替代新版帮助：

```bash
node scripts/opencli-run.mjs skills list -f json
node scripts/opencli-run.mjs skills read opencli-usage -f plain
node scripts/opencli-run.mjs <site> <command> --help -f json
```

## 全部能力如何使用

| 能力 | 发现与执行入口 | 条件与完成判据 |
|---|---|---|
| 全部170个站点／1,223条动作 | `list <query> --site <site>`，再读站点与命令帮助 | 包含搜索、正文、列表、详情、下载／导出及发布等读写动作；按当前注册表核对 `access`、参数、字段、浏览器依赖及任务授权 |
| 66条内置命令 | `list <query>` 或对应命令组 `--help` | 包含下列发现、浏览器、认证、开发及维护能力；缺少 access 标记不等于只读 |
| 页面浏览器 | `browser ...`，加载 opencli-browser | 页面导航、定位、表单、点击、上传、截图、frame、等待、提取、网络、console、对话框及 session 收尾；实际接口和字段以当前帮助为准 |
| 原生 Chrome 对象 | `browser chrome describe`／`browser chrome call` | 标签、窗口、分组等方法按当前 schema 发现；只操作本任务归属对象，不以批量 API 或 profile 名称代替归属证据 |
| 认证与 Profile | `auth status/refresh --site <site>`、`profile list/use/rename` | status 与刷新分别判断；不自动登录、采 Cookie、切换账号或修改其他任务默认环境。runner 仍以 LOOKUP_OPENCLI_PROFILE 为本任务 Profile，原生默认值不覆盖它 |
| 插件管理 | `plugin list/create/install/update/uninstall` | 原生包、扩展能力和本地定制均保留；安装／卸载、全局依赖及用户配置变更按明确任务授权执行，不由查询或自动修复隐式触发 |
| Adapter 开发 | `adapter init/check/test/status/eject/reset`、`convention-audit` | 原生开发、检查、测试、导出覆盖和重置能力可用；test 会执行真实动作，reset 会移除本地覆盖，先核对对象、写入和恢复条件 |
| Adapter 故障修复 | opencli-autofix 及 trace／测试工具 | 仅在选中 OpenCLI 且有具体失败证据时加载；先定位、保留本地差异，验证修复和相邻正常路径。原指南的发 Issue 建议不构成对外发送授权 |
| Bridge 诊断与生命周期 | `doctor`、`daemon status/restart/stop` | 状态读取与停止／重启共享进程分别处理；先核对其他任务占用及授权，不以杀共享进程恢复单个动作 |
| Bridge、远端／无头、Android CDP | 原生 Bridge 与 CDP 接口及对应完整指南 | 默认保持 Bridge；显式选择的 CDP 环境使用下一节入口。不因技术失败自行换浏览器、账号或开放调试端口 |
| Skill 与 Shell 补全 | `skills list/read`、`completion <shell>` | 指南读取和输出补全脚本文本不等于安装；不把内置指南重新注册为竞争的自动入口 |
| 输出与扩展协议 | 当前命令的 `-f`、字段 schema、流式／follow 帮助 | 保留 JSON、table、YAML、Markdown、CSV、plain 和流式等实际支持格式，不强制将所有输出包装成一个业务信封；验收目标内容及文件写入范围 |

站点命令不仅限于 Lookup 原 providers.json 中列出的常用动作。完整候选都可从原生注册表发现，现有 providers 合约继续约束其已登记动作；未登记动作不自动视为不可用，也不自动取得执行授权。

```bash
node scripts/opencli-run.mjs list "<action>" --limit 25 -f json
node scripts/opencli-run.mjs list "<action>" --limit 25 --offset <nextOffset> -f json
node scripts/opencli-run.mjs <site> --help -f json
node scripts/opencli-run.mjs <site> <command> --help -f json
```

只有确认需要更多候选时沿 `nextOffset` 继续；完整性验收工具会遍历所有页，不把首100项当作全量。查询默认选择 `access: read`；发布、删除、发送、购买、上传敏感文件、安装、重置和共享状态操作依具体用户指令执行，不能仅凭“已融合全部能力”执行。

## 5套原始 Skill 的加载边界

| 来源 | 按需读取时机 | 融合处理 |
|---|---|---|
| opencli-usage | 发现命令、schema、结果与恢复 | 保留完整执行说明，选路归 Lookup |
| opencli-browser | 需要页面或原生 Chrome 操作 | 保留全部接口；浏览器选择、账号与资源归属沿用 Lookup |
| opencli-adapter-author | 新建／改进 Adapter | 完整参考覆盖 API 发现、策略、字段、输出、覆盖矩阵、站点经验及测试；只加载相关文件 |
| opencli-autofix | 已确认 Adapter 故障，需要修复 | 保留完整修复流程；对外提交、安装和真实写入仍须对应授权 |
| smart-search | 需要站点领域经验和候选来源 | 保留原始完整 Skill 与8类来源参考；其自动触发、AI 源默认顺序、固定次数和强制全表预检不另设通用规则，统一遵循 Lookup 搜索策略、有界恢复与按需发现 |

原生 `skills list/read` 当前只列出 `opencli-*`，不列 smart-search；不要据此误报它缺失。smart-search 及其他原始参考可从完整来源读取：

```bash
python3 scripts/opencli-source.py reference skills/smart-search/SKILL.md
python3 scripts/opencli-source.py reference skills/smart-search/references/sources-tech.md
node scripts/opencli-run.mjs skills read opencli-adapter-author references/api-discovery.md -f plain
```

只注册 Lookup。已存在的这5套 OpenCLI 入口由 [发现恢复](Agent-Reach融合.md#客户端发现与恢复) 保留到自动发现目录之外；同名 smart-search 必须能识别为 OpenCLI 来源，无关同名 Skill 保持原状。原始 description 和触发规则不改写，只在当前组合中关闭其独立发现。

## 显式 CDP 路线

Lookup 已选定并获准使用目标 CDP 环境时，显式设置传输模式与目标 endpoint；没有 endpoint、模式无效或 URL 不支持时，在执行前失败。默认 Bridge 收到遗留 CDP 环境变量仍拒绝执行，避免隐式换路。

```bash
LOOKUP_OPENCLI_TRANSPORT=cdp OPENCLI_CDP_ENDPOINT=http://127.0.0.1:9222 \
  node scripts/opencli-run.mjs <site> <command> ...
```

远端／无头／Android 的完整指南分别位于 `docs/advanced/cdp.md`、`docs/advanced/remote-chrome.md` 和 `docs/advanced/android-chrome.md`。设置隧道、开放端口、启动浏览器、登录或连接其他设备均不由上面的变量自动授权。不要在 endpoint 的 authority 中嵌入凭据，也不向日志回显带令牌的 URL。

`opencli-health.sh` 的就绪判据针对 Browser Bridge；不能把 CDP 不具备 extensionConnected 判据解释为该 CDP 路线不可用。CDP 按实际版本的专用帮助和目标最小动作验证，单独报告环境、账号与结果；不以 Bridge doctor 报告替代其验收。

## 更新与完整性门禁

继续复用 [既有更新流程](上游更新.md)。OpenCLI 候选在隔离 HOME 中读取完整分页注册表，核对当前1,289条公开命令及站点动作的读写属性；同时核对4套可由原生 skills 读取的完整执行指南；smart-search 保留在固定源码中。缺项、属性变化、指南缺失、重复或分页不完整时不切换。新增命令保留为额外能力，再按当前帮助判断用途和授权，不删掉它们来适配旧清单。

```bash
python3 scripts/opencli-source.py contract --binary /absolute/opencli
```

原有常用动作的参数／字段合约继续核对；两种检查共同通过仍不代表所有账号或站点实测。升级融合基线时重新获取完整发布源码和 npm 包，更新 commit、完整文件清单、校验值、全部命令与原始指南映射，再做定向与正常路径验证。第三方插件、用户覆盖和未发布 main 的能力分别核对，不混入正式基线冒充已发布能力。
