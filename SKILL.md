---
name: jingcai-daily
description: >
  每日竞彩足球批量分析、赔率刷新和批量复盘工作流。用户要求分析今天、明天或指定日期的全部/多场竞彩，
  刷新当日赔率、临场复测，或复盘一批竞彩场次时使用。按中国竞彩业务日（Asia/Shanghai 当日11:00
  至次日11:00）获取并核验尚未开赛场次，逐场调用 soccer-predict，生成日期目录下的单场报告、
  结构化结果、Markdown 汇总报告、幂等历史归档，在对话中直接返回逐场核心预测，
  并在最终校验后同步预测记录到 GitHub。多场任务优先使用
  具有独立写入范围的 subagent 并行分析；单场比赛、单个 match ID 或单场盘口问题优先使用 soccer-predict。
---

# 竞彩日分析工作流

把一批比赛作为一个可核验、可重跑、失败后可恢复的任务处理：先冻结比赛集合，再逐场分析，最后由主 agent
统一校验、发布、汇总和归档。不要因单场抓取失败虚构结论，也不要把已开赛场次包装成赛前预测。

## 开始前

1. 完整读取项目级 `$soccer-predict` 的 `SKILL.md`，把它作为单场分析引擎。普通单场不要预加载
   `raw.json`、完整 `summary.json`、模型源码、完整预测框架或旧预测大 JSON；只有生成的
   `analysis-packet.json` 中 `reference_routing` 命中时，才读取对应参考文档。
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
- 新报告统一使用 Markdown，不生成 HTML，不自动打开浏览器或文件。
- 最终对话必须直接给出逐场主推方向、行动等级、概率/EV、比分和风险摘要，
  再附本地 Markdown 报告链接；只提供文件链接视为交付未完成。

## Step 1：获取、标准化并冻结比赛清单

### 数据入口

竞彩比赛清单统一从以下页面获取：

`https://cp.titan007.com/buy/JingCai.aspx`

不要再从 AI 预测页生成或补齐候选清单。AI 预测页、比赛详情页和赔率页只能作为清单冻结后的单场交叉核验来源。

按以下竞彩页契约读取，避免把展示字段误当成真实数据：

- 页面按竞彩业务日展示，通常包含“当日 11:00--次日 11:00”的分组；用户指定日期时，先在页面日期选择器中切换到对应业务日，再读取 `#MatchTable`。
- 比赛行通常是 `tr[id^="row_"]`。第一列是竞彩编号，第二列是联赛，主客队链接通常指向 `bf.titan007.com/panlu/<match_id>.htm`。以该详情链接中的数字作为 canonical `match_id`；不要把行的 `id="row_<...>"` 或 `matchid` 属性当作比赛 ID，它们可能是竞彩页面内部行号。
- 实际开球时间读取带有 `开赛时间：YYYY-MM-DD HH:mm` 的单元格 `title` 属性，即使该列因页面显示设置被隐藏；带有 `截止时间：` 的单元格只记录销售截止时间，绝不能写入 `kickoff_time`。
- `cansale=true/false` 只表示当前是否可售，不等于未开赛/已开赛。比分为 `-` 且开球时间晚于 `{now}` 时才可作为未开赛候选；出现比分、比赛分钟或其他进行中状态时，仍须用比赛详情页核验状态。
- 胜平负赔率通常位于 `spfTr_<row_id>`，让球胜平负赔率通常位于 `rqTr_<row_id>`；页面显示“未开售胜平负玩法”或字段缺失时保留缺失状态，不得补猜赔率。

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

- 正式 Markdown：`reports/{business_date}/match-{match_id}.md`
- 正式 JSON：`reports/{business_date}/match-{match_id}.json`
- 本次尝试 Markdown：`reports/{business_date}/runs/{run_id}/match-{match_id}.md`
- 本次尝试 JSON：`reports/{business_date}/runs/{run_id}/match-{match_id}.json`

### 普通运行与刷新

