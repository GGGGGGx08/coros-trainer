# COROS 训练助手 Pro

基于 **杰克·丹尼尔斯经典跑步训练法** 的智能训练分析平台。连接 COROS 设备，获取 AI 驱动的个性化训练指导。

## 功能

- **数据同步** — 登录 COROS 账号，一键同步训练记录（数据自动缓存）
- **丹尼尔斯配速** — 基于 COROS 实测乳酸阈值(LTSP)推导 E/M/T/I/R 五级配速
- **AI 教练** — Claude 驱动的实时训练分析和问答
- **训练计划** — AI 根据个人指标、天气、目标定制周期计划
- **可视化看板** — 交互式图表：距离、心率、配速、运动分布、周热力图
- **天气感知** — 实时天气融入训练建议
- **多用户支持** — 各自登录自己的 COROS 账号，数据隔离

## 使用

```bash
pip install -r requirements.txt
streamlit run app.py
```

打开浏览器访问 http://localhost:8501

## 部署到 Streamlit Cloud（免费）

1. Fork 此仓库到你的 GitHub
2. 打开 [share.streamlit.io](https://share.streamlit.io)
3. New app → 选择仓库 → Main file: `app.py` → Deploy

## 技术栈

Python · Streamlit · Plotly · Claude AI · COROS API · FIT Protocol
