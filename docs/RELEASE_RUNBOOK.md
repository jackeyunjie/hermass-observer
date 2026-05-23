# Hermass Observer Product Release Runbook

## 每日发布步骤

1. 在研究母库确认每日发布已完成。

```bash
cd ../hongrun-chaos-trading-system
.venv/bin/python scripts/verify_p116b_ashare_d1_official_sr_key_positions.py
.venv/bin/python scripts/verify_p116d_ashare_omni_cycle_alignment.py
.venv/bin/python scripts/verify_p108_daily_consumer_observation_card.py
```

2. 回到产品库导入。

```bash
cd ../hermass-observer-product
python3 scripts/import_from_research_repo.py
python3 scripts/verify_release.py
```

3. 打开页面。

```text
public/index.html
```

4. 对外分发前确认：

- 日期正确。
- 数据层级正确。
- 无禁用词。
- 无歧义字段。
- 页面只说观察，不说行动。