- 普通运行只有在正式 Markdown 存在、正式 JSON 的 `analysis_status` 为 `success`、业务日和 match ID 匹配，并且历史条目完整时才复用。复用结果保持 `analysis_status=success`，设置 `run_action=reused`。只有历史 HTML 而没有 Markdown 时不得复用，应重新生成新格式报告。
- 任一正式产物缺失、JSON 无法解析、状态不是 `success`、路径不合规或历史条目不完整时，重新分析并设置 `run_action=generated`。
- 用户要求刷新赔率、重新分析或临场复测时设置 `run_action=refreshed`，始终重新采集；旧正式产物在新尝试通过校验前保持不变。
- `skipped` 不是分析状态。分析质量使用 `analysis_status`，本次运行的动作使用 manifest 中的 `run_action`；正式 JSON 用 `artifact_action` 记录产物最初由生成还是刷新产生。

### 执行方式与批量模式契约

- 当待分析场次 N >= 4 且存在可用的多智能体能力时，必须优先使用 subagent 并行分析；不要先在主 agent 中串行完成全部场次再补建并发。1–3 场使用 1 个分析单元，避免并发编排成本超过收益。只有没有多智能体能力、并发槽位为 1、或用户明确要求串行时，才在当前任务内逐场执行。
- 有多智能体能力时，先读取当前可用的并发槽位，再按“最多 3 个分析单元、场次均衡分组”的策略派发；禁止默认每场启动一个智能体。每个单元只写自己的运行目录文件，不写任何共享文件。主 agent 负责冻结、分配、回收、校验、发布、汇总、归档和 GitHub 同步。
- 不要用 `create_thread` 创建用户可见任务，除非用户明确要求独立任务。

### 比赛场次分配策略

主 agent 先完成候选冻结、缓存判定和运行目录初始化，再把仍需分析的 match ID 分配给当前可用的子智能体。按场次数量和槽位动态均衡：

1. 设待分析场次数为 N，当前可用子智能体数为 W。1–3 场使用 1 个分析单元，4–6 场使用 2 个，7 场及以上最多使用 3 个；实际并发数还必须受 W 和运行环境槽位上限约束。
2. 将场次按稳定顺序轮转或均衡分组，使每个分析单元负责的场次数相差不超过 1；不得为了凑并发重复创建线程，也不得采用“每场一个智能体、全部同时启动”。
3. 分组时优先保持每个子任务的比赛数量均衡，同时把相同联赛或相近开球时间放在同一组仅作为可选优化；不能因为分组方便而改变候选集合、跳过比赛或把已开赛场次加入任务。
4. 每个分配消息必须列出该子智能体负责的全部 match ID、竞彩编号、开球时间、主客队、business_date、run_id 和每场固定尝试路径。子智能体必须逐场处理自己的整个分组，不能只抓取盘口后提前结束。
5. 子智能体的完成条件是“每场通过两阶段入口走完完整预测并提交结果”：包括基本面、伤停/首发状态、欧赔、亚盘、大小球、模型概率、胜平负、竞彩让球胜平负、预测比分、EV/价值判断、冷门与失效条件，以及该场 JSON 和完整 Markdown。只有 `run-state.json` 到达 `validated`，才向主 agent 返回最终摘要。
6. 子智能体可以并行抓取不同比赛，但不能并行写同一场的 JSON/Markdown，也不能修改 run-manifest.json、daily-summary.md、历史、联赛资料或预测框架。每个 match ID 在运行目录中只能有一份结果。
7. 主 agent 应维护一个内部分配表，记录 match_id -> worker -> status，并在回收结果后检查每场是否有最终产物。某个子智能体中断时，只把未完成的 match ID 重新分配给空闲槽位；不要让两个子智能体同时重写同一场。
8. 不要为了缩短等待而在子智能体完成数据采集后主动打断其模型和报告阶段。若确实超时或工具失败，才将该场标为 incomplete 或 failed，保留错误与缺失数据，并由主 agent 决定是否安全重试。

### 逐场两阶段入口

每场调用项目级 `soccer-predict` 的确定性入口：

1. `python .agents/skills/soccer-predict/scripts/predict_one.py start <match_id>`：建立独占目录，
   完成一次抓取，并生成轻量 `analysis-packet.json`、可编辑 `analysis-overlay.json` 和
   `run-state.json`；
2. 分析单元只读取 packet，并编辑已生成的 overlay。普通路径不得读取原始快照、完整摘要、
   模型源码或完整预测框架；
3. `python .agents/skills/soccer-predict/scripts/predict_one.py finish --run-dir <run_dir> --mode batch`：
   默认读取该运行目录的 overlay，完成准备、建模、Markdown/JSON/聊天载荷生成和验证；
