# 批量结果契约

本文件定义 `jingcai-daily` 的每场 JSON 和运行 manifest。字段名和状态必须保持稳定，便于主 agent
完成缓存复用、完整性校验、汇总和历史归档。

## 每场结果 JSON

每个候选 match ID 都必须有一个 JSON。`success` 同时需要 HTML；其他状态允许没有 HTML。

```json
{
  "schema_version": "1.0",
  "business_date": "2026-08-01",
  "match_id": "2912225",
  "kickoff_time": "2026-08-01T21:00:00+08:00",
  "league": "瑞典超",
  "home_team": "赫根",
  "away_team": "卡尔马",
  "analysis_status": "success",
  "artifact_action": "generated",
  "odds_snapshot_at": "2026-08-01T20:15:00+08:00",
  "analysis_version": "soccer-predict v1.3.19",
  "recommendation": "赫根 -1",
  "probability": 0.56,
  "predicted_score": "2-0",
  "score_scenarios": {
    "unconditional_mode": {
      "score": "2-0",
      "probability": 0.12,
      "primary_market_settlement": "full_win"
    },
    "primary_market_mode": {
      "market": "赫根 -1",
      "market_type": "asian_handicap",
      "selection": "home",
      "line": -1.0,
      "condition": "full_win",
      "score": "2-0",
      "joint_probability": 0.12,
      "conditional_probability": 0.21
    },
    "settlement_scenarios": [],
    "displayed_markets": [
      {
        "market": "赫根 -1",
        "market_type": "asian_handicap",
        "selection": "home",
        "line": -1.0,
        "full_win_mode": {
          "score": "2-0",
          "joint_probability": 0.12,
          "conditional_probability": 0.21
        }
      }
    ],
    "joint_market_mode": {
      "score": "2-0",
      "probability": 0.12,
      "settlements": [
        {"market": "赫根 -1", "condition": "full_win"}
      ]
    },
    "market_conflict": null
  },
  "formal_recommendation": true,
  "ou_model": {
    "model_version": "soccer-predict v1.3.23",
    "market_implied_lambda": 2.91,
    "lambda": {"total": 2.82, "home": 1.72, "away": 1.10, "feature_delta": -0.09},
    "feature_coverage": {"ratio": 0.68, "missing_value_policy": "neutral_zero_signal"},
    "feature_contributions": [],
    "markets": {
      "over": {"profit_probability": 0.44, "ev": -0.12},
      "under": {"profit_probability": 0.56, "ev": 0.07}
    }
  },
  "shadow_forecast": {
    "ou": {
      "direction": "under",
      "base_model_direction": "under",
      "post_gate_direction": "under",
      "model_probability": 0.56,
      "probability_semantics": "profit_probability=full_win+half_win",
      "ev": 0.07,
      "formal_status": "formal",
      "nonformal_reason": "none"
    }
  },
  "report_path": "soccer-prediction-journal/reports/2026-08-01/match-2912225.html",
  "missing_data": [],
  "error": ""
}
```

约束：

- `analysis_status` 只能是 `success|waiting|incomplete|failed`。
- `artifact_action` 只能是 `generated|refreshed|not_run`，表示这份 JSON/HTML 是怎样产生的。
- `match_id` 必须为纯数字字符串；不要写成 JSON 数字，以免未来 ID 格式变化造成兼容问题。
- `kickoff_time` 和 `odds_snapshot_at` 使用 ISO 8601，并包含 `+08:00`。
- `probability` 为 `0..1` 数值或 `null`。
- 新生成的结果必须提供 `score_scenarios`：`unconditional_mode` 保存全局精确比分众数及其概率；
  `primary_market_mode` 保存主推荐（或报告中首个明确观察方向）全赢条件下概率最高的代表比分。若没有任何
  市场方向，`primary_market_mode` 可为 `null`。整数大小球的条件比分必须落在全赢区域，不能用走盘比分；
  亚盘和竞彩让球胜平负必须按各自结算规则确定条件。旧版1.0产物缺少该字段时仍可读取，但刷新/新生成时必须补齐。
- `predicted_score` 作为兼容字段保留。存在正式推荐时，它必须等于 `primary_market_mode.score`；仅有观察方向时，
  若全局众数会输掉该观察盘口，报告必须同时展示两个场景，不能只显示裸 `predicted_score`。
- v1.3.18 起，`primary_market_mode` 还必须提供 `market_type`、`selection` 和 `line`（无线市场可为 `null`），
  `unconditional_mode.primary_market_settlement` 必须说明全局众数在主方向下如何结算。四分之一亚盘或大小球
  必须提供 `settlement_scenarios`，逐一列出所有非零的全赢、半赢/半输、走盘和全输分支；每项包含
  `condition`、`branch_probability`、`score`、`joint_probability`、`conditional_probability`。校验器会按
  比分、选择方和盘口线复算分支，不能把 `2-0` 之类的全输比分标成受让盘全赢代表。
