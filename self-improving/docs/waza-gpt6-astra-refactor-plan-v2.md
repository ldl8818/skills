# Waza 面向 GPT-6 Astra 的原名精简改造方案 V2

> 审计基线：Waza v3.36.1，commit `ba60df6`
>
> 用途：历史改造方案，仅供追溯；当前独立冻结版以各 Skill 入口和冻结版本维护文档为准，不再直接作为施工指令。
>
> 核心原则：删除已经被 Astra 原生能力覆盖的技能，保留原有英文技能名，重写触发边界和规则，不用改名制造伪升级。

## 0. 已确定的产品决策

以下决定不再由实施 Agent 重新讨论：

1. 完整删除 `think`、`learn`、`read`。
2. 不创建 `decide`、`research`、`source`、`voice` 或任何兼容别名。
3. 保留并继续使用原名：`ui`、`check`、`hunt`、`write`、`health`。
4. 不创建 `ui-review`、`release-check`、`incident`、`agent-health`、`voice-tw93` 等新技能。
5. 不在 Waza 中新增抓取器或工具适配器。URL、PDF、来源获取由宿主原生能力或现有 `lookup` 负责。
6. Waza 不依赖 `lookup`，也不修改 `lookup`。二者保持独立，避免耦合。
7. 删除技能时不保留禁用占位、转发壳、弃用 alias 或隐藏路由。旧名字不应继续占据模型路由上下文。
8. 只修改源码和生成器。`plugins/waza/**` 等生成产物不得手工编辑，最后统一重新生成。
9. 本轮不提交、不推送、不发布、不创建 release，除非用户在当前执行会话中另行明确授权。

目标技能集合必须精确等于：

```text
check
health
hunt
ui
write
```

## 1. 对上一版方案的取舍

上一版判断对了一半。

应该继承：

- `ui` 不再教模型什么才叫好设计，重点转向项目上下文和真实渲染验证。
- `hunt` 保留根因纪律，但允许日志、探针和隔离实验。
- `check` 增加与影响范围成比例的验证预算。
- `health` 增加 Astra 指令兼容性审计。
- Skill 只提供边界、证据、完成条件和模型不知道的领域事实，不再规定冗长固定步骤。

不采纳：

- `think → decide`
- `learn → research`
- `read → source`
- `write → voice`
- 新增任何 fallback adapter

原因很简单：重命名没有删除重复能力，只是给旧流程换了牌子。技能名属于用户已经形成习惯的接口。真正需要修的是触发范围和内部契约，不是英文单词。

## 2. Astra 版的职责边界

| Skill | 唯一职责 | 不再负责 |
|---|---|---|
| `ui` | 编码界面的创建、视觉修改和真实渲染验证 | 文档排版、独立图片生成、抽象设计哲学、运行时故障排查 |
| `check` | 代码审查、明确的项目审计、PR/issue triage、合并与发布前验收 | 方案设计、功能实施、具体故障根因、写作文风 |
| `hunt` | 有可观察症状的软件故障诊断与修复验证 | 泛化代码审查、纯审美修改、新功能设计 |
| `write` | 明确要求的写作、改稿、校对和本地化 | 研究、抓取、发布执行、实现任务里的顺手改文案 |
| `health` | Agent 指令、配置、skills、hooks、MCP、权限与验证器健康 | 应用代码 bug、普通 PR review、通用代码质量评分 |

默认一次最多选择一个 Waza Skill。只有用户请求本身确实包含两个独立结果时，才可按结果顺序组合；不能因为关键词同时出现就自动串联。

## 3. 第一阶段：完整删除三个技能

### 3.1 删除源码

删除以下完整目录：

```text
skills/think/
skills/learn/
skills/read/
```

其中包括：

- `think` 的 evaluation、triage 和 durable-context references。
- `learn` 的六阶段研究工作流。
- `read` 的入口、read-methods、`fetch.sh`、`fetch_local.py`、飞书与微信抓取脚本。

不要把其中内容迁移成新技能。只有真正属于其余五个技能且不可替代的安全规则，才允许压缩后进入对应 Skill；迁移前必须指出原路径和保留理由。

### 3.2 删除专属测试

删除只服务于 `read` 抓取能力的测试：