4. 返回 `run-state.json` 的阶段、精确逐场工件路径和核心聊天载荷。单场卡住时检查现有阶段工件，
   使用原 `run_dir` 恢复；不得从头重复抓取或手工绕过 runner 重算结论。

单场内部首轮网络并发最多 5 个请求，使基本面、欧赔、亚盘、大小球和首发同时抓取；结合最多
3 个分析单元，批量峰值保持在 15 个首轮请求以内，避免对 Titan007 形成无界并发。
输入契约失败时按返回的 `code/path/message` 只修 overlay 或指定证据缺口，再继续原运行目录。

### 主 agent 等待与回收纪律

1. 派发后，主 agent 必须对所有活动 worker 建立 match_id -> worker -> status 回收表，并使用多目标等待能力持续等待；不得因为暂时没有文件、没有最终摘要或等待一次超时，就判定 worker 失败。
2. pending_init、running 和“已写入部分产物但尚未返回终态”都不是失败。主 agent 不得在这些状态下调用 close_agent 或 interrupt=true，也不得为了提前交付而中止其分析。
3. 长任务可以分段等待并发送不打断工作的进度询问，但累计等待必须持续到每个 worker 返回 completed、明确 errored 或明确 interrupted。只有明确终态且确认该场未完成时，才允许把 match ID 重新分配给空闲槽位。
4. worker 返回 completed 后，主 agent 仍须读取并校验该 worker 的 JSON/Markdown；交付文件存在不等于 worker 已返回终态，不能因此提前关闭。只有读取完成状态、校验产物并记录结果后，才可关闭已完成 worker。
5. 如果用户在等待期间追加问题，先报告仍在等待的 worker 和已收到的交付，再继续等待；不要因一次对话更新而丢弃或关闭未完成的 worker。
6. 主 agent 不得重做仍在运行 worker 负责的同一场分析。可以并行准备不重叠的汇总模板、校验命令和发布计划，但不得覆盖 worker 的尝试 JSON/Markdown。

向每个分析单元传递以下明确契约；单场分配时填写一个 match_id，分组分配时列出该 worker 负责的全部 match ID，并将每场的固定尝试路径逐一展开：

```text
使用 $soccer-predict 的两阶段入口预测比赛 {match_id}，完成完整分析和详细 Markdown 报告。
业务日期：{business_date}
业务窗口：{business_start} 至 {business_end}
已核验开球时间：{kickoff_time}

这是 batch_mode=true、archive_mode=parent 的批量调用。
使用 soccer-predict 的数据采集、模型和报告规则，但本调用由父级工作流接管归档阶段：
不要执行其单场模式的强制历史归档，不要修改 football-match-history.md、
football-league-profiles.md 或 prediction-framework.md，也不要写 daily-summary.md。

本次尝试 Markdown：soccer-prediction-journal/reports/{business_date}/runs/{run_id}/match-{match_id}.md
本次尝试 JSON：soccer-prediction-journal/reports/{business_date}/runs/{run_id}/match-{match_id}.json
正式路径由主 agent 校验后发布，分析单元不得直接覆盖正式文件。

JSON 是每场必需产物，必须符合 jingcai-daily/references/result-contract.md。
success 必须同时生成完整 Markdown；waiting、incomplete 或 failed 仍必须生成 JSON，Markdown 可省略。
如果分析单元无法写 JSON，返回完整 JSON payload，由主 agent 写入运行目录。
关键赔率、开球状态、阵容或独立核验数据缺失时，不得给出高置信度正式推荐。
先运行 `predict_one.py start <match_id>`，只读取 `analysis-packet.json` 并编辑已生成的
`analysis-overlay.json`；再运行 `predict_one.py finish --run-dir <run_dir> --mode batch`。
不得读取完整原始快照、摘要、模型源码或预测框架来重复推导，也不得手工调用 prepare/runner
后续写报告。结果 JSON 必须保存规范 `ou_model` 和 `shadow_forecast.ou`，不得手工填写总 λ
或使用默认小球方向。
```

主 agent 必须保证每个候选 match ID 最终都有且只有一个结果 JSON。分析单元完全失败时，由主 agent 生成 `analysis_status=failed` 的 JSON，保留错误信息。

