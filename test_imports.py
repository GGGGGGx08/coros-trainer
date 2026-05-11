#!/usr/bin/env python
# -*- coding: utf-8 -*-
print("1. 脚本启动")

import sys
print(f"2. Python版本: {sys.version}")

try:
    import requests
    print("3. requests 导入成功")
except Exception as e:
    print(f"3. requests 导入失败: {e}")

try:
    import hashlib
    print("4. hashlib 导入成功")
except Exception as e:
    print(f"4. hashlib 导入失败: {e}")

try:
    import os
    print("5. os 导入成功")
except Exception as e:
    print(f"5. os 导入失败: {e}")

try:
    from dotenv import load_dotenv
    print("6. python-dotenv 导入成功")
except Exception as e:
    print(f"6. python-dotenv 导入失败: {e}")

try:
    import pandas as pd
    print("7. pandas 导入成功")
except Exception as e:
    print(f"7. pandas 导入失败: {e}")

try:
    import matplotlib.pyplot as plt
    print("8. matplotlib 导入成功")
except Exception as e:
    print(f"8. matplotlib 导入失败: {e}")

try:
    from fitparse import FitFile
    print("9. fitparse 导入成功")
except Exception as e:
    print(f"9. fitparse 导入失败: {e}")

print("10. 所有导入测试完成")
