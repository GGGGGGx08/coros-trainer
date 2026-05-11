# 运动训练助手

这个项目是一个运动训练助手，可以从Coros读取训练数据，并基于专业的训练理念提供评价和指导。

## 功能

- 从Coros API获取训练数据
- 分析训练表现
- 提供个性化指导建议

## 安装

1. 克隆仓库
2. 安装依赖：pip install -r requirements.txt
3. 配置Coros账户信息：在.env文件中设置COROS_EMAIL、COROS_PASSWORD和COROS_REGION
4. 运行：python main.py

## 使用

运行脚本后，助手将自动获取最近30天的训练数据并生成报告。

## 注意

- 请确保.env文件不被提交到版本控制中（已通过.gitignore排除）
- Coros API为非公开API，可能随时更改
- 首次运行时会下载FIT文件，可能需要一些时间