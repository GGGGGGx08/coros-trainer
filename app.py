"""
COROS 训练助手 Pro — 丹尼尔斯训练法 · AI教练 · 实时天气
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import os
import sys
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

from main import CorosAPI, parse_fit_file, SPORT_TYPES

# ==================== 页面配置 ====================
st.set_page_config(
    page_title="COROS 训练助手 Pro",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== 样式 ====================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif; }

    /* 主色调 */
    :root {
        --primary: #6366f1;
        --success: #10b981;
        --warning: #f59e0b;
        --danger: #ef4444;
    }

    /* 卡片 */
    .glass-card {
        background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
        border-radius: 16px; padding: 24px; color: white;
        box-shadow: 0 4px 24px rgba(99, 102, 241, 0.25);
    }
    .glass-card.green { background: linear-gradient(135deg, #10b981 0%, #059669 100%); box-shadow: 0 4px 24px rgba(16, 185, 129, 0.25); }
    .glass-card.amber { background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); box-shadow: 0 4px 24px rgba(245, 158, 11, 0.25); }
    .glass-card.rose { background: linear-gradient(135deg, #f43f5e 0%, #e11d48 100%); box-shadow: 0 4px 24px rgba(244, 63, 94, 0.25); }

    /* 训练计划卡片 */
    .plan-card {
        background: #f8fafc; border-left: 4px solid #6366f1;
        padding: 16px 20px; border-radius: 8px; margin: 8px 0;
    }
    .plan-card.e { border-left-color: #10b981; }
    .plan-card.t { border-left-color: #f59e0b; }
    .plan-card.i { border-left-color: #ef4444; }

    /* 提示框 */
    .insight { background: #eef2ff; border-radius: 10px; padding: 16px 20px;
               border: 1px solid #c7d2fe; margin: 10px 0; }

    /* 分区标头 */
    .section-title {
        font-size: 18px; font-weight: 600; color: #1e293b;
        margin: 24px 0 12px 0; padding-bottom: 8px;
        border-bottom: 2px solid #6366f1; display: inline-block;
    }

    /* 隐藏Streamlit默认元素 */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    .stDeployButton { display: none; }
</style>
""", unsafe_allow_html=True)

# ==================== 工具函数 ====================
def pace_to_str(pace_min: float) -> str:
    """小数分钟/公里 → M:SS"""
    if pace_min is None or pace_min <= 0 or np.isnan(pace_min):
        return "--:--"
    m = int(pace_min)
    s = int((pace_min - m) * 60 + 0.5)
    if s >= 60:
        m += 1; s -= 60
    return f"{m}:{s:02d}"


def sec_per_km_to_pace_str(sec: float) -> str:
    """秒/公里 → M:SS格式"""
    if sec is None or sec <= 0:
        return "--:--"
    m = int(sec / 60)
    s = int(sec % 60 + 0.5)
    if s >= 60:
        m += 1; s -= 60
    return f"{m}:{s:02d}"


def daniels_paces_from_coros(coros_profile: dict) -> dict:
    """
    使用高驰实测 LTSP (乳酸阈值配速) 推导丹尼尔斯五级配速。
    数据来源：高驰账号中的 ltspZone 配速区间（基于实际训练数据和心率测量）。

    COROS 配速区间 → 丹尼尔斯映射:
      Zone 0 (73.5% LTSP) → E 轻松跑 (最慢)
      Zone 1 (87.8% LTSP) → E/M 过渡
      Zone 2 (94.4% LTSP) → M 马拉松配速
      Zone 3 (100%  LTSP) → T 阈值跑
      Zone 4 (102%  LTSP) → I 间歇跑
      Zone 5 (110.3% LTSP) → R 重复跑 (最快)
    """
    pace_zones = coros_profile.get('pace_zone', [])
    if not pace_zones or len(pace_zones) < 5:
        return {}

    # 提取各区间配速 (单位: 秒/公里)
    # COROS pace 字段是 LTSP / ratio * 100
    z = {}
    for pz in pace_zones:
        idx = pz.get('index', 0)
        pace_sec = pz.get('pace', 0)  # 秒/公里
        ratio = pz.get('ratio', 100)
        z[idx] = {'pace': pace_sec, 'ratio': ratio}

    if 3 not in z:
        return {}

    ltsp_sec = z[3]['pace']  # 乳酸阈值配速 (100%)

    # 丹尼尔斯五级配速区间 (基于高驰实测阈值)
    # E 轻松跑: Zone 0 (73.5%) ~ Zone 1 (87.8%) of LTSP
    e_slow_sec = z[0]['pace'] if 0 in z else ltsp_sec / 0.735
    e_fast_sec = z[1]['pace'] if 1 in z else ltsp_sec / 0.878

    # M 马拉松: Zone 1 (87.8%) ~ Zone 2 (94.4%)
    m_slow_sec = z[1]['pace'] if 1 in z else ltsp_sec / 0.878
    m_fast_sec = z[2]['pace'] if 2 in z else ltsp_sec / 0.944

    # T 阈值: Zone 2 (94.4%) ~ Zone 3 (100%)
    t_slow_sec = z[2]['pace'] if 2 in z else ltsp_sec / 0.944
    t_fast_sec = ltsp_sec

    # I 间歇: Zone 3 (100%) ~ Zone 4 (102%)
    i_slow_sec = ltsp_sec
    i_fast_sec = z[4]['pace'] if 4 in z else ltsp_sec / 1.02

    # R 重复: Zone 5 (110.3%)
    r_pace_sec = z[5]['pace'] if 5 in z else ltsp_sec / 1.103

    # R配速转换: 秒/km → 400m和800m用时(秒)
    r_400 = round(r_pace_sec * 0.4)
    r_800 = round(r_pace_sec * 0.8)

    return {
        'ltsp': ltsp_sec,
        'ltsp_str': sec_per_km_to_pace_str(ltsp_sec),
        'source': 'COROS LTSP (高驰实测乳酸阈值)',
        'E_range': f"{sec_per_km_to_pace_str(e_fast_sec)}-{sec_per_km_to_pace_str(e_slow_sec)}",
        'M_range': f"{sec_per_km_to_pace_str(m_fast_sec)}-{sec_per_km_to_pace_str(m_slow_sec)}",
        'T_range': f"{sec_per_km_to_pace_str(t_fast_sec)}-{sec_per_km_to_pace_str(t_slow_sec)}",
        'I_range': f"{sec_per_km_to_pace_str(i_fast_sec)}-{sec_per_km_to_pace_str(i_slow_sec)}",
        'R_400': str(r_400),
        'R_800': str(r_800),
        # 保留数值用于计算
        '_E_fast': e_fast_sec / 60,  # 转为min/km
        '_T_slow': t_slow_sec / 60,
    }


