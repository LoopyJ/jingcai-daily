---
name: jingcai-daily
description: >
  每日竞彩足球批量分析、赔率刷新和批量复盘工作流。用户要求分析今天、明天或指定日期的全部/多场竞彩，
  刷新当日赔率、临场复测，或复盘一批竞彩场次时使用。按中国竞彩业务日（Asia/Shanghai 当日11:00
  至次日11:00）获取并核验尚未开赛场次，逐场调用 soccer-predict，生成日期目录下的单场报告、
  结构化结果、汇总报告和幂等历史归档。单场比赛、单个 match ID 或单场盘口问题优先使用 soccer-predict。
---

# 竞彩日分析工作流

把一批比赛作为一个可核验、可重跑、失败后可恢复的任务处理：先冻结比赛集合，再逐场分析，最后由主 agent
统一校验、发布、汇总和归档。不要因单场抓取失败虚构结论，也不要把已开赛场次包装成赛前预测。

## 开始前

1. 完整读取项目级 `$soccer-predict` 及其当前任务需要的参考文档，把它作为单场分析引擎。
2. 读取 [references/result-contract.md](references/result-contract.md)，按其中的字段和状态契约生成结果。
3. 从当前工作区定位 `soccer-prediction-journal/`；所有报告和历史只写入该仓库，不写入 skill 目录。

## 业务日与运行参数

- 使用 `Asia/Shanghai`。用户指定日期时将该日期记为 `{business_date}`；未指定时使用当前系统日期。
- 竞彩业务窗口不是自然日。定义：
  - `{business_start}` = `{business_date} 11:00:00+08:00`
  - `{business_end}` = `{business_date + 1 day} 11:00:00+08:00`
  - 仅当 `{business_start} <= kickoff_time < {business_end}` 时，比赛才属于该业务日。
- 将执行开始时间记为 `{now}`，运行标识记为 `{run_id}`，格式建议为 `YYYYMMDDTHHMMSS+0800`。
- `kickoff_time` 必须保存为含完整年月日和 `+08:00` 偏移的时间；不要只保存网页上的月日或时分。
- “销售截止/已截止”不等于已开赛。赛前资格由实际开球时间和比赛状态共同决定。
- 用户明确说“全部”“所有比赛”时，核验后的候选清单可视为已确认；只说“看看今天竞彩”或范围不明确时，先展示清单并等待确认。
- 单场请求、单个 match ID 和单场盘口问题交给 `$soccer-predict`；本技能只负责编排多场任务。
- 报告只返回可点击的本地文件链接，不自动打开浏览器或文件。

## Step 1：获取、标准化并冻结比赛清单

### 数据入口

首选：

`https://aiplus.titan007.com/ai/pc/spf`

首选页不可访问，或虽然打开但无法提取可靠的比赛 ID、开球时间、状态和赔率时，再使用：

`https://cp.titan007.com/buy/JingCai.aspx`

按以下页面契约读取，避免把展示字段误当成真实数据：

- AI 预测页按“当日 11:00 至次日 11:00”分组；当前页面通常可从 `schedule_<match_id>` 行标识提取比赛 ID。
- AI 预测页的 `-` 通常表示未开赛；比分、比赛分钟或“上/中/下”等状态表示已经开始。状态文案变化时同时核对比分和实际开球时间，不只依赖单个符号。
- 备用竞彩页可能默认展示“截止”时间。必须切换或读取“开赛”时间，或者用比赛详情页核验；绝不能把销售截止时间写入 `kickoff_time`。
- 备用页可从亚盘、欧赔或比赛详情链接中的数字 ID 交叉核验 match ID。

### 标准化与筛选

