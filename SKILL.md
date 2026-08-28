---
name: jingcai-daily
description: >
  每日竞彩足球全量分析工作流。当用户请求"分析今天竞彩"、"预测今天比赛"、
  "竞彩日分析"等批量分析竞彩赛事时触发。自动从竞彩官网抓取当日所有场次，
  然后对每场调用 soccer-predict skill 进行完整五步量化分析，最后汇总输出。
  Triggers: (1) "分析今天竞彩", (2) "预测今天所有比赛", (3) "竞彩日分析",
  (4) "帮我分析今天的竞彩比赛", (5) references to 竞彩 daily batch prediction.
---

# 竞彩日分析工作流

## 流程概览

```
Step 1: 找比赛 → Step 2: 合理分组 → Step 3: 逐场快速分析 → Step 4: 统一审计与交付
```

## Step 1: 找比赛

1. 导航到 `https://cp.titan007.com/buy/JingCai.aspx`
2. 从页面 DOM 的 `[matchid]`、`cansale`、开赛时间和截止时间字段提取当日完整比赛清单；销售状态与是否开赛必须分别判断。
3. 保存竞彩编号、Titan 比赛 ID、主客队竞彩名称、开赛时间、截止时间、胜平负及让球赔率。
4. 列出完整比赛清单。用户已明确要求分析全部比赛时直接继续；只有赛事身份或日期栏目不明确时才暂停确认。

## Step 2: 合理分组

使用当前任务内的协作子智能体，不创建用户侧独立 `create_thread`。按场次数量均衡分组：

- 1–3 场：1 个分析单元；
- 4–6 场：2 个分析单元；
- 7 场及以上：最多 3 个分析单元，按场次数量均分；
- 每个分析单元顺序处理自己分配的比赛，禁止“每场一个智能体、全部同时启动”。

每个分析单元必须返回阶段状态：`fetched`、`summarized`、`prepared`、`modeled`、
`validated`。单场卡住时先检查已有阶段工件，再定向重试缺失阶段；页面探测失败时优先使用
`soccer_fetch.py`，不得无限等待。

## Step 3: 逐场快速分析

每场调用项目级 `soccer-predict`，严格执行其快速通道：

1. 使用独占目录 `.tmp-soccer-predict-{date}-{match_id}-{run_id}/`；
2. `soccer_fetch.py` 生成 `raw.json`；
3. `soccer_summarize.py --output-json` 生成紧凑 `summary.json`；
4. 只根据摘要和必要的补充来源生成 `analysis-overlay.json`；
5. `soccer_prepare_input.py` 生成 `prediction-input.json`；
6. `soccer_prediction_runner.py` 生成逐场 Markdown 和结构化 JSON。

单场内部网络并发最多 4 个请求；结合最多 3 个分析单元，避免对 Titan007 形成无界并发。
字段完整时不得重复打开浏览器、读取旧的大型预测 JSON 或检查模型源码。J.LEAGUE 官方首发、
伤停独立核验和身份冲突仍按 `soccer-predict` 契约补证。

### 逐场写入边界

分析单元只允许写入：

- `soccer-prediction-journal/reports/YYYY-MM-DD/match-{match_id}.md`
- `soccer-prediction-journal/reports/YYYY-MM-DD/match-{match_id}.json`
- 自己的独占临时目录

分析单元不得并发修改 `memory/football-match-history.md`、`summary.md`、
`batch-summary.json`，不得自行提交或推送 Git，也不得清理其他比赛的临时目录。

## Step 4: 统一审计与交付

所有逐场工件完成后由主流程统一执行：

1. 验证每场均有且只有一个 AH 方向、一个 OU 方向和一个主推方向；
2. 聚合 AH/OU `conversion_funnel`、`action_status`、`primary_blocking_reason`、正式数量和候选后置阻断数量；
3. 同批至少 8 个 OU 方向且任一方向达到 75% 时运行集中度审计并阻断正式发布，不机械反向；6–7 场达到 80% 时运行敏感性审计；
4. 生成 `reports/YYYY-MM-DD/summary.md` 和 `batch-summary.json`；不得生成新的 HTML 报告；
5. 一次性追加 `soccer-prediction-journal/memory/football-match-history.md`；
6. 验证全部报告、快照、批次汇总和历史记录后，逐场安全清理临时目录；
7. 按项目规则在 `soccer-prediction-journal/main` 进行一次范围明确的提交和推送，并核验远端提交。

## 已分析场次跳过

只有当同一比赛 ID 已存在通过验证的赛前冻结 JSON/Markdown、`retrieved_at` 早于开球、
身份一致且本次不是用户明确要求的临场更新时，才跳过。仅凭“当天文件存在”不能跳过。

## 赛后复盘

当用户请求赛果结算、命中率、ROI、累计学习或权重优化时，停止本赛前流程并路由到项目级
`soccer-review` Skill；不得回退到 `soccer-predict` 执行复盘。