def process_df(activities):
    """活动列表 → DataFrame"""
    if not activities:
        return None
    df = pd.DataFrame(activities)

    if 'startTime' in df.columns and df['startTime'].notna().any():
        df['date'] = pd.to_datetime(df['startTime'], unit='s')
    elif 'date' in df.columns:
        try:
            df['date'] = pd.to_datetime(df['date'].astype(str).str.strip(), format='%Y%m%d', errors='coerce')
        except Exception:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')

    if 'distance' in df.columns and df['distance'].median() > 500:
        df['distance'] = df['distance'] / 1000
    if 'duration' in df.columns and df['duration'].median() > 100000:
        df['duration'] = df['duration'] / 1000

    df['sport_name'] = df['sportType'].map(SPORT_TYPES).fillna(
        df['sportType'].apply(lambda x: f"运动({x})"))

    if 'distance' in df.columns and 'duration' in df.columns:
        mask = (df['distance'].fillna(0) > 0.01) & (df['duration'].fillna(0) > 0)
        df.loc[mask, 'pace'] = (df.loc[mask, 'duration'] / 60) / df.loc[mask, 'distance']
        df.loc[mask, 'speed_kmh'] = df.loc[mask, 'distance'] / (df.loc[mask, 'duration'] / 3600)
    return df


def fetch_weather(lat=34.26, lon=108.94):
    """免费天气API"""
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        url += "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
        url += "&daily=temperature_2m_max,temperature_2m_min&timezone=Asia/Shanghai&forecast_days=3"
        r = requests.get(url, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def weather_desc(code: int) -> str:
    m = {0: "☀️ 晴", 1: "🌤 晴间多云", 2: "⛅ 多云", 3: "☁️ 阴",
         45: "🌫 雾", 51: "🌦 小雨", 61: "🌧 雨", 71: "🌨 雪", 95: "⛈ 雷暴"}
    return m.get(code, f"🌡")


def build_summary(df) -> str:
    if df is None or len(df) == 0:
        return "无数据"
    lines = [f"周期: {df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}",
             f"总计 {len(df)} 次"]
    for stype, g in df.groupby('sportType'):
        name = SPORT_TYPES.get(stype, f"运动{stype}")
        d = g['distance'].sum() if 'distance' in g.columns else 0
        t = g['duration'].sum() if 'duration' in g.columns else 0
        h = g['avg_heart_rate'].mean() if 'avg_heart_rate' in g.columns else None
        hr = f", HR{int(h)}" if h and not np.isnan(h) else ""
        lines.append(f"  {name}: {len(g)}次, {d:.1f}km, {t/3600:.1f}h{hr}")
    return "\n".join(lines)


def call_claude(sys_prompt: str, msg: str, max_tok=2000) -> str | None:
    key = os.getenv('ANTHROPIC_API_KEY') or st.session_state.get('api_key', '')
    if not key:
        return None
    try:
        from anthropic import Anthropic
        c = Anthropic(api_key=key)
        r = c.messages.create(model="claude-sonnet-4-6", max_tokens=max_tok,
                              system=sys_prompt, messages=[{"role": "user", "content": msg}])
        return r.content[0].text
    except Exception as e:
        return f"AI服务异常: {e}"


# ==================== 初始化 & 缓存 ====================
CACHE_FILE = os.path.join(os.path.dirname(__file__), '.training_cache.pkl')

def load_cache():
    """从磁盘加载缓存的训练数据"""
    if os.path.exists(CACHE_FILE):
        try:
            import pickle
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)
        except Exception:
            return None
    return None