```text
tests/test_read-fetch.sh
tests/python/test_fetchers.py
```

同时从 `tests/python/test_trusted_helper_resolution.py` 等共享测试中删除 `read` 专属用例。删除或改写只验证 `think`、`learn`、`read` 文案存在的断言。不要为了让旧测试继续通过而保留空目录或兼容文本。

### 3.3 清理全部注册面

从以下源码和手工维护文档中移除三个技能：

- `README.md`
- `llms.txt`
- `skills/RESOLVER.md`
- `scripts/dispatcher-template.md`
- `scripts/build_metadata.py`
- `AGENTS.md`
- `assets/waza_skills.svg`
- `package.json` 的手工关键词或说明源，如相应字段不是生成字段
- `.claude-plugin`、`.agents`、Codex plugin 的生成逻辑
- 安装、打包、codegen、validator 和 E2E 测试中的八技能断言

必须删除这些旧工作流描述：

- URL 出现就先走 `read`
- `read → learn → write`
- `think → 等待批准 → 实施 → check`
- eight skills、all eight skills、八个技能等固定数量描述

历史 changelog 可以保留旧版本事实，但当前 README、manifest、dispatcher 和安装说明不得继续宣传已删除技能。

## 4. 第二阶段：重写五个保留技能

所有保留技能遵守同一结构：

1. 一句窄范围 `description`。
2. 明确 `Use when` 和 `Not for`。
3. Outcome、边界、证据、完成条件。
4. 只保留 3 至 7 条模型无法安全自行推断的规则。
5. 复杂细节放入条件加载的 reference。
6. 确定性行为留在 script，不把脚本逻辑复制成提示词。
7. 删除固定阶段、固定次数、固定 Agent 数量和无依据的数值阈值。
8. 删除强制首行 `🥷` 和所有输出标记要求。
9. 删除与任务无关的标点、措辞和格式世界观。
10. 安全且可逆的工作应持续完成，只有真实缺权、不可逆动作或缺少用户独有信息时才停。

入口文件建议控制在 40 至 90 行。`check` 因承担多个内部 mode 可以稍长，但根入口必须是路由器，不能重新堆成总手册。

### 4.1 `ui`

建议 frontmatter：

```yaml
name: ui
description: "Builds or visually polishes coded web and native interfaces using project context and rendered evidence. Use when the user asks to create or change a page, component, layout, typography, or screenshot-grounded visual detail. Not for backend work, document typesetting, standalone image generation, or runtime regressions."
when_to_use: "设计页面, 修改界面, UI组件, 界面不好看, 截图视觉问题, build this page, polish this component, match this UI screenshot, fix visual hierarchy, interface typography"
dispatch_intent: "Create or visually refine a coded product interface and verify the rendered result"
```

触发要求：

- 用户明确要创建或修改真实产品界面。
- 用户给出截图并表达视觉、层级、排版、对齐、颜色或一致性问题。
- 裸 `screenshot`、裸 `style`、裸 `design`、裸 `排版` 不作为独立触发词。

明确排除：

- UI 点击失效、崩溃、状态错误、升级后回归，交给 `hunt`。
- PDF、PPT、Word、打印物排版，交给宿主对应能力。
- 独立插画、照片、纹理和图片编辑，交给宿主图片能力。
- 后端逻辑和数据管道。

必须保留：

- 先检查现有 design tokens、同类组件和项目约定。
- 成熟产品优先复用现有视觉语言，不自创第二套系统。
- 对照用户参考图或当前页面验证关键视觉差异。
- 在真实 render 中检查，不用编译通过代替视觉验证。
- 按任务影响检查相关 viewport、响应式和无障碍。

必须删除或降级为非强制启发：

- 强制五维 direction lock。
- 必须命名视觉哲学。
- 必须存在 design signature。
- 必须设计 signature micro-interaction。
- 所有可点击元素必须 `scale(0.96)`。
- 对字体、颜色模型、渐变、玻璃效果、卡片和技术组合的绝对禁令。
- 写代码前必须再次获得批准。
- 输出禁用 em dash 等与 UI 任务无关的语言规则。

文件处理：

