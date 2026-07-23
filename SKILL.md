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
Step 1: 找比赛 → Step 2: 并行分析 → Step 3: 汇总输出
```

## Step 1: 找比赛

1. 导航到 `https://cp.titan007.com/buy/JingCai.aspx`
2. 从页面提取当日所有未开赛/已截止的 match ID（如 `2999954`）
3. 提取每场的竞彩赔率（胜平负+让球）
4. 列出完整比赛清单给用户确认

## Step 2: 并行分析

对每一场比赛，使用 `create_thread` 创建独立子任务：

- **Prompt 模板**: `使用 $soccer-predict 预测比赛 {match_id}`
- **并行度**: 所有场次同时启动，不等先后
- 每个子任务独立采集数据（亚盘、大小球、欧赔、基本面、阵容）并运行五步框架
- 子任务产出独立 HTML 报告到 `E:\codex_project\soccer-predict\reports\`

## Step 3: 汇总输出

所有子任务完成后：

1. 读取各报告的关键结论
2. 生成一张汇总表（对阵、赔率、推荐、概率、比分）
3. 生成最终汇总 HTML 报告
4. 存档所有场次到 `E:\codex_project\soccer-predict\memory\football-match-history.md`

## 已分析场次跳过

如果某场已经分析过（报告文件已存在且当天生成），跳过不重复分析。

## 赛后复盘

当用户提供比赛结果时，对每场调用 `$soccer-predict` 的复盘流程进行偏差分析和权重优化。