1. 提取竞彩编号、match ID、联赛、主队、客队、实际开球时间、比赛状态、胜平负和让球赔率、来源 URL 与采集时间。
2. 只将业务窗口内、`kickoff_time > now`、且状态明确为未开赛的记录列为候选。
3. 已开赛、完场、取消或明确延期的记录进入排除清单；销售截止但尚未开赛的记录仍可分析，并标注销售状态。
4. 状态或开球时间无法可靠核验的记录列为 `waiting_verification`，不进入正式分析。
5. 按 `business_date + match_id` 去重；重复记录合并时保留来源列表，并优先采用时间更新、字段更完整且可交叉核验的值。
6. match ID 必须为数字，主客队和完整开球时间必须存在；关键字段缺失的记录进入异常清单。
7. 没有候选场次时，报告业务窗口、数据源、筛选统计和排除原因后停止；不要拿其他业务日补齐。

创建运行目录：

`soccer-prediction-journal/reports/{business_date}/runs/{run_id}/`

在逐场分析前写入初始 `run-manifest.json`，冻结候选 match ID 和排除清单。之后页面新增或变化的比赛不静默加入本次运行；需要加入时创建新运行。

向用户展示候选清单，至少包含：竞彩编号、match ID、完整开球时间、联赛、对阵、胜平负赔率、让球赔率、状态、来源和采集时间。
同时给出原始数、去重后数量、候选数、待核验数和各类排除数量。

## Step 2：缓存判定与逐场分析

### 固定产物路径

使用 match ID 作为唯一稳定文件名，不使用可能随队名变化的 slug：

- 正式 HTML：`reports/{business_date}/match-{match_id}.html`
- 正式 JSON：`reports/{business_date}/match-{match_id}.json`
- 本次尝试 HTML：`reports/{business_date}/runs/{run_id}/match-{match_id}.html`
- 本次尝试 JSON：`reports/{business_date}/runs/{run_id}/match-{match_id}.json`

### 普通运行与刷新

- 普通运行只有在正式 HTML 存在、正式 JSON 的 `analysis_status` 为 `success`、业务日和 match ID 匹配，并且历史条目完整时才复用。复用结果保持 `analysis_status=success`，设置 `run_action=reused`。
- 任一正式产物缺失、JSON 无法解析、状态不是 `success`、路径不合规或历史条目不完整时，重新分析并设置 `run_action=generated`。
- 用户要求刷新赔率、重新分析或临场复测时设置 `run_action=refreshed`，始终重新采集；旧正式产物在新尝试通过校验前保持不变。
- `skipped` 不是分析状态。分析质量使用 `analysis_status`，本次运行的动作使用 manifest 中的 `run_action`；正式 JSON 用 `artifact_action` 记录产物最初由生成还是刷新产生。

### 执行方式与批量模式契约

- 没有多智能体能力时，在当前任务内逐场执行同一分析单元。
- 有多智能体能力时，先读取当前可用的并发槽位，再按“每场一个分析单元、超出槽位时均衡分组”的策略派发；每个单元只写自己的运行目录文件，不写任何共享文件。
- 不要用 `create_thread` 创建用户可见任务，除非用户明确要求独立任务。

### 比赛场次分配策略

主 agent 先完成候选冻结、缓存判定和运行目录初始化，再把仍需分析的 match ID 分配给当前可用的子智能体。分配不是按固定的“一个子智能体只能分析一场”处理，而是按槽位和候选数动态均衡：

