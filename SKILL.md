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
Step 1: 找比赛 → Step 2: 逐场分析 → Step 3: 汇总输出
```

## Step 1: 找比赛

1. 导航到 `https://cp.titan007.com/buy/JingCai.aspx`
2. 从页面提取当日所有未开赛/已截止的 match ID（如 `2999954`）
3. 提取每场的竞彩赔率（胜平负+让球）
4. **推荐使用** `https://aiplus.titan007.com/ai/pc/spf` 代替竞彩页面，该页面每天仅列出当日有效场次、无重复条目
5. 列出完整比赛清单给用户确认

## Step 2: 逐场分析

对每一场比赛调用 `$soccer-predict` 完成完整五步量化分析。执行方式按当前环境能力选择：

- **默认**：在当前任务内逐场分析，完成一场再开始下一场，不自动创建新线程
- **多智能体可用时**：优先使用多智能体工具（如 `spawn_agent`）并行派发子智能体，每个子智能体负责一场比赛
- **仅当用户明确要求创建独立任务时**：才使用 `create_thread` 创建用户可见的子任务线程；不要把 `create_thread` 用于内部并行，因为线程会出现在侧边栏且归用户所有

- **Prompt 模板**: `使用 $soccer-predict 预测比赛 {match_id}`
- 每个分析单元独立采集数据（亚盘、大小球、欧赔、基本面、阵容）并运行五步框架
- 每场产出独立 HTML 报告到 `soccer-prediction-journal/reports/`

## Step 3: 汇总输出

所有比赛分析完成后：

1. 读取各报告的关键结论
2. 生成一张汇总表（对阵、赔率、推荐、概率、比分）
3. 生成最终汇总 HTML 报告
4. 存档所有场次到工作区根目录的 `soccer-prediction-journal/memory/football-match-history.md`

**⚠️ 存档重要提醒**：若按用户要求创建了独立任务线程，子任务可能在独立目录中运行并各自生成自己的 `football-match-history.md`。Step 3 必须由主 agent 从各分析结果/汇总表中提取关键数据，统一追加写入 **工作区根目录** 的 `soccer-prediction-journal/memory/football-match-history.md`，而非依赖子任务自行写入。

### Step 3 额外操作

- 若按用户要求创建了独立任务线程，分析完成后主 agent 可将其归档（`set_thread_archived`）
- 输出各报告的可点击本地文件链接；遵守仓库 AGENTS.md，不自动打开浏览器或报告文件

## 已分析场次跳过

如果某场已经分析过（报告文件已存在且当天生成），跳过不重复分析。

## 赛后复盘

当用户提供比赛结果时，按 Step 2 的并行规则对每场调用 `$soccer-predict` 的复盘流程进行偏差分析和权重优化。