## Step 3：校验、发布、汇总和归档

### 3.1 OU 批量统计与完整性校验

所有分析单元返回后，主 agent 先从每场结果中收集规范
`shadow_forecast.ou`，写入本次运行目录的 `ou-batch-forecasts.json`，并生成批次统计：

```text
python .agents/skills/soccer-predict/scripts/soccer_ou_model.py audit \
  --input soccer-prediction-journal/reports/{business_date}/runs/{run_id}/ou-batch-forecasts.json \
  --output soccer-prediction-journal/reports/{business_date}/runs/{run_id}/ou-batch-audit.json
```

- 将 `ou_batch_audit_path` 写入 manifest。统计输入和输出都属于运行证据，
  不得写入正式日期目录根部。
- 批次统计只保存方向计数、主方向、集中度和 conversion funnel，不设置集中度比例或样本数阈值，
  不产生 `review_required`、`sensitivity_required` 或正式阻断。
- `formal_publication_blocked` 必须为 `false`；各场 OU 是否正式发布仍只由该场身份、盘口、证据覆盖、
  阵容敏感度、压力 EV、基础 EV 和市场冲突门控决定，AH 同理。

所有分析单元返回后，先补齐 `run-manifest.json`，再运行：

```text
python .agents/skills/jingcai-daily/scripts/validate_run.py \
  --project-root <workspace-root> \
  --manifest soccer-prediction-journal/reports/{business_date}/runs/{run_id}/run-manifest.json \
  --phase attempt
```

校验失败时先修复 manifest 或运行产物，不生成成功汇总，也不写历史。OU 正式方向集中本身
不再构成完整性校验失败；若审计发现真实数据或符号错误，修正后重新运行审计。

### 3.2 安全发布

- `generated/refreshed + success`：仅在本次 JSON 与 Markdown 都通过校验后，才在同一文件系统内替换对应正式文件。
- `reused + success`：保留正式文件，不重复复制或改写历史。
- `waiting/incomplete/failed`：保留运行 JSON，不发布为正式结果，也不改写已有成功产物。
- 刷新失败时，在 manifest 和汇总中标记 `previous_success_retained=true`；旧报告只能作为“上次成功版本”展示，不能冒充本次刷新成功。
- 发布后把 manifest 中的正式路径更新为实际路径，并以 `--phase final` 再校验一次。

### 3.3 汇总

1. 候选清单中的每个 match ID 必须恰好对应一个结果；重复、遗漏或目录外路径都视为运行不完整。
2. 所有 `analysis_status=success` 的结果都进入正式汇总，包括 `run_action=reused`。
3. `waiting`、`incomplete` 和 `failed` 单独列出原因；刷新失败且保留旧版本时明确标注旧版本时间。
4. 更新 `reports/{business_date}/daily-summary.md`，包含业务窗口、运行 ID、赔率截点、来源、状态与动作统计、逐场主推/行动等级/概率/EV/比分/风险、失败清单、报告链接和免责声明。
5. 不创建 `daily-summary-v2.md` 等变体绕过幂等规则；同一业务日的正式汇总始终更新固定文件。
6. 汇总必须分列 OU 正式推荐、非正式影子方向和 `abstain`；存在
   `ou-batch-audit.json` 时展示方向计数、集中度、统计状态和
   `publication_policy=descriptive_only`。集中度本身不得触发审计、正式降级，也不得把其他门控产生的
   观察方向写成普通预测推荐。

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

### 3.5 推送预测记录到 GitHub

在 --phase final 校验通过、正式汇总和历史归档完成后，主 agent 默认必须把本次预测记录推送到项目配置的预测历史 GitHub 仓库；除非用户明确要求只生成报告/不要推送，或推送被远端权限、网络或分叉冲突阻塞。

按项目级仓库映射执行：

