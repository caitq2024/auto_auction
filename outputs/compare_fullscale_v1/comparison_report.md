# 策略对比报告

| pv_num: 500000 | episodes: 2 | seed: 1 | controlled_slot: 0 |

同一市场、同一 seed（common random numbers）下的配对比较；排序指标为 NeurIPS competition score。

## 排名

| candidate    |   episodes |   score_mean |   score_std | score_ci95    |   conversions_mean |   expected_conversions_mean |   actual_cpa_mean |   cpa_violation_mean |   budget_utilization_mean |   paired_win_rate_vs_pid |
|:-------------|-----------:|-------------:|------------:|:--------------|-------------------:|----------------------------:|------------------:|---------------------:|--------------------------:|-------------------------:|
| upstream_iql |          2 |       17.78  |       8.781 | [9, 26.56]    |               18.5 |                       21.25 |             100.5 |              0.01335 |                    0.6483 |                        1 |
| pid          |          2 |        6.152 |       2.139 | [4.013, 8.29] |               17   |                       16.71 |             172.4 |              0.7236  |                    0.9959 |                      nan |

## 明细（per episode）

| candidate    |   episode |   score |   conversions |   expected_conversions |   cost |   actual_cpa |   target_cpa |   cpa_violation |   budget_utilization |   win_pv |   last_compete_tick |   wall_time_sec |
|:-------------|----------:|--------:|--------------:|-----------------------:|-------:|-------------:|-------------:|----------------:|---------------------:|---------:|--------------------:|----------------:|
| pid          |         0 |   4.013 |            15 |                 14.48  | 2900   |       193.3  |          100 |          0.9333 |               1      |    26522 |                  33 |           38.59 |
| pid          |         1 |   8.29  |            19 |                 18.93  | 2876   |       151.4  |          100 |          0.5139 |               0.9918 |    28959 |                  47 |           34.76 |
| upstream_iql |         0 |  26.56  |            28 |                 34.29  | 2875   |       102.7  |          100 |          0.0267 |               0.9913 |    27449 |                  47 |           35.18 |
| upstream_iql |         1 |   9     |             9 |                  8.213 |  885.5 |        98.38 |          100 |          0      |               0.3053 |    11222 |                  47 |           32.07 |

> 所有数字为 simulated 结果，未经客户数据校准，不代表真实平台收益。