- 删除 `skills/ui/references/mode-generated-asset.md`。
- 精简 `design-reference.md`，只留项目上下文、层级、密度、排版和一致性判断。
- 保留并瘦身 screenshot iteration、quick fix、native motion、data visualization references，只有命中具体任务时才加载。
- 同步重写 `tests/python/test_ui_behavior_contracts.py` 和相关 shell contract，不再断言旧的五维锁与 always-on bans。

完成标准：实际界面已实现或问题已明确定位，并对相关真实渲染、viewport 和无障碍风险给出本轮证据。

### 4.2 `check`

建议 frontmatter：

```yaml
name: check
description: "Reviews code changes, repository quality, and release readiness using current evidence and risk-proportional verification. Use when the user explicitly asks for code review, project audit, PR or issue triage, merge readiness, or release follow-through. Not for debugging a concrete failure, writing prose, or implementing a plan."
when_to_use: "代码审查, review this diff, PR review, 合并前检查, 发布前检查, 项目代码审计, issue triage, release readiness"
dispatch_intent: "Review code or repository evidence and verify an explicitly requested merge, triage, or release outcome"
```

触发要求：

- 必须存在明确的 review、audit、triage、merge 或 release 意图。
- 仅出现 `看看`、`检查一下`、`优化`、`继续` 不得自动触发。
- 普通实现完成后不自动附加 `check`，除非用户、项目规则或当前任务完成条件明确要求。

内部仍保留原有 mode，不拆成新技能：

- diff / PR review
- project audit
- issue / PR triage
- ship / release readiness

必须保留：

- 只读请求不得变成写入授权。
- 保护 staged、unstaged、untracked 和用户已有修改。
- finding 必须有当前证据，并说明影响和修复方向。
- clean review 是合法结果，不能为了显得有用而制造问题。
- 源码、生成物、包、registry、release asset 等状态分层报告。
- commit、push、publish、回复、关闭 issue 等公开动作需要当前任务明确授权。

必须修改：

- 删除 Plan Execution Mode。实施明确方案属于 Astra 原生执行，不属于 `check`。
- 删除按 diff 行数决定 reviewer 数量的规则。
- 删除固定 Standard、Deep fan-out 和四个 adversarial Agent 编排。
- 删除固定置信度阈值、固定 14 项签收和 Linus/persona 式评分表演。
- 删除 release reaction、发布表情等仪式性要求。
- 项目 audit 可以保留，但取消机械分数，改成按证据排序的问题与风险。

引入 Verification Budget：

- 文档、注释、局部低风险改动，只做相关静态检查。
- 单模块逻辑改动，运行目标测试和必要构建。
- 公共 API、数据迁移、权限、支付、发布链路，扩大到集成、回归和产物验证。
- 只有前一层出现失败、新改动或未解决风险时才继续扩大检查。
- 通过必要检查后停止，不重复运行同类测试证明同一件事。

文件处理：

- 保留 `mode-ship.md`、`mode-triage.md`、`mode-audit.md` 作为 `check` 内部条件 reference，并按上述边界重写。
- 删除 `skills/check/references/persona-catalog.md` 及两个 reviewer persona prompt；将仍有价值的安全和架构检查点压缩进 `review-patterns.md`，按 diff 风险加载。
- 保留 `release-surfaces.md`、`review-patterns.md`、`release_gate.py`、`audit_signals.py`。
- 将 `run-tests.sh` 改为默认只发现候选验证命令，不自行调用可能联网的 `npx`，实际执行依据项目文档、锁文件、CI 和用户授权。
- `check/references/public-reply.md` 作为公开 maintainer action 的唯一规则来源；删除 `write` 中重复版本。

完成标准：请求范围已覆盖，finding 和验证均有本轮证据，授权内的目标状态已完成；不存在用测试数量冒充质量的行为。

### 4.3 `hunt`

建议 frontmatter：

```yaml
name: hunt
description: "Diagnoses and fixes observable software failures through reproduction, evidence, and targeted verification. Use when the user reports an error, crash, failing test, regression, performance problem, or broken runtime behavior. Not for general code review, aesthetic preference, or new feature design."
when_to_use: "报错, 崩溃, 测试失败, 运行异常, 回归, 卡顿, fix this bug, failing test, regression, crash, not working"
dispatch_intent: "Diagnose an observable software failure, establish its cause, and verify the authorized fix"
```