1. 设待分析场次数为 N，当前可用子智能体数为 W。实际并发数为 min(N, W)；不得超过运行环境报告的槽位上限，也不得为了凑并发重复创建线程。
2. 当 N <= W 时，每个子智能体负责一场；当 N > W 时，将场次按稳定顺序轮转或均衡分组，使每个子智能体负责的场次数相差不超过 1。实际分组始终以当前已上线且可用的子智能体数量为准。
3. 分组时优先保持每个子任务的比赛数量均衡，同时把相同联赛或相近开球时间放在同一组仅作为可选优化；不能因为分组方便而改变候选集合、跳过比赛或把已开赛场次加入任务。
4. 每个分配消息必须列出该子智能体负责的全部 match ID、竞彩编号、开球时间、主客队、business_date、run_id 和每场固定尝试路径。子智能体必须逐场处理自己的整个分组，不能只抓取盘口后提前结束。
5. 子智能体的完成条件是“每场走完完整五步预测并提交结果”：包括基本面、伤停/首发状态、欧赔、亚盘、大小球、模型概率、胜平负、竞彩让球胜平负、预测比分、EV/价值判断、冷门与失效条件，以及该场 JSON 和完整 HTML。只有完成这些步骤后，才向主 agent 返回最终摘要。
6. 子智能体可以并行抓取不同比赛，但不能并行写同一场的 JSON/HTML，也不能修改 run-manifest.json、daily-summary.html、历史、联赛资料或预测框架。每个 match ID 在运行目录中只能有一份结果。
7. 主 agent 应维护一个内部分配表，记录 match_id -> worker -> status，并在回收结果后检查每场是否有最终产物。某个子智能体中断时，只把未完成的 match ID 重新分配给空闲槽位；不要让两个子智能体同时重写同一场。
8. 不要为了缩短等待而在子智能体完成数据采集后主动打断其模型和报告阶段。若确实超时或工具失败，才将该场标为 incomplete 或 failed，保留错误与缺失数据，并由主 agent 决定是否安全重试。

向每个分析单元传递以下明确契约；单场分配时填写一个 match_id，分组分配时列出该 worker 负责的全部 match ID，并将每场的固定尝试路径逐一展开：

```text
使用 $soccer-predict 预测比赛 {match_id}，完成完整五步分析和可视化报告。
业务日期：{business_date}
业务窗口：{business_start} 至 {business_end}
已核验开球时间：{kickoff_time}

这是 batch_mode=true、archive_mode=parent 的批量调用。
使用 soccer-predict 的数据采集、模型和报告规则，但本调用由父级工作流接管归档阶段：
不要执行其单场模式的强制历史归档，不要修改 football-match-history.md、
football-league-profiles.md 或 prediction-framework.md，也不要写 daily-summary.html。

本次尝试 HTML：soccer-prediction-journal/reports/{business_date}/runs/{run_id}/match-{match_id}.html
本次尝试 JSON：soccer-prediction-journal/reports/{business_date}/runs/{run_id}/match-{match_id}.json
正式路径由主 agent 校验后发布，分析单元不得直接覆盖正式文件。

JSON 是每场必需产物，必须符合 jingcai-daily/references/result-contract.md。
success 必须同时生成完整 HTML；waiting、incomplete 或 failed 仍必须生成 JSON，HTML 可省略。
如果分析单元无法写 JSON，返回完整 JSON payload，由主 agent 写入运行目录。
关键赔率、开球状态、阵容或独立核验数据缺失时，不得给出高置信度正式推荐。
```

主 agent 必须保证每个候选 match ID 最终都有且只有一个结果 JSON。分析单元完全失败时，由主 agent 生成 `analysis_status=failed` 的 JSON，保留错误信息。

## Step 3：校验、发布、汇总和归档

### 3.1 完整性校验

所有分析单元返回后，先补齐 `run-manifest.json`，再运行：

```text
python .agents/skills/jingcai-daily/scripts/validate_run.py \
  --project-root <workspace-root> \
  --manifest soccer-prediction-journal/reports/{business_date}/runs/{run_id}/run-manifest.json \
  --phase attempt
```

校验失败时先修复 manifest 或运行产物，不生成成功汇总，也不写历史。

### 3.2 安全发布

- `generated/refreshed + success`：仅在本次 JSON 与 HTML 都通过校验后，才在同一文件系统内替换对应正式文件。
- `reused + success`：保留正式文件，不重复复制或改写历史。
- `waiting/incomplete/failed`：保留运行 JSON，不发布为正式结果，也不改写已有成功产物。
- 刷新失败时，在 manifest 和汇总中标记 `previous_success_retained=true`；旧报告只能作为“上次成功版本”展示，不能冒充本次刷新成功。
- 发布后把 manifest 中的正式路径更新为实际路径，并以 `--phase final` 再校验一次。