- v1.3.19 起，所有报告中明确展示的正式或观察市场必须进入 `displayed_markets`，并各自提供全赢条件代表比分。
  若这些方向存在共同全赢比分，`joint_market_mode` 必须保存全赢交集中概率最高的比分及每项结算；若不存在，
  `joint_market_mode` 必须为 `null`，同时用非空 `market_conflict` 说明拆组原因。同概率比分不得随意取第一个，
  应优先选择对已展示市场结算更一致的比分。
- `missing_data` 始终为数组，`error` 始终为字符串。
- `success` 必须给出正式 `report_path`，且对应 HTML 完整存在。
- `waiting/incomplete/failed` 的 `formal_recommendation` 必须为 `false`；可在 `recommendation` 中写“等待首发”或“数据不足，不投注”等非投注结论。
- `reused` 只出现在本次 `run-manifest.json` 的 `run_action` 中；复用时不要改写正式 JSON，正式 JSON 保留原来的 `artifact_action`。
- `analysis_version >= soccer-predict v1.3.23` 时必须提供规范 `ou_model` 和
  `shadow_forecast.ou`。`ou_model` 必须来自 `soccer_ou_model.py estimate`，
  保存市场隐含 λ、最终 λ、特征覆盖、逐项贡献及 OVER/UNDER 完整结算结果。
- `shadow_forecast.ou.model_probability` 统一等于所选方向的
  `full_win + half_win`；`probability_semantics` 固定为
  `profit_probability=full_win+half_win`。两侧 EV 都不为正时，
  `direction`、`base_model_direction` 和 `post_gate_direction` 必须为
  `abstain`，`model_probability` 必须为 `null`。
- OU 特征覆盖率低于 `0.55`、批量方向审计触发阻断或其他正式门槛未通过时，
  `shadow_forecast.ou.formal_status` 不得为 `formal`；保留影子方向时必须写
  稳定的 `nonformal_reason`。

## run-manifest.json

每次运行在 `reports/{business_date}/runs/{run_id}/run-manifest.json` 保存一份 manifest：

```json
{
  "schema_version": "1.0",
  "business_date": "2026-08-01",
  "business_window": {
    "start": "2026-08-01T11:00:00+08:00",
    "end": "2026-08-02T11:00:00+08:00"
  },
  "run_id": "20260801T201500+0800",
  "created_at": "2026-08-01T20:15:00+08:00",
  "ou_batch_audit_path": "soccer-prediction-journal/reports/2026-08-01/runs/20260801T201500+0800/ou-batch-audit.json",
  "candidates": [
    {
      "match_id": "2912225",
      "kickoff_time": "2026-08-01T21:00:00+08:00",
      "league": "瑞典超",
      "home_team": "赫根",
      "away_team": "卡尔马"
    }
  ],
  "excluded": [],
  "results": [
    {
      "match_id": "2912225",
      "analysis_status": "success",
      "run_action": "generated",
      "attempt_result_path": "soccer-prediction-journal/reports/2026-08-01/runs/20260801T201500+0800/match-2912225.json",
      "attempt_report_path": "soccer-prediction-journal/reports/2026-08-01/runs/20260801T201500+0800/match-2912225.html",
      "canonical_result_path": "soccer-prediction-journal/reports/2026-08-01/match-2912225.json",
      "canonical_report_path": "soccer-prediction-journal/reports/2026-08-01/match-2912225.html",
      "previous_success_retained": false,
      "error": ""
    }
  ]
}
```

Manifest 约束：

- `candidates` 中的 match ID 必须唯一；`results` 必须与候选集合一一对应。
- Manifest 的 `run_action` 只能是 `generated|refreshed|reused|not_run`，描述当前这次运行对该场采取的动作。
- `excluded` 不进入 `candidates`，每条需保存 `reason` 和可用的原始字段。
- `generated/refreshed` 总要有 `attempt_result_path`；状态为 `success` 时还必须有 `attempt_report_path`。
- `reused` 不需要本次尝试路径，但必须给出已存在的正式 JSON 和 HTML 路径。
- 正式路径固定为 `reports/{business_date}/match-{match_id}.json|html`。
- 所有路径使用工作区相对路径，并且必须位于当前业务日目录下；拒绝 `..`、绝对路径和目录外文件。
- 刷新失败时可保留原正式路径，但 `analysis_status` 仍记录本次失败，且 `previous_success_retained=true`。
- 当本次运行含至少 8 个方向性 OU 影子预测时，`ou_batch_audit_path` 必填，
  固定指向本次运行目录的 `ou-batch-audit.json`。若审计返回
  `formal_publication_blocked=true`，所有集中方向 OU 必须降为非正式，且最终
  审计的 `formal_direction_counts.over + formal_direction_counts.under` 必须为 0。

## 发布顺序

1. 冻结候选并创建 manifest。
2. 写本次尝试 JSON/HTML，补齐 manifest 的 `results`。
3. 方向性 OU 至少 8 场时生成 `ou-batch-audit.json`；触发阻断则先降级正式 OU 并重跑审计。
4. 用 `validate_run.py --phase attempt` 校验。
5. 仅发布校验通过的成功产物；失败刷新保留旧正式文件。
6. 更新 manifest 后用 `--phase final` 校验。
7. final 校验通过后再更新汇总和历史。