触发要求：

- 必须有具体症状、失败信号、回归、性能异常或可观察的错误行为。
- 用户只是觉得界面不好看，走 `ui`。
- 用户只是想 review 代码，走 `check`。
- 用户只是要实现新功能，不触发 Waza。

必须保留：

- 先建立可复现路径或最接近的可验证信号。
- 用证据排除假设，而不是连续猜补丁。
- 正式修复指向根因，不扩大到未失败的相邻逻辑。
- 回归风险决定验证范围。
- 缓存、队列、IME、Unicode、native freeze、rendering 等真实故障经验按条件加载。

必须修改：

- 将 Do not touch code before root cause 改成在有根因证据前不得提交 production behavior fix。
- 明确允许临时日志、断言、探针、最小测试和隔离实验。
- 三次假设失败后重新建立问题模型并继续调查，不机械停下询问。
- 只有缺少用户独有信息、权限、设备或不可替代输入时才停。
- 不强制 stash、revert 或改动用户工作树来证明 red/green。
- 不要求每个 bug 都新增永久测试。按复发概率和影响选择回归保护。
- 删除三轮、三个假设、文件数量等无事实依据的硬阈值。

完成标准：根因有证据，授权范围内的修复已经验证；若无法完成，则明确缺失证据、已排除项和唯一真实阻塞点。

### 4.4 `write`

建议 frontmatter：

```yaml
name: write
description: "Drafts, rewrites, or reviews user-facing prose while preserving intent, facts, and the author's voice. Use when the user explicitly asks to write, edit, proofread, localize, or polish prose. Not for code comments, research, release execution, or incidental text inside an implementation task."
when_to_use: "写文案, 改稿, 润色, 校对, 去AI味, 本地化文案, release notes文案, draft this, rewrite this, proofread, localize this"
dispatch_intent: "Draft or edit user-facing prose while preserving intent, evidence, and the author's natural voice"
```

触发要求：

- 必须有明确的写、改、润色、校对、本地化或文案审阅意图。
- 代码任务中偶然出现 README、label、按钮文案或注释，不得因此抢占整个任务。
- release notes 的文字生成可以使用 `write`；发布状态、产物和执行动作由 `check` 负责。

必须保留：

- 不编造事实、引用、经历、用户观点和产品状态。
- 保留原意和作者真实表达，能不改的句子不改。
- 修改强度服从受众、载体和用户要求。
- 对外事实应来自当前材料或可验证产品状态。
- 中文、英文、双语和本地化 reference 只在对应任务中加载。

必须删除或降级：

- 长篇 AI 味词典作为硬规则。
- em dash、分号、括号数量、句长、排比数量、粗体数量等绝对门禁。
- 机械替换表和固定禁词。
- 每次输出都必须运行 punctuation lint。
- 为了显得自然而新增个人经历、情绪或口头禅。
- 与 `check` 重复的 public reply 工作流。

文件处理：

- 将 `write-zh.md` 从百科式禁令压缩成少量原则和对比例子，删除任意数字阈值。
- 保留 `write-en.md`、双语、本地化、long-form 和 release-notes references，但全部改成条件加载。
- 删除 `skills/write/references/mode-public-reply.md`，以 `check/references/public-reply.md` 为 maintainer action 的唯一来源。
- 保留 punctuation script，但只在用户明确要求排版检查、项目规则要求或任务确实涉及 CJK/Latin 标点一致性时运行。

完成标准：交付的是用户要的最终文本或文件修改，含义和事实未被擅自改变；除非用户要求，不附加修改说明和自我表演。

### 4.5 `health`

建议 frontmatter：

```yaml
name: health
description: "Audits AI-agent instructions, configuration, skills, hooks, MCP, permissions, and verifier health using redacted evidence. Use when the user explicitly asks to audit or diagnose Codex, Claude, Pi, or agent-tooling behavior. Not for application bugs, PR review, general code quality, or routine instruction-file edits."
when_to_use: "审计Codex配置, Claude不听指令, hook没触发, MCP配置异常, skill冲突, agent health, instruction audit, verifier coverage audit"
dispatch_intent: "Audit an AI-agent configuration or instruction problem using bounded, redacted, and evidence-backed checks"
```