### 3.3 汇总

1. 候选清单中的每个 match ID 必须恰好对应一个结果；重复、遗漏或目录外路径都视为运行不完整。
2. 所有 `analysis_status=success` 的结果都进入正式汇总，包括 `run_action=reused`。
3. `waiting`、`incomplete` 和 `failed` 单独列出原因；刷新失败且保留旧版本时明确标注旧版本时间。
4. 更新 `reports/{business_date}/daily-summary.html`，包含业务窗口、运行 ID、赔率截点、来源、状态与动作统计、推荐、失败清单、报告链接和免责声明。
5. 不创建 `daily-summary-v2.html` 等变体绕过幂等规则；同一业务日的正式汇总始终更新固定文件。

### 3.4 历史归档与旧数据兼容

只有主 agent 写入：

`soccer-prediction-journal/memory/football-match-history.md`

只归档本次 `generated/refreshed + success`；`reused` 只验证已有条目，不重复写入。稳定键为：

`<!-- jingcai-key: {business_date}/{match_id} -->`

归档前按以下顺序查找：

1. 先查找完全匹配的稳定键；找到后更新该条目。
2. 没有稳定键时，在对应业务日章节中按 match ID 查找旧格式条目；唯一匹配时原地补上稳定键再更新。
3. 同一业务日存在多个旧格式匹配时，不再追加第三份。保留旧快照，在 manifest 中记录迁移异常，并选择明确标注为最近刷新且字段最完整的一条作为当前条目；无法确定时停止该场归档并报告。

当前条目至少保存：业务日期、完整开球时间、分析版本、赔率时间、推荐、预测比分、正式报告路径、预测状态“待确认”和最近刷新原因。
归档后重新读取目标段落，确认当前稳定键只出现一次。不要为了采用新键批量删除旧历史快照。

## 状态语义与降级

- `success`：关键数据和必要核验完成，JSON 合规且 HTML 完整；允许进入正式汇总。
- `waiting`：预期可在开球前补齐的临时数据尚未出现，例如首发待公布；不发布正式推荐。
- `incomplete`：分析已结束但必要核验仍缺失或已没有安全重试窗口；不发布正式推荐。
- `failed`：抓取、工具、文件写入或分析过程发生技术失败。
- 首选页的数据质量不合格时也要启用备用页，不只在 HTTP 失败时降级。
- 两个入口都无法形成可靠候选清单时停止逐场分析，并报告 URL、时间和失败原因。
- 单场失败不阻塞其他场次，但不得把空伤停表写成“阵容齐整”，不得猜测缺失数据。
- 页面出现矛盾时间时以可核验的实际开球来源为准；无法确认则保持 `waiting_verification`。

## 赛后批量复盘

1. 从历史中找出指定业务日或 match ID 的“待确认”记录，并核验 90 分钟正式赛果和来源时间。
2. 对每场调用 `$soccer-predict` 复盘流程，但沿用 `archive_mode=parent`：分析单元只返回偏差分析、联赛资料建议和权重调整建议，不写共享文件。
3. 主 agent 按 `kickoff_time + match_id` 的稳定顺序串行应用复盘。每处理一场前重新读取最新权重，遵守 soccer-predict 的单场学习护栏，再写回权重和版本。
4. 原地更新带稳定键的历史条目，不为同一场另建赛前条目；没有可靠赛果时保持“待确认”，不更新权重。
5. 更新 `reports/{business_date}/review-summary.html`，汇总推荐、实际赛果、命中、偏差原因、是否参与学习和累计统计。

## 最终交付

最终回复必须包含：业务窗口、候选/成功/复用/待核验/失败数量、汇总报告链接、成功场次报告链接、刷新失败但保留旧版本的清单，以及历史归档结果。
只提供可点击的本地文件链接，不自动打开报告。
