# P116 Recommendation Workbench

独立推荐工作目录，用于把 P116 每日三周期 E/F 观察池转换为“研究型股票池 + 组合候选 + 风险剔除 + 可打开报告”。

## Design Rules

- 全部通过 Python/CLI 运行，不依赖 IDE。
- 默认模型配置为 `deepseekV4`，但第一版推荐引擎不依赖大模型即可运行。
- 输入来自每日标准池：`outputs/p116_daily_all_three_ef/`。
- 输出同时保存到 `recommendation/outputs/` 和 `public/`。
- 所有页面必须包含 Research-Only 提示。

## Run

```bash
python3 recommendation/run_recommendation_workflow.py --date 2026-05-20
```

可选：使用已有资金流增强 CSV。

```bash
python3 recommendation/run_recommendation_workflow.py \
  --date 2026-05-20 \
  --moneyflow-csv public/p116_moneyflow_enhanced_top10_20260520.csv
```

## Outputs

```text
recommendation/outputs/p116_recommendation_YYYYMMDD.json
recommendation/outputs/p116_recommendation_YYYYMMDD.csv
public/p116_recommendation_YYYYMMDD.html
public/p116_recommendation_YYYYMMDD.csv
public/p116_recommendation_latest.html
```

## Scope

This workbench provides structured observation and portfolio research candidates. It does not produce guaranteed return claims or execution instructions.