1. 定位 soccer-prediction-journal/ 仓库和其配置的默认分支。预测历史仓库通常为 E:\codex_project\soccer-prediction-journal 的 main。
2. 运行 git status --short --branch，确认本次变更范围；只暂存本次业务日的报告、运行 manifest、汇总文件和本次实际更新的历史条目，禁止使用 git add -A 静默带入无关改动。
3. 推送前运行 git fetch origin <branch>，用 git rev-list --left-right --count HEAD...origin/<branch> 确认没有分叉。发现远端领先或已分叉时停止推送并报告，不强制覆盖远端。
4. 提交信息使用简洁稳定格式，例如 Add {business_date} Jingcai prediction records；提交前再次检查 staged diff。
5. 按仓库要求直接执行 git push origin <branch>；除非用户明确要求 PR，不创建 PR、不把 gh auth status 作为普通直接推送的前置条件，也不改用其他凭据绕过 Git Credential Manager。
6. 推送失败若疑似沙箱网络限制，按平台权限流程申请提升后重试同一 Git 命令；不要改写提交或强制推送。
7. 推送后再次 git fetch origin <branch>，确认 HEAD 与 origin/<branch> 的提交哈希一致且工作区干净。最终回复必须报告仓库、分支、commit 和同步结果。

## 状态语义与降级

- `success`：关键数据和必要核验完成，JSON 合规且 Markdown 完整；允许进入正式汇总。
- `waiting`：预期可在开球前补齐的临时数据尚未出现，例如首发待公布；不发布正式推荐。
- `incomplete`：分析已结束但必要核验仍缺失或已没有安全重试窗口；不发布正式推荐。
- `failed`：抓取、工具、文件写入或分析过程发生技术失败。
- 竞彩页的数据质量不合格时，不得用 AI 预测页替代或补齐比赛清单；可用比赛详情页和赔率页逐场核验，仍无法可靠确定关键字段时停止该场并标记 `waiting_verification`。
- 竞彩页无法形成可靠候选清单时停止逐场分析，并报告 URL、时间和失败原因。
- 单场失败不阻塞其他场次，但不得把空伤停表写成“阵容齐整”，不得猜测缺失数据。
- 页面出现矛盾时间时以可核验的实际开球来源为准；无法确认则保持 `waiting_verification`。

## 赛后批量复盘

1. 复盘集合不得只从历史取数。对指定业务日，先读取历史中的“待确认”记录，再读取
   `reports/{business_date}/runs/*/run-manifest.json` 的全部候选，取二者并集并按
   `business_date + match_id` 去重。`success`、`waiting` 和 `incomplete` 都进入复盘集合；
   `failed` 仅在存在可识别的赛前方向或预测比分时进入，否则单列为“无可复盘预测”。这样可覆盖因未达到
   success 发布门槛而没有写入历史、但已经形成冻结观察方向的尝试产物。
2. 对 manifest 中没有历史条目的 `waiting/incomplete` 场次，读取其 `attempt_result_path` 和
   `attempt_report_path` 作为赛前冻结快照。复盘与汇总必须明确标记“非正式观察”，不得把它升级为正式
   推荐，也不得计入正式 AH/OU 或竞彩命中率；可靠赛果核验后可写入带稳定键的观察复盘条目，保存原始
   `analysis_status`、运行 ID 和尝试报告路径。
3. 对每场调用 `$soccer-predict` 复盘流程，但沿用 `archive_mode=parent`：分析单元只返回偏差分析、联赛资料建议和权重调整建议，不写共享文件。
4. 主 agent 按 `kickoff_time + match_id` 的稳定顺序串行应用复盘。每处理一场前重新读取最新权重，遵守 soccer-predict 的单场学习护栏，再写回权重和版本。
5. 原地更新带稳定键的历史条目，不为同一场另建赛前条目；没有历史条目但存在可复盘尝试产物时，按第2条创建明确标注为“非正式观察复盘”的稳定键条目。没有可靠赛果时保持“待确认”，不更新权重。
6. 更新 `reports/{business_date}/review-summary.md`，逐一覆盖并核对并集中的每个 match ID，汇总正式推荐、非正式观察、实际赛果、命中、偏差原因、是否参与学习和累计统计；最终数量必须与去重后的复盘集合一致。旧 manifest 中的 HTML 报告路径可作为历史冻结快照只读参考，不得因复盘而重写或新建 HTML。

## 最终交付

最终回复必须包含：业务窗口、候选/成功/复用/待核验/失败数量；逐场主推方向、
`formal_standard|formal_cautious|direction_only` 行动状态、概率/EV、预测比分和主要风险；
汇总与成功场次 Markdown 链接；刷新失败但保留旧版本的清单；历史归档结果；
以及 GitHub 推送的仓库、分支、commit 和同步状态。不自动打开报告。
