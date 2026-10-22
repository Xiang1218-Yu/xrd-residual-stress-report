# 热处理钢件的残余应力单

热处理后的轴承钢滚道需要做表面质量确认。检测人员用 X 射线衍射仪，在多个方位和倾转角采集衍射峰，程序要把这份测量资料整理成可供工艺人员判断的残余应力单。当前入口对仪器零点、重复测量和缺失数据处理不完整，结果可能把无效峰位当成真实应力。

## 输入资料

程序命令保持为：

```bash
python3 /app/xrd_stress_report.py <输入资料> <输出报告>
```

输入是 UTF-8 JSON 对象，包含 `specimen_id`、`material`、`wavelength_nm`、`stress_free_d_nm`、`youngs_modulus_gpa`、`poisson_ratio`、`instrument_zero_deg`、`limits` 和 `measurements`。`limits` 至少包含 `max_tensile_mpa`、`max_compressive_mpa`；每条测量记录包含 `azimuth_deg`、`tilt_deg`、`peak_2theta_deg`、`quality`。数值应为有限数字，`quality` 在 0 到 1 之间，倾转角在 0 到 85 度之间。

`peak_2theta_deg` 是仪器记录的两倍衍射角，`instrument_zero_deg` 是仪器零点偏移。计算晶面间距前，应先从记录峰位中扣除零点偏移，再将修正后的两倍角除以二得到布拉格角，并依据布拉格定律计算晶面间距和应变。不能把两倍角直接当成布拉格角，也不能把应变或峰位直接当成应力。

## 处理规则

峰拟合质量低于 0.8 的记录不能参与拟合，但要在 `issues` 中留下 `LOW_QUALITY`。缺字段、非有限数、质量越界、倾转角越界、修正后角度无法用于布拉格计算的记录不能参与计算，并分别留下可识别的问题标记。相同 `azimuth_deg` 和 `tilt_deg` 的重复记录只保留质量较高的一条；质量相同的重复记录也必须使用确定性的选择规则，不能因输入顺序变化而改变结果，并留下 `DUPLICATE_MEASUREMENT`。

每个方位单独拟合应变与 `sin(tilt_deg)^2` 的关系，不能把不同方位的记录混在一条回归线上。一个方位少于 3 个有效倾转点，或所有有效倾转点没有变化时，该方位不能输出应力。没有任何可用方位时，整体状态必须为 `REVIEW`。有效记录不足、异常记录或重复记录都不能用默认数值悄悄替代。

## 输出报告

输出为 UTF-8 JSON，写入第二个命令行参数指定的文件，并以换行结束。顶层包含 `specimen_id`、`status`、`directions`、`summary`、`issues`。每个有效方位包含 `azimuth_deg`、`stress_mpa`、`stress_type`、`fit_rmse_mpa`、`valid_points`。正值应标为 `tensile`，负值应标为 `compressive`；`summary` 至少给出 `max_tensile_mpa`、`max_compressive_mpa` 和 `worst_azimuth_deg`。

`issues` 是问题对象数组；每项包含 `code`、`count` 和 `message`，其中 `code` 是稳定的问题标识，`count` 是该类问题的数量，`message` 用于说明原因。相同问题应合并为一项，报告中的问题顺序应保持确定，不应随测量记录输入顺序变化。

当所有有效方位的拉应力和压应力绝对值都不超过资料中的工艺限值时，状态为 `PASS`；任一限值超出时为 `REJECT`。没有足够有效数据支持应力结论时为 `REVIEW`。最危险方位按应力绝对值最大确定，出现并列时选择数值较小的方位。测量记录的排列顺序改变后，报告内容应保持一致。参数数量不对或输入无法解析时，标准错误输出以 `用法: ` 或 `运行失败: ` 开头的单行信息并以非零状态退出。