def save_cache(activities, profile):
    """保存训练数据到磁盘"""
    try:
        import pickle
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump({'activities': activities, 'profile': profile}, f)
    except Exception:
        pass

for k, v in {'activities': None, 'df': None, 'loaded': False, 'chat': [],
             'profile': {}, 'weather': None, 'api_key': os.getenv('ANTHROPIC_API_KEY', ''),
             'coros_logged_in': False, 'coros_api': None, 'coros_profile': {}}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# 启动时尝试加载缓存
if not st.session_state.loaded:
    cached = load_cache()
    if cached:
        st.session_state.activities = cached.get('activities')
        st.session_state.coros_profile = cached.get('profile', {})
        if st.session_state.activities:
            st.session_state.df = process_df(st.session_state.activities)
            st.session_state.loaded = True

# ==================== 侧边栏 ====================
with st.sidebar:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
        <div style="font-size:36px">🏃</div>
        <div>
            <div style="font-size:20px;font-weight:700;color:#6366f1">COROS 训练助手</div>
            <div style="font-size:12px;color:#64748b">Daniels Method · AI Coach</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # === COROS 登录 ===
    with st.expander("🔐 COROS 登录", expanded=not st.session_state.coros_logged_in):
        coros_account = st.text_input("手机号/邮箱", placeholder="手机号或邮箱")
        coros_pwd = st.text_input("密码", type="password", placeholder="输入密码")
        coros_region = st.selectbox("区域", ["china", "europe", "america"],
                                    format_func=lambda x: {"china": "🇨🇳 中国", "europe": "🇪🇺 欧洲", "america": "🇺🇸 美洲"}[x])

        if st.button("登录 COROS", use_container_width=True, type="primary"):
            with st.spinner("登录中..."):
                api = CorosAPI(coros_account, coros_pwd, coros_region)
                if api.login():
                    st.session_state.coros_api = api
                    st.session_state.coros_logged_in = True
                    st.session_state.coros_profile = api.get_profile()
                    st.success("登录成功！")
                else:
                    st.session_state.coros_logged_in = False
                    st.error("登录失败，请检查账号密码")

        if st.session_state.coros_logged_in:
            cp = st.session_state.coros_profile
            st.success(f"已登录 ✅ {cp.get('nickname', '')}")
            # 显示高驰关键指标
            if cp:
                with st.expander("📊 个人指标", expanded=False):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.metric("最大心率", f"{cp.get('max_hr','?')} bpm")
                        st.metric("静息心率", f"{cp.get('rest_hr','?')} bpm")
                        st.metric("乳酸阈值心率(LTHR)", f"{cp.get('lthr','?')} bpm")
                    with c2:
                        st.metric("体重", f"{cp.get('weight','?')} kg")
                        st.metric("FTP", f"{cp.get('ftp','?')} W")
                        ltsp_val = cp.get('ltsp', 0)
                        st.metric("阈值配速(LTSP)", f"{sec_per_km_to_pace_str(ltsp_val)}/km")

    st.divider()

    # === 数据获取 ===
    st.markdown("**📡 数据获取**")
    custom_date = st.checkbox("自定义日期", False)
    if custom_date:
        c1, c2 = st.columns(2)
        with c1:
            sd = st.date_input("开始", datetime.now() - timedelta(30))
        with c2:
            ed = st.date_input("结束", datetime.now())
        start_str = sd.strftime('%Y%m%d')
        end_str = ed.strftime('%Y%m%d')
        days_val = None
    else:
        days_val = st.slider("获取最近N天", 7, 180, 30, 7)
        start_str = end_str = None

    if st.button("🔄 同步 COROS 数据", use_container_width=True):
        if not st.session_state.coros_logged_in:
            st.error("请先登录 COROS 账号")
        else:
            with st.spinner("正在同步训练数据..."):
                api = st.session_state.coros_api
                if not start_str:
                    ed2 = datetime.now()
                    sd2 = ed2 - timedelta(days=days_val or 30)
                    start_str = sd2.strftime('%Y%m%d')
                    end_str = ed2.strftime('%Y%m%d')

                raw = api.get_activities(start_date=start_str, end_date=end_str, page_size=200)
                acts = raw.get('data', {}).get('dataList', [])
                if not acts:
                    st.error("无活动数据")
                else:
                    detailed = []
                    bar = st.progress(0, "下载中...")
                    for i, act in enumerate(acts):
                        fit = api.download_activity(act['labelId'], act['sportType'])
                        if fit:
                            act.update(parse_fit_file(fit))
                        detailed.append(act)
                        bar.progress((i+1)/len(acts), f"下载 {i+1}/{len(acts)}")
                    bar.empty()
                    st.session_state.activities = detailed
                    st.session_state.df = process_df(detailed)
                    st.session_state.loaded = True
                    save_cache(detailed, st.session_state.coros_profile)
                    st.success(f"成功获取 {len(detailed)} 条记录！数据已缓存")

    # FIT上传
    uploads = st.file_uploader("或上传FIT文件", type=['fit'], accept_multiple_files=True)
    if uploads and st.button("解析上传文件", use_container_width=True):
        manual = []
        for f in uploads:
            manual.append({'name': f.name.replace('.fit', ''), 'startDay': datetime.now().strftime('%Y%m%d'),
                           'sportType': 10, **parse_fit_file(f.read())})
        st.session_state.activities = manual
        st.session_state.df = process_df(manual)
        st.session_state.loaded = True
        st.rerun()

    st.divider()

    # === 个人档案 ===
    st.markdown("**👤 个人档案**")
    with st.expander("编辑", expanded=False):
        p = st.session_state.profile
        p['age'] = st.number_input("年龄", 10, 80, p.get('age', 22))
        p['weight'] = st.number_input("体重(kg)", 30, 200, p.get('weight', 72))
        p['height'] = st.number_input("身高(cm)", 100, 250, p.get('height', 177))
        c1, c2 = st.columns(2)
        with c1: p['max_hr'] = st.number_input("最大心率", 120, 240, p.get('max_hr', 198))
        with c2: p['rest_hr'] = st.number_input("静息心率", 30, 120, p.get('rest_hr', 45))
        goals = ["健康跑", "5K完赛", "10K完赛", "半马完赛", "全马完赛", "提升速度", "减肥塑形"]
        p['goal'] = st.selectbox("目标", goals, goals.index(p.get('goal', '健康跑')) if p.get('goal') in goals else 0)
        levels = ["新手(<1年)", "中级(1-3年)", "高级(3-5年)", "精英(>5年)"]
        p['level'] = st.selectbox("水平", levels, levels.index(p.get('level', '新手(<1年)')) if p.get('level') in levels else 0)
        p['notes'] = st.text_area("伤病/备注", p.get('notes', ''))

    st.divider()

    # === 天气 ===
    st.markdown("**🌤 天气**")
    if st.button("获取实时天气", use_container_width=True):
        st.session_state.weather = fetch_weather()
    if st.session_state.weather:
        w = st.session_state.weather
        c = w.get('current', {})
        st.caption(f"{weather_desc(c.get('weather_code',0))} {c.get('temperature_2m','?')}°C | 💧{c.get('relative_humidity_2m','?')}% | 💨{c.get('wind_speed_10m','?')}km/h")

    st.divider()

    # === AI Key ===
    st.markdown("**🤖 AI Key**")
    if st.session_state.api_key:
        st.success("已配置 ✅")
    else:
        with st.expander("配置 Key", expanded=False):
            k = st.text_input("Anthropic API Key", type="password", placeholder="sk-ant-...")
            if k and st.button("保存", use_container_width=True):
                st.session_state.api_key = k
                os.environ['ANTHROPIC_API_KEY'] = k
                st.rerun()

    if st.button("🗑 清空数据", use_container_width=True):
        for k in list(st.session_state.keys()):
            if k not in ('coros_api', 'coros_logged_in', 'api_key', 'profile', 'weather', 'coros_profile'):
                del st.session_state[k]
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
        st.session_state.loaded = False
        st.rerun()

    st.caption("v3.0 · Powered by Claude")