触发要求：

- 必须同时存在 Agent/工具配置对象和审计、异常、漂移、不生效、冲突等问题意图。
- 裸 `AGENTS.md`、`config.toml`、`维护性`、`上下文` 不得独立触发。
- 普通编辑 Agent 指令文件不自动变成全量 health audit。

必须保留：

- report-only 授权边界。
- summary first、证据和风险校准。
- 敏感值脱敏，绝不输出 token、密钥和完整私有配置。
- skills、hooks、MCP、权限和供应链的确定性检查。
- 文档引用、验证器空跑和指令可达性的检查。

必须收窄：

- 从默认职责中删除通用代码质量、hotspot ownership 和泛化 maintainability 评分，它们属于 `check`。
- 默认 summary 不读取历史会话，不扫描无关全局目录，不调用 MCP 工具。
- 历史会话扫描必须由用户明确要求，并使用显式 flag。
- 全局配置扫描、MCP live probe、deep 模式和 inspector Agent 都必须单独升级，且先说明范围。
- 不因用户说完整、深入之外的普通关键词自动进入 deep。
- 不根据记忆中的旧偏好自动扩大扫描范围。

在 `health` 内增加 Astra Compatibility 检查，不创建新 Skill。只检查：

- Skill 与 `AGENTS.md` 是否冲突。
- Skill 之间是否争夺同一意图。
- 是否存在不必要的 approval gate。
- 是否存在过度 stop condition。
- 是否重复要求验证同一件事。
- 是否用固定规则压制合理并行。
- 是否保留针对旧模型弱点的过时假设。
- 是否存在互相冲突的输出格式和文风要求。
- 根入口是否加载了当前任务不需要的长 reference。

文件处理：

- 删除通用 maintainability inspector、reference 和专属脚本；其中与 Agent 指令可达性或 verifier 真实性直接相关的检查可压缩迁入现有 context/control 检查。
- `conversation_audit.py` 如保留，必须改为显式 opt-in，不得由默认 summary 调用。
- `collect-data.sh` 默认只收集当前项目、非敏感、静态摘要。复杂解析逐步移入可测试的 Python 模块，shell 只做编排。
- MCP live check 增加显式参数，默认关闭。

完成标准：报告只覆盖用户授权的 Agent 健康范围，每条 finding 都有脱敏证据和可执行动作，没有通过扩大隐私范围来换取表面完整度。

## 5. 第三阶段：清理共享规则与路由

### 5.1 删除运行时噪声

删除：

```text
rules/chinese.md
rules/english.md
rules/waza-routing.md
rules/durable-context.md
```

同时删除五个 Skill 中复制的 `references/durable-context.md` 和对应 Preflight。

同步删除这些规则的专属安装测试：

```text
tests/test_routing-installer.sh
tests/test_chinese-installer.sh
tests/test_english-coaching-installer.sh
tests/test_durable-context-installer.sh
```

从 `scripts/build_metadata.py`、`scripts/checks_distribution.py` 和相关测试中移除共享 durable-context 复制、必需规则集合及生成镜像断言。

理由：

- 语言偏好应由 `write` 或用户当前要求决定，不应污染所有工程任务。
- 路由应以 Skill frontmatter 为准，不能再维护第四份关键词表。
- Astra 宿主已有自己的上下文和权限机制，Skill 不应默认读取记忆或历史。

`rules/anti-patterns.md` 不再承担通用 Codex 行为手册。将它压缩到只剩 Waza 项目独有的源码/生成物、打包、发布和秘密保护规则；这些规则如果只影响仓库维护，应移入 `AGENTS.md`，而不是随插件注入所有用户任务。

### 5.2 建立单一触发真相

- `skills/*/SKILL.md` 的 `description` 是模型路由的唯一语义真相。
- `when_to_use` 只保留少量真实用户表达，不放裸名词和关键词海。
- `dispatch_intent` 只服务 bundle dispatcher，内容必须来自同一技能边界。
- `skills/RESOLVER.md` 是给维护者看的简短索引，不再包含完整工作流、链式调用和十一条歧义规则。
- `scripts/dispatcher.md` 继续由 `scripts/dispatcher-template.md` 和 frontmatter 生成。
- 删除命中两个技能就全文读取两个再判断的规则。先按 description 选最具体的一个；真正无法判断且会实质改变结果时才提问。

