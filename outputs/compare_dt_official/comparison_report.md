# 策略对比报告

| pv_num: 500000 | episodes: 2 | seed: 1 | controlled_slot: 0 |

同一市场、同一 seed（common random numbers）下的配对比较；排序指标为 NeurIPS competition score。

## 排名

| candidate                                          |   episodes |   score_mean |   score_std | score_ci95      |   conversions_mean |   expected_conversions_mean |   actual_cpa_mean |   cpa_violation_mean |   budget_utilization_mean |   paired_win_rate_vs_dt_model_diroutputs/dt_official/saved_model/DTtest |
|:---------------------------------------------------|-----------:|-------------:|------------:|:----------------|-------------------:|----------------------------:|------------------:|---------------------:|--------------------------:|------------------------------------------------------------------------:|
| dt_model_diroutputs/dt_official/saved_model/DTtest |          2 |        1.505 |      0.5495 | [0.9557, 2.055] |                9.5 |                       8.999 |             256.1 |                1.561 |                    0.8266 |                                                                     nan |

## 明细（per episode）

| candidate                                          |   episode |   score |   conversions |   expected_conversions |   cost |   actual_cpa |   target_cpa |   cpa_violation |   budget_utilization |   win_pv |   last_compete_tick |   wall_time_sec |
|:---------------------------------------------------|----------:|--------:|--------------:|-----------------------:|-------:|-------------:|-------------:|----------------:|---------------------:|---------:|--------------------:|----------------:|
| dt_model_diroutputs/dt_official/saved_model/DTtest |         0 |  0.9557 |             7 |                    4.8 |   1894 |        270.6 |          100 |           1.706 |               0.6532 |    17640 |                  28 |           34.49 |
| dt_model_diroutputs/dt_official/saved_model/DTtest |         1 |  2.055  |            12 |                   13.2 |   2900 |        241.7 |          100 |           1.417 |               1      |    24698 |                  41 |           32.33 |

> 所有数字为 simulated 结果，未经客户数据校准，不代表真实平台收益。