# ==================== 主页 ====================
if not st.session_state.loaded:
    st.title("🏃 COROS 训练助手 Pro")
    st.markdown("""
    <div style="max-width:700px;margin:24px 0">
        <p style="font-size:18px;color:#475569;line-height:1.8">
        基于 <b>杰克·丹尼尔斯经典跑步训练法</b> 的智能训练分析平台。
        连接你的 COROS 设备，获取 AI 驱动的个性化训练指导。
        </p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("""
        <div class="glass-card" style="text-align:center">
            <div style="font-size:32px;margin-bottom:8px">📊</div>
            <div style="font-weight:600;margin-bottom:4px">数据同步</div>
            <div style="font-size:13px;opacity:0.9">登录一次，数据自动缓存</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div class="glass-card green" style="text-align:center">
            <div style="font-size:32px;margin-bottom:8px">📐</div>
            <div style="font-weight:600;margin-bottom:4px">VDOT + COROS</div>
            <div style="font-size:13px;opacity:0.9">丹尼尔斯配速 + 高驰训练区间</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown("""
        <div class="glass-card amber" style="text-align:center">
            <div style="font-size:32px;margin-bottom:8px">🤖</div>
            <div style="font-weight:600;margin-bottom:4px">AI教练</div>
            <div style="font-size:13px;opacity:0.9">结合个人指标和天气的智能指导</div>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        st.markdown("""
        <div class="glass-card rose" style="text-align:center">
            <div style="font-size:32px;margin-bottom:8px">📅</div>
            <div style="font-weight:600;margin-bottom:4px">训练计划</div>
            <div style="font-size:13px;opacity:0.9">AI定制丹尼尔斯周期计划</div>
        </div>
        """, unsafe_allow_html=True)

    st.info("👈 开始：左侧 **登录COROS** → **同步数据**（仅需一次）→ 之后自动加载缓存")
    st.stop()

# ==================== 数据加载后 ====================
df = st.session_state.df
profile = st.session_state.profile

# KPI
ta = len(df)
td = df['distance'].sum() if 'distance' in df.columns else 0
tt = df['duration'].sum() if 'duration' in df.columns else 0
ah = df['avg_heart_rate'].mean() if 'avg_heart_rate' in df.columns and df['avg_heart_rate'].notna().any() else 0
ds = f"{df['date'].min().strftime('%m/%d')} - {df['date'].max().strftime('%m/%d')}" if 'date' in df.columns else "N/A"

c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.metric("活动次数", ta)
with c2: st.metric("总距离", f"{td:.1f} km")
with c3: st.metric("总时间", f"{tt/3600:.1f} h")
with c4: st.metric("平均心率", f"{ah:.0f}" if ah > 0 else "N/A")
with c5: st.metric("日期范围", ds)

# 配速信息条 (优先使用COROS实测数据)
cp = st.session_state.coros_profile
paces = daniels_paces_from_coros(cp) if cp else {}

if paces:
    st.markdown(f"""
    <div class="insight">
        <b>丹尼尔斯配速</b> (数据源: <b>{paces['source']}</b>) &nbsp;|&nbsp;
        阈值: {paces['ltsp_str']}/km &nbsp;|&nbsp;
        E: {paces['E_range']}/km &nbsp;|&nbsp;
        M: {paces['M_range']}/km &nbsp;|&nbsp;
        T: {paces['T_range']}/km &nbsp;|&nbsp;
        I: {paces['I_range']}/km &nbsp;|&nbsp;
        R400: {paces['R_400']}s &nbsp;|&nbsp;
        R800: {paces['R_800']}s
    </div>
    """, unsafe_allow_html=True)
elif cp:
    st.markdown(f"""
    <div class="insight">
        <b>COROS 个人指标</b> &nbsp;|&nbsp;
        最大HR: {cp.get('max_hr','?')} &nbsp;|&nbsp;
        静息HR: {cp.get('rest_hr','?')} &nbsp;|&nbsp;
        LTHR: {cp.get('lthr','?')} &nbsp;|&nbsp;
        LTSP: {sec_per_km_to_pace_str(cp.get('ltsp',0) if cp.get('ltsp',0)>100 else 0)}/km
    </div>
    """, unsafe_allow_html=True)

st.divider()

# ==================== Tabs ====================
t1, t2, t3, t4, t5 = st.tabs(["📊 数据看板", "📋 活动列表", "🤖 AI教练", "📅 训练计划", "📐 丹尼尔斯指导"])

# === Tab 1: 看板 ===
with t1:
    cl, cr = st.columns(2)
    with cl:
        if 'distance' in df.columns and 'date' in df.columns:
            dp = df.sort_values('date')
            cmap = {'跑步': '#6366f1', '田径场跑步': '#8b5cf6', '越野跑': '#a78bfa',
                    '室内跑步': '#c4b5fd', '跑步机': '#ddd6fe', '户外跑步': '#818cf8',
                    '户外骑行': '#0ea5e9', '公路骑行': '#38bdf8', '室内骑行': '#7dd3fc',
                    '泳池游泳': '#06b6d4', '公开水域游泳': '#22d3ee',
                    '健走': '#10b981', '徒步': '#34d399', '力量训练': '#f59e0b', '瑜伽': '#a78bfa'}
            colors = dp['sport_name'].map(lambda x: cmap.get(x, '#94a3b8'))
            fig = go.Figure()
            fig.add_trace(go.Bar(x=dp['date'], y=dp['distance'].fillna(0),
                                 marker_color=colors, text=dp['sport_name'],
                                 hoverinfo="text+y", textposition="none",
                                 marker_line_width=0))
            avg = dp['distance'].mean()
            fig.add_hline(y=avg, line_dash="dash", line_color="#ef4444",
                          annotation_text=f"均值 {avg:.1f}km")
            fig.update_layout(title="每日训练距离", xaxis_title="", yaxis_title="km",
                              height=380, margin=dict(l=10, r=10, t=40, b=10),
                              plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)

    with cr:
        if 'avg_heart_rate' in df.columns and df['avg_heart_rate'].notna().any():
            hr_d = df.sort_values('date').dropna(subset=['avg_heart_rate'])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=hr_d['date'], y=hr_d['avg_heart_rate'],
                                     mode='lines+markers', marker_size=8,
                                     line=dict(color='#ef4444', width=2, shape='spline')))
            max_hr = profile.get('max_hr', 198)
            rest_hr = profile.get('rest_hr', 45)
            e_top = rest_hr + (max_hr - rest_hr) * 0.79
            t_top = rest_hr + (max_hr - rest_hr) * 0.92
            fig.add_hrect(y0=0, y1=e_top, line_width=0, fillcolor="#10b981", opacity=0.06)
            fig.add_hrect(y0=e_top, y1=t_top, line_width=0, fillcolor="#f59e0b", opacity=0.06)
            fig.add_hrect(y0=t_top, y1=max_hr+10, line_width=0, fillcolor="#ef4444", opacity=0.06)
            fig.update_layout(title="心率趋势 (🟢E区 🟡M/T区 🔴I区)",
                              xaxis_title="", yaxis_title="bpm", height=380,
                              margin=dict(l=10, r=10, t=40, b=10),
                              plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)

    cl2, cr2 = st.columns(2)
    with cl2:
        sc = df['sport_name'].value_counts()
        fig = px.pie(values=sc.values, names=sc.index, hole=0.45,
                     color_discrete_sequence=px.colors.qualitative.Pastel)
        fig.update_traces(textinfo='percent+label', textfont_size=11)
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10),
                          paper_bgcolor='rgba(0,0,0,0)')
        fig.add_annotation(text=f"{ta}次", x=0.5, y=0.5, showarrow=False, font_size=20)
        st.plotly_chart(fig, use_container_width=True)

    with cr2:
        run_types = [10, 11, 12, 13, 14, 100, 101, 102, 103]
        run_df = df[df['sportType'].isin(run_types)].sort_values('date')
        if len(run_df) > 0 and 'pace' in run_df.columns:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=run_df['date'], y=run_df['pace'],
                                 marker_color='#6366f1', marker_line_width=0,
                                 text=[f"{pace_to_str(p)}/km" if p == p else '' for p in run_df['pace']],
                                 hoverinfo="text"))
            avg_p = run_df['pace'].mean()
            fig.add_hline(y=avg_p, line_dash="dash", line_color="#ef4444",
                          annotation_text=f"均值 {pace_to_str(avg_p)}/km")
            fig.update_layout(title="跑步配速趋势 (↓越快)", xaxis_title="",
                              yaxis_title="配速", height=360, yaxis=dict(autorange="reversed"),
                              margin=dict(l=10, r=10, t=30, b=10),
                              plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)

    # 周热力图
    if 'date' in df.columns and 'distance' in df.columns:
        dw = df.copy()
        dw['weekday'] = dw['date'].dt.dayofweek
        dw['week'] = dw['date'].dt.isocalendar().week.astype(int)
        pivot = dw.pivot_table(values='distance', index='weekday', columns='week', aggfunc='sum', fill_value=0)
        pivot.index = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        fig = px.imshow(pivot, text_auto='.1f', aspect="auto", color_continuous_scale='Blues')
        fig.update_layout(title="周训练距离热力图", height=260,
                          margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

# === Tab 2: 活动列表 ===
with t2:
    cf1, cf2, cf3 = st.columns(3)
    with cf1:
        sf = st.multiselect("运动类型", sorted(df['sport_name'].unique()), [])
    with cf2:
        dmin = st.number_input("最小距离(km)", 0.0, 100.0, 0.0, 0.5) if 'distance' in df.columns else 0
    with cf3:
        sb = st.selectbox("排序", ["日期↓", "日期↑", "距离↓", "时长↓"])

    disp = df.copy()
    if sf: disp = disp[disp['sport_name'].isin(sf)]
    if dmin > 0 and 'distance' in disp.columns: disp = disp[disp['distance'] >= dmin]
    if sb == "日期↓" and 'date' in disp.columns: disp = disp.sort_values('date', ascending=False)
    elif sb == "日期↑" and 'date' in disp.columns: disp = disp.sort_values('date')
    elif sb == "距离↓" and 'distance' in disp.columns: disp = disp.sort_values('distance', ascending=False)
    elif sb == "时长↓" and 'duration' in disp.columns: disp = disp.sort_values('duration', ascending=False)

    cols = {}
    if 'name' in disp.columns: cols['name'] = '名称'
    if 'sport_name' in disp.columns: cols['sport_name'] = '类型'
    if 'date' in disp.columns: cols['date'] = '日期'
    if 'distance' in disp.columns: cols['distance'] = '距离(km)'
    if 'duration' in disp.columns:
        disp['_t'] = (disp['duration'] / 3600).round(1)
        cols['_t'] = '时长(h)'
    if 'pace' in disp.columns:
        disp['_p'] = disp['pace'].apply(pace_to_str)
        cols['_p'] = '配速/km'
    if 'avg_heart_rate' in disp.columns: cols['avg_heart_rate'] = '心率'
    if 'calories' in disp.columns: cols['calories'] = '卡路里'

    st.dataframe(disp[list(cols.keys())].rename(columns=cols), use_container_width=True, hide_index=True, height=500)
    csv = disp[list(cols.keys())].rename(columns=cols).to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 导出CSV", csv, f"training_{datetime.now():%Y%m%d}.csv", use_container_width=True)

# === Tab 3: AI教练 ===
with t3:
    st.subheader("🤖 AI 智能教练")

    if not st.session_state.api_key:
        st.warning("请在侧边栏配置 Anthropic API Key")
    else:
        qc1, qc2, qc3, qc4 = st.columns(4)
        user_msg = None
        with qc1:
            if st.button("📊 综合分析", use_container_width=True): user_msg = "请全面分析我的训练数据"
        with qc2:
            if st.button("🫀 负荷评估", use_container_width=True): user_msg = "评估训练负荷与过度训练风险"
        with qc3:
            if st.button("📈 趋势分析", use_container_width=True): user_msg = "分析训练趋势和进步情况"
        with qc4:
            if st.button("🎯 目标建议", use_container_width=True): user_msg = "根据我的数据给出近期合理目标"

        for msg in st.session_state.chat:
            with st.chat_message("🧑" if msg['role'] == 'user' else "🤖"):
                st.markdown(msg['content'])
        if not st.session_state.chat:
            st.info("选择快捷分析或输入问题，AI教练将基于丹尼尔斯训练法为你解答。")

        user_input = st.chat_input("输入你的问题...")
        if user_msg: user_input = user_msg

        if user_input:
            st.session_state.chat.append({'role': 'user', 'content': user_input})
            pctx = "\n".join([f"{k}: {v}" for k, v in profile.items() if v])
            tctx = build_summary(df)
            wctx = ""
            if st.session_state.weather:
                c = st.session_state.weather.get('current', {})
                wctx = f"\n天气: {weather_desc(c.get('weather_code',0))} {c.get('temperature_2m','?')}°C"

            vref = ""
            if paces:
                vref = f"\n【丹尼尔斯配速 (基于COROS实测LTSP)】阈值:{paces['ltsp_str']}/km | E:{paces['E_range']}/km | T:{paces['T_range']}/km | I:{paces['I_range']}/km | R400:{paces['R_400']}s"

            prompt = f"""你是精通杰克·丹尼尔斯训练法的跑步教练。

【个人档案】
{pctx}

【训练数据】
{tctx}{vref}{wctx}

【问题】{user_input}

请基于丹尼尔斯训练法原则（基于COROS实测LTSP的配速体系、周期化阶段、80/20强度分布）给出专业、数据驱动的建议。引用具体数据。用中文。"""

            with st.spinner("AI思考中..."):
                resp = call_claude(
                    "你是精通丹尼尔斯经典跑步训练法的专业教练。配速数据来自COROS实测乳酸阈值。用中文回答，具体可操作。",
                    prompt)
            st.session_state.chat.append({'role': 'assistant', 'content': resp or "AI不可用"})
            st.rerun()

        if st.session_state.chat and st.button("🗑 清空", use_container_width=True):
            st.session_state.chat = []
            st.rerun()

# === Tab 4: 训练计划 ===
with t4:
    st.subheader("📅 AI 定制训练计划")

    if not st.session_state.api_key:
        st.warning("请配置 Anthropic API Key")
    else:
        if paces:
            st.markdown(f"**阈值配速: {paces['ltsp_str']}/km** (COROS实测) | E: {paces['E_range']}/km | T: {paces['T_range']}/km | I: {paces['I_range']}/km")

        pc1, pc2 = st.columns(2)
        with pc1:
            weeks = st.selectbox("周期", ["1周", "2周", "4周"], 0)
            focus = st.selectbox("重点", ["综合提升", "提升速度(I/R)", "提升耐力(T阈值)", "减肥减脂(E为主)", "恢复调整", "赛前减量"], 0)
        with pc2:
            spw = st.slider("每周训练次数", 2, 7, 4)

        if st.button("🎯 生成专属计划", use_container_width=True, type="primary"):
            weekly_km = td / (max((df['date'].max() - df['date'].min()).days, 1) / 7) if 'date' in df.columns else 30
            vref = ""
            if paces:
                vref = f"""【丹尼尔斯配速 (基于COROS实测乳酸阈值)】
阈值配速(LTSP): {paces['ltsp_str']}/km
E: {paces['E_range']}/km | M: {paces['M_range']}/km | T: {paces['T_range']}/km
I: {paces['I_range']}/km | R400: {paces['R_400']}s | R800: {paces['R_800']}s"""

            wctx = ""
            if st.session_state.weather:
                c = st.session_state.weather.get('current', {})
                wctx = f"\n天气: {weather_desc(c.get('weather_code',0))} {c.get('temperature_2m','?')}°C"

            prompt = f"""你是精通丹尼尔斯训练法的跑步教练。制定{weeks}个性化训练计划。

【个人】{chr(10).join([f'{k}: {v}' for k,v in profile.items() if v])}
【数据】{build_summary(df)}
【周跑量】{weekly_km:.0f}km
{vref}{wctx}
【要求】周期:{weeks} | 每周:{spw}次 | 重点:{focus} | 遵循丹尼尔斯周期化与80/20原则

输出格式：
## 总体评估
## 训练配速参考
## 每周安排（| 日期 | 类型 | 内容 | 配速 | 时长 | 备注 |）
## 丹尼尔斯关键提醒（训练点控制、恢复、天气调整）

用中文，严格使用上述基于COROS实测LTSP的配速区间。"""

            with st.spinner("AI制定计划中..."):
                plan = call_claude(
                    "你是精通丹尼尔斯经典跑步训练法的专业教练，配速数据来自COROS实测乳酸阈值。制定具体可执行的周期计划。用中文。",
                    prompt, max_tok=4000)
            if plan:
                st.markdown(plan)

# === Tab 5: 丹尼尔斯指导 ===
with t5:
    if paces:
        st.subheader("📐 丹尼尔斯训练配速 (Daniels' Running Formula)")

        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            st.markdown(f"""
            <div class="glass-card" style="text-align:center">
                <div style="font-size:14px;opacity:0.9">乳酸阈值配速</div>
                <div style="font-size:36px;font-weight:700">{paces['ltsp_str']}</div>
                <div style="font-size:12px;opacity:0.8">COROS 实测 LTSP</div>
            </div>
            """, unsafe_allow_html=True)
        with pc2:
            st.markdown(f"""
            <div class="glass-card green" style="text-align:center">
                <div style="font-size:14px;opacity:0.9">E 轻松跑</div>
                <div style="font-size:28px;font-weight:700">{paces['E_range']}</div>
                <div style="font-size:12px;opacity:0.8">/km · 65-79% HRmax</div>
            </div>
            """, unsafe_allow_html=True)
        with pc3:
            st.markdown(f"""
            <div class="glass-card amber" style="text-align:center">
                <div style="font-size:14px;opacity:0.9">T 阈值跑</div>
                <div style="font-size:28px;font-weight:700">{paces['T_range']}</div>
                <div style="font-size:12px;opacity:0.8">/km · 88-92% HRmax</div>
            </div>
            """, unsafe_allow_html=True)

        # 完整配速表
        with st.expander("📊 完整五级配速区间", expanded=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.info(f"""**E 轻松跑 (Easy)**
                - 配速: {paces['E_range']}/km
                - 心率: 65-79% HRmax
                - 占总跑量 70-80%
                - 用途: 恢复、基础耐力、长距离""")
            with c2:
                st.info(f"""**M 马拉松配速**
                - 配速: {paces['M_range']}/km
                - 心率: 80-90% HRmax
                - 用途: 比赛配速适应""")
            with c3:
                st.warning(f"""**T 阈值跑 (Threshold)**
                - 配速: {paces['T_range']}/km
                - 心率: 88-92% HRmax
                - 单次: 20-40分钟持续
                - 用途: 乳酸阈值提升""")
            c4, c5 = st.columns(2)
            with c4:
                st.error(f"""**I 间歇跑 (Interval)**
                - 配速: {paces['I_range']}/km
                - 心率: 98-100% HRmax
                - 典型: 3-5×1000m, 间歇=跑时
                - 用途: VO2max提升""")
            with c5:
                st.success(f"""**R 重复跑 (Repetition)**
                - 400m: {paces['R_400']}s | 800m: {paces['R_800']}s
                - 间歇: 充分恢复(2-3倍跑时)
                - 用途: 速度与跑步经济性""")

    # 训练评估
    days_span = max((df['date'].max() - df['date'].min()).days, 1) if 'date' in df.columns else 30
    freq = len(df) / (days_span / 7)
    weekly_dist = td / (days_span / 7)

    st.markdown('<div class="section-title">📊 训练评估</div>', unsafe_allow_html=True)
    ec1, ec2, ec3, ec4 = st.columns(4)
    ec1.metric("周频率", f"{freq:.1f}次")
    ec2.metric("周跑量", f"{weekly_dist:.0f}km")
    ec3.metric("总时间", f"{tt/3600:.1f}h")
    ec4.metric("阈值配速", paces.get('ltsp_str', 'N/A') if paces else 'N/A')

    # 强度分布
    if 'avg_heart_rate' in df.columns and df['avg_heart_rate'].notna().any():
        max_hr = profile.get('max_hr', 198)
        rest_hr = profile.get('rest_hr', 45)
        e_hr = rest_hr + (max_hr - rest_hr) * 0.79
        t_hr = rest_hr + (max_hr - rest_hr) * 0.92
        hr = df['avg_heart_rate'].dropna()
        low = (hr < e_hr).sum()
        mid = ((hr >= e_hr) & (hr < t_hr)).sum()
        high = (hr >= t_hr).sum()
        tot = low + mid + high
        if tot > 0:
            st.markdown("**强度分布 (E / M+T / I+R)**")
            st.caption(f"E区(<{e_hr:.0f}) {low}次 | M/T区 {mid}次 | I/R区(>{t_hr:.0f}) {high}次")
            st.progress(low / tot, text=f"E区 {low/tot*100:.0f}% {'✅ 符合80/20' if low/tot>=0.7 else '⚠️ 建议≥70%'}")

    # 丹尼尔斯阶段
    ph = "阶段1 (基础期)" if (weekly_dist < 40 or freq < 4) else \
         "阶段2 (早期质量期)" if freq < 6 else "阶段3 (过渡期)"
    st.info(f"**当前训练阶段: {ph}** — 丹尼尔斯建议每阶段持续4-6周后有序过渡到下一阶段")

    # 核心原则
    st.markdown('<div class="section-title">📖 丹尼尔斯核心原则</div>', unsafe_allow_html=True)
    principles = [
        ("压力 + 休息 = 进步", "训练提供刺激，休息中身体变强。质量课后需48-72h恢复。"),
        ("LTSP 阈值配速系统", "COROS实测乳酸阈值配速(LTSP)作为基准，推导丹尼尔斯E/M/T/I/R五级配速。高驰会根据训练数据持续更新。"),
        ("周期化阶段", "基础期(E)→早期(R strides)→过渡期(T)→巅峰期(I+T)→减量。"),
        ("每个训练都有目的", "每堂课目标明确：恢复、耐力、阈值、VO2max或速度。不混合多个高强度目标。"),
        ("训练点系统", "E跑≈1点/英里，T跑≈2点/英里，I跑≈1.5点/800m。周增幅≤10%。"),
    ]
    for title, desc in principles:
        st.markdown(f"**• {title}** — {desc}")

st.divider()
st.caption(f"更新: {datetime.now():%Y-%m-%d %H:%M} | COROS Training Assistant Pro v3.0 | Daniels Method · Claude AI")
