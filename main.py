import requests
import hashlib
import json
import os
import re
from datetime import datetime, timedelta
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端，避免挂起
import matplotlib.pyplot as plt
from dotenv import load_dotenv
import fitdecode
from fitdecode import FitReader, FitDataMessage
import tempfile
import numpy as np
import warnings

# 抑制 fitdecode 对非标准 FIT 文件格式的警告
warnings.filterwarnings('ignore', message='invalid field size')

# 加载环境变量
load_dotenv()

class CorosAPI:
    def __init__(self, email: str, password: str, region: str = "europe"):
        self.email = email
        self.password = password
        self.access_token = None
        self.profile = {}  # 高驰个人训练指标

        # Regional endpoints
        self.regions = {
            "america": "https://teamapi.coros.com",
            "europe": "https://teameuapi.coros.com",
            "china": "https://teamcnapi.coros.com"
        }
        self.base_url = self.regions.get(region, self.regions["europe"])
        self.session = requests.Session()

    def login(self) -> bool:
        """Authenticate, get token, and extract COROS training profile"""
        url = f"{self.base_url}/account/login"
        pwd_hash = hashlib.md5(self.password.encode()).hexdigest()

        # 判断手机号还是邮箱: 纯数字为手机号(accountType=1)，含@为邮箱(accountType=2)
        if re.match(r'^\+?\d+$', self.email.strip()):
            account_type = 1
        elif '@' in self.email:
            account_type = 2
        else:
            print("[FAIL] 账号格式错误")
            return False

        payload = {"account": self.email, "accountType": account_type, "pwd": pwd_hash}

        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            if data.get("result") == "0000":
                user = data["data"]
                self.access_token = user["accessToken"]
                self.session.headers.update({"accesstoken": self.access_token})
                zone = user.get('zoneData', {})

                # 提取高驰训练指标 (参考高驰官网展示的指标)
                self.profile = {
                    'nickname': user.get('nickname', ''),
                    'max_hr': user.get('maxHr', 198),
                    'rest_hr': user.get('rhr', 45),
                    'lthr': zone.get('lthr', 174),       # 乳酸阈值心率
                    'ftp': zone.get('ftp', 180),           # 功能性阈值功率
                    'ltsp': zone.get('ltsp', 203),         # 乳酸阈值配速 (m/s的100倍)
                    'weight': user.get('weight', 72),
                    'stature': user.get('stature', 177),
                    # 心率区间
                    'hr_zone_maxhr': zone.get('maxHrZone', []),
                    'hr_zone_lthr': zone.get('lthrZone', []),
                    'hr_zone_rhr': zone.get('rhrZone', []),
                    # 配速区间 (value是m/s的100倍，需要转换)
                    'pace_zone': zone.get('ltspZone', []),
                    # 功率区间
                    'power_zone': zone.get('cyclePowerZone', []),
                    # 跑步成绩预测
                    'run_scores': user.get('runScoreList', []),
                }
                print("[OK] 登录成功")
                return True
            else:
                print(f"[FAIL] 登录失败: {data.get('message', '未知错误')}")
                return False
        except Exception as e:
            print(f"[FAIL] Login failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_profile(self) -> dict:
        """返回高驰个人训练指标"""
        return self.profile

    def get_activities(
        self,
        start_date: str = None,
        end_date: str = None,
        page: int = 1,
        page_size: int = 20,
        sport_types: list = None
    ) -> dict:
        """Query workout activities"""
        url = f"{self.base_url}/activity/query"

        params = {
            "size": page_size,
            "pageNumber": page
        }

        if start_date:
            params["startDay"] = start_date  # YYYYMMDD
        if end_date:
            params["endDay"] = end_date
        if sport_types:
            params["modeList"] = ",".join(sport_types)

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Failed to query activities: {e}")
            return {}

    def download_activity(
        self,
        label_id: str,
        sport_type: int,
        file_type: str = "fit"
    ) -> bytes:
        """Download activity file (FIT, TCX, GPX, etc.)"""
        url = f"{self.base_url}/activity/detail/download"

        # File type mapping
        file_types = {
            "fit": "4",
            "tcx": "3",
            "kml": "2",
            "gpx": "1",
            "csv": "0"
        }

        params = {
            "labelId": label_id,
            "sportType": sport_type,
            "fileType": file_types.get(file_type, "4")
        }

        try:
            response = self.session.post(url, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("result") == "0000":
                file_url = data["data"].get("fileUrl")
                if file_url:
                    file_response = self.session.get(file_url)
                    file_response.raise_for_status()
                    return file_response.content
            return None
        except Exception as e:
            print(f"Failed to download activity: {e}")
            return None

def parse_fit_file(fit_data):
    """Parse FIT file using fitdecode (robust, handles non-standard field sizes)"""
    temp_file_path = None
    try:
        temp_fd, temp_file_path = tempfile.mkstemp(suffix='.fit')
        with os.fdopen(temp_fd, 'wb') as f:
            f.write(fit_data)

        result = {}
        lap_dist = 0
        lap_dur = 0
        hr_list = []
        max_hr = 0
        calories = 0

        with FitReader(temp_file_path) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue

                name = frame.name

                # Session级别数据（优先级最高）
                if name == 'session':
                    for field in frame.fields:
                        if field.name == 'total_distance' and field.value is not None:
                            result['distance'] = float(field.value) / 1000  # m -> km
                        elif field.name == 'total_elapsed_time' and field.value is not None:
                            result['duration'] = float(field.value)
                        elif field.name == 'avg_heart_rate' and field.value is not None:
                            result['avg_heart_rate'] = float(field.value)
                        elif field.name == 'max_heart_rate' and field.value is not None:
                            result['max_heart_rate'] = float(field.value)
                        elif field.name == 'total_calories' and field.value is not None:
                            result['calories'] = float(field.value)
                        elif field.name == 'enhanced_avg_speed' and field.value is not None:
                            result['avg_speed'] = float(field.value)  # m/s
                        elif field.name == 'avg_speed' and field.value is not None and 'avg_speed' not in result:
                            result['avg_speed'] = float(field.value)
                        elif field.name == 'enhanced_max_speed' and field.value is not None:
                            result['max_speed'] = float(field.value)
                        elif field.name == 'max_speed' and field.value is not None and 'max_speed' not in result:
                            result['max_speed'] = float(field.value)
                    if 'distance' in result:
                        break  # Session data complete, stop

                # Lap级别数据（汇总）
                elif name == 'lap':
                    for field in frame.fields:
                        if field.name == 'total_distance' and field.value is not None:
                            lap_dist += float(field.value)
                        elif field.name == 'total_elapsed_time' and field.value is not None:
                            lap_dur += float(field.value)
                        elif field.name == 'avg_heart_rate' and field.value is not None:
                            hr_list.append(float(field.value))
                        elif field.name == 'max_heart_rate' and field.value is not None:
                            max_hr = max(max_hr, float(field.value))
                        elif field.name == 'total_calories' and field.value is not None:
                            calories += float(field.value)

                # Record级别心率
                elif name == 'record':
                    for field in frame.fields:
                        if field.name == 'heart_rate' and field.value is not None:
                            hr_list.append(float(field.value))

        # 如果没有session数据，用lap汇总
        if 'distance' not in result and lap_dist > 0:
            result['distance'] = lap_dist / 1000  # m -> km
        if 'duration' not in result and lap_dur > 0:
            result['duration'] = lap_dur
        if 'avg_heart_rate' not in result and hr_list:
            result['avg_heart_rate'] = sum(hr_list) / len(hr_list)
        if 'max_heart_rate' not in result and max_hr > 0:
            result['max_heart_rate'] = max_hr
        if 'calories' not in result and calories > 0:
            result['calories'] = calories

        return result

    except Exception as e:
        print(f"  FIT解析失败: {e}")
        return {}
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except (PermissionError, OSError):
                pass

# Coros API 运动类型映射 (根据实际API返回校准)
# Coros API endpoint /activity/query uses modeList for sport type filtering
# The sportType field in activity list may differ from modeList values
SPORT_TYPES = {
    # 跑步系列
    10: "跑步", 11: "越野跑", 12: "田径场跑步", 13: "室内跑步", 14: "跑步机",
    # 骑行系列
    20: "户外骑行", 21: "室内骑行", 22: "山地骑行", 23: "砾石骑行",
    # 游泳系列
    30: "公开水域游泳", 31: "泳池游泳",
    # 户外
    40: "健走", 41: "徒步", 42: "登山",
    # 健身
    50: "力量训练", 51: "有氧运动", 52: "瑜伽", 53: "跳绳", 54: "椭圆机",
    # 水上
    60: "划船", 61: "桨板", 62: "皮划艇",
    # 冬季
    70: "越野滑雪", 71: "单板滑雪", 72: "双板滑雪",
    # 综合
    80: "铁人三项", 90: "其他运动",
    # Coros实际返回的编号（与modeList不同，以实际为准）
    100: "跑步", 101: "户外跑步", 102: "田径场跑步", 103: "室内跑步",
    200: "公路骑行", 201: "室内骑行",
    300: "泳池游泳",
    400: "健走", 410: "徒步",
    500: "力量训练",
}


def get_coros_data(days: int = 30):
    email = os.getenv('COROS_EMAIL')
    password = os.getenv('COROS_PASSWORD')
    region = os.getenv('COROS_REGION', 'europe')

    if not email or not password:
        print("请在.env文件中设置COROS_EMAIL和COROS_PASSWORD")
        return []

    api = CorosAPI(email, password, region)
    if not api.login():
        print("登录失败，请检查账户信息")
        return []

    # 获取指定天数的活动
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    start_str = start_date.strftime('%Y%m%d')
    end_str = end_date.strftime('%Y%m%d')

    activities_data = api.get_activities(start_date=start_str, end_date=end_str, page_size=100)
    activities = activities_data.get('data', {}).get('dataList', [])

    if not activities:
        print("没有找到活动数据")
        return []

    # 下载并解析每个活动的详细数据
    detailed_activities = []
    for activity in activities:
        activity_name = activity.get('name', '未知')
        print(f"下载活动: {activity_name}")
        fit_data = api.download_activity(activity['labelId'], activity['sportType'])
        if fit_data:
            details = parse_fit_file(fit_data)
            activity.update(details)
        detailed_activities.append(activity)

    return detailed_activities

def analyze_training(activities):
    if not activities:
        print("没有找到训练数据")
        return

    df = pd.DataFrame(activities)

    # 统一日期字段: Coros API返回 date(YYYYMMDD整数) 和 startTime(Unix时间戳)
    if 'startTime' in df.columns:
        df['activity_date'] = pd.to_datetime(df['startTime'], unit='s')
    elif 'date' in df.columns:
        df['activity_date'] = pd.to_datetime(df['date'].astype(str).str.strip(), format='%Y%m%d', errors='coerce')
    else:
        df['activity_date'] = pd.NaT

    df['date'] = df['activity_date']

    # 映射运动类型名称
    df['sport_name'] = df['sportType'].map(SPORT_TYPES).fillna(f"其他({df['sportType']})")

    print("\n" + "=" * 60)
    print("                   训  练  总  结")
    print("=" * 60)
    print(f"  统计周期内活动数: {len(activities)} 次")

    # 按运动类型分组统计
    sport_stats = {}
    for stype, group in df.groupby('sportType'):
        name = SPORT_TYPES.get(stype, f"其他({stype})")
        total_dist = group['distance'].sum() if 'distance' in group.columns else 0
        total_dur = group['duration'].sum() if 'duration' in group.columns else 0
        count = len(group)
        avg_hr = group['avg_heart_rate'].mean() if 'avg_heart_rate' in group.columns else None
        sport_stats[name] = {
            'distance': total_dist, 'duration': total_dur,
            'count': count, 'avg_hr': avg_hr
        }

    print(f"\n  {'运动类型':<10} {'次数':>4}  {'距离(km)':>10}  {'时间(h)':>8}  {'平均心率':>8}")
    print(f"  {'-' * 48}")
    grand_dist = 0
    grand_dur = 0
    for name, stats in sport_stats.items():
        grand_dist += stats['distance']
        grand_dur += stats['duration']
        hr_str = f"{stats['avg_hr']:.0f} bpm" if stats['avg_hr'] and not np.isnan(stats['avg_hr']) else "N/A"
        print(f"  {name:<10} {stats['count']:>4}  {stats['distance']:>9.2f}  {stats['duration']/3600:>7.2f}  {hr_str:>8}")
    print(f"  {'-' * 48}")
    hr_str = f"{df['avg_heart_rate'].mean():.0f} bpm" if 'avg_heart_rate' in df.columns and not df['avg_heart_rate'].isna().all() else "N/A"
    print(f"  {'合计':<10} {len(activities):>4}  {grand_dist:>9.2f}  {grand_dur/3600:>7.2f}  {hr_str:>8}")

    # 跑步行分析 (主要关注)
    running_df = df[df['sportType'].isin([10, 11, 12, 13])]
    if len(running_df) > 0:
        print(f"\n  ── 跑步专项 ──")
        run_dist = running_df['distance'].sum() if 'distance' in running_df.columns else 0
        run_dur = running_df['duration'].sum() if 'duration' in running_df.columns else 0
        run_count = len(running_df)
        avg_pace = run_dur / 60 / (run_dist if run_dist > 0 else 1)  # min/km
        print(f"  跑步次数: {run_count}  总距离: {run_dist:.2f} km  平均配速: {avg_pace:.1f} min/km")

    # 心率区间分析
    if 'avg_heart_rate' in df.columns and df['avg_heart_rate'].notna().any():
        valid_hr = df['avg_heart_rate'].dropna()
        if len(valid_hr) > 0:
            print(f"\n  ── 心率分析 ──")
            print(f"  平均: {valid_hr.mean():.0f} bpm  "
                  f"最高: {valid_hr.max():.0f} bpm  "
                  f"最低: {valid_hr.min():.0f} bpm")

    print("=" * 60)

    # 调用专业指导
    provide_guidance(df, sport_stats, grand_dist, grand_dur)

    # 生成图表
    generate_charts(df)

    # 保存数据
    save_summary(df, sport_stats)


def provide_guidance(df, sport_stats, total_distance, total_duration):
    """基于训练学原理提供专业评价与指导"""
    print("\n" + "=" * 60)
    print("                 专  业  评  价  与  指  导")
    print("=" * 60)

    num_activities = len(df)
    days_span = 30
    if 'date' in df.columns and len(df) >= 2:
        days_span = max((df['date'].max() - df['date'].min()).days, 1)

    # 1. 训练频率评估
    freq_per_week = num_activities / (days_span / 7)
    print(f"\n  【训练频率】")
    print(f"  月训练 {num_activities} 次，约 {freq_per_week:.1f} 次/周")
    if freq_per_week >= 6:
        print(f"  → 频率很高，注意恢复质量，警惕过度训练信号（静息心率升高、睡眠质量下降）")
    elif freq_per_week >= 4:
        print(f"  → 频率良好，保持当前节奏，可适当加入1次低强度恢复训练")
    elif freq_per_week >= 2:
        print(f"  → 频率偏低，建议逐步增加到每周3-4次，建立规律训练习惯")
    else:
        print(f"  → 频率较低，先从每周2-3次短时间训练开始建立习惯")

    # 2. 训练量评估
    weekly_dist = total_distance / (days_span / 7)
    total_hours = total_duration / 3600
    print(f"\n  【训练量】")
    print(f"  总距离: {total_distance:.1f} km，总时间: {total_hours:.1f} h，周均距离: {weekly_dist:.1f} km")
    if weekly_dist > 50:
        print(f"  → 训练量充足，接近或达到业余精英水平，注意周期化安排")
    elif weekly_dist > 30:
        print(f"  → 训练量良好，适合半马/全马备赛基础期。可加入间歇/节奏跑等强度训练")
    elif weekly_dist > 15:
        print(f"  → 训练量中等，适合10K-半马目标。保持每周1次长距离+1次速度训练的结构")
    else:
        print(f"  → 训练量偏少，优先增加训练频次和每次时长，而非速度")

    # 3. 心率与强度
    if 'avg_heart_rate' in df.columns and df['avg_heart_rate'].notna().any():
        avg_hr = df['avg_heart_rate'].dropna().mean()
        max_hr = df['avg_heart_rate'].dropna().max()
        print(f"\n  【训练强度】")
        print(f"  平均心率: {avg_hr:.0f} bpm，最高单次平均心率: {max_hr:.0f} bpm")
        if avg_hr > 155:
            print(f"  → 整体强度偏高。建议80%训练在低强度有氧区（<145 bpm），20%在高强度区")
            print(f"    这是当今主流训练理念「极化训练」或「金字塔训练」的核心原则")
        elif avg_hr > 135:
            print(f"  → 强度适中，处于有氧耐力发展区。可每周加入1-2次间歇/节奏训练")
        else:
            print(f"  → 强度偏低，若以提升成绩为目标，可适当增加中高强度训练比例")

    # 4. 运动多样性
    sport_types = list(set(df['sportType']))
    if len(sport_types) >= 3:
        print(f"\n  【运动多样性】")
        names = [SPORT_TYPES.get(s, str(s)) for s in sport_types]
        print(f"  包含 {len(sport_types)} 种运动: {', '.join(names)}")
        print(f"  → 交叉训练有助于全身协调发展，降低单一运动损伤风险，非常好！")
    elif len(sport_types) == 2:
        print(f"\n  【运动多样性】")
        names = [SPORT_TYPES.get(s, str(s)) for s in sport_types]
        print(f"  包含 {len(sport_types)} 种运动: {', '.join(names)}")
        print(f"  → 可考虑加入游泳或力量训练作为补充")

    print(f"\n  【核心原则提醒】")
    print(f"  • 渐进超负荷: 每周训练量增加不超过10%，避免受伤")
    print(f"  • 超量恢复: 训练效果在休息中产生，而非训练中")
    print(f"  • 周期化: 3周递增+1周减量恢复，避免持续高强度")
    print(f"  • 体感优先: 数据是参考，身体感受才是最好的教练")
    print("=" * 60)

def generate_charts(df):
    """生成多子图训练图表"""
    if 'date' not in df.columns:
        print("(无日期数据，跳过图表生成)")
        return

    df = df.sort_values('date')

    # 创建中文字体设置，避免乱码
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    base_dir = os.path.dirname(__file__)

    # 子图1: 距离趋势
    ax1 = axes[0, 0]
    if 'distance' in df.columns:
        ax1.bar(range(len(df)), df['distance'].fillna(0), color='steelblue', alpha=0.8)
        ax1.set_title('Training Distance per Session')
        ax1.set_ylabel('Distance (km)')
        ax1.set_xlabel('Session #')
        avg = df['distance'].mean()
        ax1.axhline(y=avg, color='red', linestyle='--', alpha=0.5,
                    label=f'Avg: {avg:.2f} km')
        ax1.legend()
    else:
        ax1.text(0.5, 0.5, 'No distance data', ha='center', va='center')
        ax1.set_title('Distance Trend')

    # 子图2: 运动类型分布 (饼图)
    ax2 = axes[0, 1]
    sport_counts = df['sport_name'].value_counts()
    colors = plt.cm.Set3(range(len(sport_counts)))
    ax2.pie(
        sport_counts.values, labels=sport_counts.index,
        autopct='%1.1f%%', colors=colors, startangle=90
    )
    ax2.set_title('Sport Type Distribution')

    # 子图3: 心率趋势
    ax3 = axes[1, 0]
    if 'avg_heart_rate' in df.columns and df['avg_heart_rate'].notna().any():
        valid = df[df['avg_heart_rate'].notna()]
        ax3.plot(valid['date'], valid['avg_heart_rate'], 'o-', color='coral',
                 markersize=8, linewidth=1.5)
        ax3.fill_between(range(len(valid)), 0, valid['avg_heart_rate'],
                         alpha=0.2, color='coral')
        ax3.set_title('Avg Heart Rate Trend')
        ax3.set_ylabel('Heart Rate (bpm)')
        ax3.set_xlabel('Date')
        ax3.axhline(y=140, color='orange', linestyle='--', alpha=0.4,
                    label='Aerobic zone (~140)')
        ax3.axhline(y=160, color='red', linestyle='--', alpha=0.3,
                    label='Threshold zone (~160)')
        ax3.legend(fontsize=8)
        fig.autofmt_xdate(rotation=30)
    else:
        ax3.text(0.5, 0.5, 'No heart rate data', ha='center', va='center')
        ax3.set_title('Heart Rate Trend')

    # 子图4: 配速分析 (仅跑步类)
    ax4 = axes[1, 1]
    running_types = [10, 11, 12, 13]
    running = df[df['sportType'].isin(running_types)].copy()
    if len(running) > 0 and 'distance' in running.columns and 'duration' in running.columns:
        running['pace'] = (running['duration'] / 60) / running['distance'].clip(lower=0.01)
        ax4.bar(range(len(running)), running['pace'], color='teal', alpha=0.7)
        ax4.set_title('Running Pace per Session')
        ax4.set_ylabel('Pace (min/km)')
        ax4.set_xlabel('Session #')
        if len(running) >= 2:
            avg_pace = running['pace'].mean()
            ax4.axhline(y=avg_pace, color='red', linestyle='--', alpha=0.5,
                        label=f'Avg pace: {avg_pace:.1f} min/km')
            ax4.legend()
        ax4.invert_yaxis()
    else:
        ax4.text(0.5, 0.5, 'No running data', ha='center', va='center')
        ax4.set_title('Running Pace')

    plt.tight_layout(pad=2.5)
    chart_path = os.path.join(base_dir, 'training_chart.png')
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    print(f"\n  [图表已保存] {chart_path}")
    plt.close()


def save_summary(df, sport_stats):
    """保存训练摘要到JSON文件"""
    base_dir = os.path.dirname(__file__)
    summary = {
        'report_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'total_activities': len(df),
        'sport_breakdown': {
            name: {k: (round(v, 2) if isinstance(v, (int, float, np.floating)) else v) for k, v in stats.items()}
            for name, stats in sport_stats.items()
        }
    }

    # 处理numpy类型
    for name, stats in summary['sport_breakdown'].items():
        for k, v in stats.items():
            if isinstance(v, (np.floating,)):
                stats[k] = float(v)
            elif isinstance(v, (np.integer,)):
                stats[k] = int(v)

    summary_path = os.path.join(base_dir, 'training_summary.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"  [摘要已保存] {summary_path}")



if __name__ == "__main__":
    # Windows下设置UTF-8编码避免中文/特殊字符乱码
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("开始训练助手...")
    try:
        activities = get_coros_data()
        print(f"获取到 {len(activities)} 个活动")
        analyze_training(activities)
        print("分析完成")
    except Exception as e:
        print(f"发生错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()