建议保留的核心消歧只有：

| 输入 | 路由 |
|---|---|
| 界面不好看、对齐或层级不对 | `ui` |
| 界面点击失效、崩溃、状态错、升级后坏了 | `hunt` |
| 代码或 PR 是否可合并、项目代码质量审计 | `check` |
| 明确要求写、改、润色、本地化 | `write` |
| Codex/Claude/skills/hooks/MCP/权限不生效或冲突 | `health` |
| URL 阅读、资料研究、方案规划、普通功能实现 | 不触发 Waza，使用宿主原生能力 |

## 6. 第四阶段：缩短 `AGENTS.md` 与修复打包

### 6.1 `AGENTS.md`

只保留：

- 仓库源码与生成物边界。
- 不手改 `plugins/waza/**`。
- 关键开发、生成和验证命令。
- 删除技能时需要同步的分发表面。
- 工作树与发布安全边界。
- 测试范围与改动风险相匹配。

移出或删除：

- 八技能哲学和固定数量上限。
- 每个技能都要重复的通用 Agent 教程。
- 详细 release 文案模板和发布表情要求。
- 无条件运行全套测试。
- 与系统级 Codex 规则重复的安全说明。

### 6.2 Claude Desktop bundle

重写 `scripts/package-skill.sh` 和 `scripts/validate_package.py`：

- 根 `SKILL.md` 只保留简短 dispatcher。
- 五个技能正文以普通 playbook/reference 文件随包分发，命中后只读取一个。
- 如果发行格式要求只能有一个 `SKILL.md`，保留根入口即可，子技能正文改成非入口 Markdown 文件。
- 不再把五份完整正文串接进根入口。
- validator 必须验证 root dispatcher 的每个目标文件存在、链接正确、无路径逃逸。

Codex plugin 和直接安装仍使用五个原名 `skills/<name>/SKILL.md`，无需引入新命名。

## 7. 测试与行为评测

### 7.1 更新确定性测试

同步修改：

- `scripts/checks_content.py`
- `scripts/checks_distribution.py`
- `scripts/checks_routing.py`
- `scripts/skill_frontmatter.py`
- `scripts/validate_package.py`
- `tests/test_behavior_contracts.sh`
- `tests/test_codegen.sh`
- `tests/test_package.sh`
- `tests/test_skills-add-e2e.sh`
- `tests/test_validators.sh`
- `tests/python/test_trusted_helper_resolution.py`
- 所有断言八技能集合、旧路由、`🥷`、durable-context 和已删除文件存在的测试

不要把旧文案断言换成另一批长文案断言。测试应该验证边界和产物：

- 注册集合精确等于五个技能。
- 删除项不存在。
- 所有引用可解析。
- 源码和生成镜像一致。
- bundle 根入口没有内联全部技能正文。
- 高风险脚本默认只读或显式 opt-in。
- description 同时包含窄触发与明确排除。

### 7.2 增加路由评测集

新增一份小型路由评测集，至少覆盖中英文正例、hard negative 和边界组合。

必须包含以下案例：

| 用户意图 | 期望 |
|---|---|
| 看这个 GitHub URL，告诉我项目做什么 | 不触发 Waza |
| 为新功能给一个技术方案并直接实现 | 不触发 Waza |
| 深入研究这个行业并给出处 | 不触发 Waza |
| 帮我做一个设置页面 | `ui` |
| 这个页面层级很乱，按截图改好 | `ui` |
| 升级后按钮点击崩溃 | `hunt` |
| 这个测试以前通过，现在失败 | `hunt` |
| review 当前 diff 是否能合并 | `check` |
| 审计整个仓库的代码质量 | `check` |
| 润色这段中文，不改变意思 | `write` |
| 写一版 release notes 文案 | `write` |
| Codex 忽略 AGENTS.md 里的规则 | `health` |
| MCP 配好了但 Agent 看不到工具 | `health` |
| 请修改 AGENTS.md 加一条命令 | 不自动触发 `health` |
| 截图里按钮难看 | `ui` |
| 截图显示按钮点了没反应 | `hunt` |

建议对裸 Astra、旧 Skill、精简 Skill 做盲测。记录：

- 是否选对技能。
- 是否读取无关 reference。
- 是否出现不必要请示。
- 是否过度测试。
- 是否完成用户要求。
- 输入 token、工具调用和耗时是否明显增加。

保留规则的标准不是看起来专业，而是相对裸 Astra 能提高成功率，或稳定避免一个具体高风险错误。

## 8. 实施顺序

按以下顺序执行，不要把删除、重写、生成和发布混在一起：

1. 检查工作树，记录现有修改，避免覆盖用户内容。
2. 建立删除前引用清单。
3. 删除 `think`、`learn`、`read` 源目录及专属测试。
4. 更新 README、resolver、dispatcher template、metadata generator 和当前技能集合。
5. 重写 `ui`、`check`、`hunt`、`write`、`health`。
6. 删除或压缩共享 rules，移除 `🥷`。
7. 修复 bundle 渐进披露。
8. 更新测试和路由评测集。
9. 运行 `make regenerate`，让生成器重建 plugin mirror 和 metadata。
10. 运行验证命令并修复真实失败。
11. 检查 diff，确认没有新技能名、adapter 或兼容壳。
12. 只报告结果，不执行 commit、push、publish 或 release。

建议验证命令：

```bash
git status --short --branch -uall
make regenerate
python3 scripts/verify_skills.py --root .
make test
make package
git diff --check
```

解包后还要验证：

- 技能集合精确等于 `check health hunt ui write`。
- 根 dispatcher 只负责路由，没有五份正文内联。
- 不包含 `skills/think`、`skills/learn`、`skills/read`。
- 不包含 `decide`、`research`、`source`、`voice` 等替代技能。
- 不包含 read 抓取脚本或新增 adapter。
- plugin mirror 与源码逐字一致。

## 9. 完成验收

满足以下条件才算本次重构完成：

- [ ] 源码只剩五个目标 Skill。
- [ ] 五个 Skill 名称保持 `ui/check/hunt/write/health` 不变。
- [ ] 三个删除 Skill 没有 alias、占位或自动迁移壳。
- [ ] 没有引入任何新 Skill 或工具适配器。
- [ ] URL、PDF、研究和通用规划不再被 Waza 抢占。
- [ ] 五个 description 都是意图式窄触发，不依赖裸关键词。
- [ ] `ui` 不再强制审美人格和固定设计动作。
- [ ] `hunt` 允许诊断实验，但正式修复仍需要根因证据。
- [ ] `check` 使用风险成比例的验证预算，不机械拉 Agent 或跑全套。
- [ ] `write` 保留作者表达和事实边界，不再用长禁词表塑造统一文风。
- [ ] `health` 默认不读取历史会话、不扫无关全局目录、不 live call MCP。
- [ ] 所有 `🥷` 输出要求及对应 validator 已移除。
- [ ] bundle 已恢复渐进披露。
- [ ] 生成物、manifest、文档、示意图和测试全部同步。
- [ ] 完整测试与打包验证通过。
- [ ] 未发生未经授权的 commit、push、publish 或 release。

## 10. 发布建议

删除三个公开 Skill 属于破坏性变更，应在未来发布时使用 major version，并在迁移说明中直接写清楚：

- `think` 删除，规划与决策交给模型原生能力。
- `learn` 删除，研究交给宿主原生能力。
- `read` 删除，来源获取交给宿主能力或用户已有工具。
- `ui`、`check`、`hunt`、`write`、`health` 保持原名，但触发更窄、规则更短。

旧 tag 就是回滚方案，不需要为了兼容继续把旧技能装进新版本。

## 11. 最终定位

Waza Astra 版不再负责教模型如何思考。

它只负责五件事：界面结果可见、审查证据可靠、故障根因成立、文字忠于作者、Agent 环境没有互相打架。

模型负责能力，Waza 负责边界和验收。

参考：

- [GPT-6 Astra 模型指南](https://developers.openai.com/api/docs/guides/latest-model)
- [Rethinking skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)
- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Waza v3.36.1](https://github.com/tw93/Waza/tree/ba60df6efd4ff9a8332e939c6027f156440d2eb8)
