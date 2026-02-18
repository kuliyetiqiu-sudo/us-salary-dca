import requests
import datetime
import sys
import traceback
import os

# 强制设置输出编码
sys.stdout.reconfigure(encoding='utf-8')

# ==============================================================================
# ⚙️ 配置区域
# ==============================================================================
# 🔴 你的 PushPlus Token (已自动填入)
PUSHPLUS_TOKEN = '229e6e58116042c8a0065709dd98eabc'

TARGETS = {
    "SPX": {"name": "标普500", "sina_code": "gb_inx", "qq_code": "us.INX"},
    "NDX": {"name": "纳指100", "sina_code": "gb_ndx", "qq_code": "us.NDX"}
}

STRATEGY = {
    "RULE_1_PERIOD_DROP":  {"SPX": -2.0, "NDX": -2.0},   # 规则1
    "RULE_2_DAILY_DROP":   {"SPX": -2.0, "NDX": -2.0},   # 规则2
    "RULE_3_PERIOD_DROP":  {"SPX": -5.0, "NDX": -5.0},   # 规则3
    "RULE_4_CRASH_DROP":   {"SPX": -5.0, "NDX": -10.0}  # 规则4
}

def send_wechat(title, content):
    url = 'http://www.pushplus.plus/send'
    data = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "html"}
    try:
        requests.post(url, json=data, timeout=5)
        print("✅ 微信推送成功")
    except Exception as e:
        print(f"❌ 微信推送失败: {e}")

def get_realtime_sina():
    """从新浪获取实时价格"""
    url = "http://hq.sinajs.cn/list=gb_ndx,gb_inx"
    headers = {"Referer": "https://finance.sina.com.cn"}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        content = resp.text
        results = {}
        if "gb_ndx" in content:
            parts = content.split('var hq_str_gb_ndx="')[1].split('";')[0].split(',')
            results["NDX"] = {"price": float(parts[1]), "daily_pct": float(parts[2])}
        if "gb_inx" in content:
            parts = content.split('var hq_str_gb_inx="')[1].split('";')[0].split(',')
            results["SPX"] = {"price": float(parts[1]), "daily_pct": float(parts[2])}
        return results
    except Exception as e:
        print(f"❌ 新浪接口报错: {e}")
        return None

def get_salary_day_price(qq_code):
    """计算发薪日基准价"""
    today = datetime.datetime.now()
    if today.day >= 15:
        salary_date = today.replace(day=15)
    else:
        first_day = today.replace(day=1)
        last_month = first_day - datetime.timedelta(days=1)
        salary_date = last_month.replace(day=15)
    
    salary_date_str = salary_date.strftime("%Y-%m-%d")
    url = f"https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get?param={qq_code},day,,,60,qfq"
    
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        k_lines = data['data'][qq_code]['day']
        
        ref_price = None
        for k in k_lines:
            if k[0] >= salary_date_str:
                ref_price = float(k[2])
                break
        if not ref_price and k_lines: ref_price = float(k_lines[-1][2])
        return ref_price, salary_date_str
    except:
        return None, salary_date_str

def analyze_and_notify():
    sina_data = get_realtime_sina()
    if not sina_data: return

    msg_body = ""
    triggers = []
    
    # 获取当前时间 (北京时间)
    utc_now = datetime.datetime.utcnow()
    beijing_now = utc_now + datetime.timedelta(hours=8)
    cur_time = beijing_now.strftime("%m-%d %H:%M")

    for key, conf in TARGETS.items():
        if key not in sina_data: continue
        
        price = sina_data[key]['price']
        daily_pct = sina_data[key]['daily_pct']
        base_price, salary_date = get_salary_day_price(conf['qq_code'])
        
        period_pct = 0.0
        if base_price:
            period_pct = (price - base_price) / base_price * 100

        # === 核心策略逻辑 ===
        signal = "⚪ 观望待机"
        color = "#888888" # 灰色
        level = 0
        
        if period_pct <= STRATEGY['RULE_4_CRASH_DROP'][key]:
            signal = "🚨 <b>暴跌时刻 (买2份!)</b>"
            color = "#FF0000" # 红色
            level = 4
            triggers.append(f"{conf['name']}暴跌")
        elif period_pct <= STRATEGY['RULE_3_PERIOD_DROP'][key]:
            signal = "⭐ <b>周期大跌 (买1份)</b>"
            color = "#FF4500" # 橙红
            level = 3
            triggers.append(f"{conf['name']}机会")
        elif daily_pct <= STRATEGY['RULE_2_DAILY_DROP'][key]:
            signal = "⚡ <b>日内急跌 (买1份)</b>"
            color = "#FF8C00" # 深橙
            level = 2
            triggers.append(f"{conf['name']}急跌")
        elif period_pct <= STRATEGY['RULE_1_PERIOD_DROP'][key]:
            signal = "✅ <b>周期达标 (买1份)</b>"
            color = "#228B22" # 绿色
            level = 1
            triggers.append(f"{conf['name']}达标")

        # 格式化 HTML
        d_color = "green" if daily_pct < 0 else "red"
        p_color = "green" if period_pct < 0 else "red"
        
        row = f"""
        <div style="border-bottom:1px solid #eee; padding: 10px 0;">
            <div style="font-size:16px;"><b>{conf['name']}</b> <span style="font-size:12px;color:#999;">({salary_date}起)</span></div>
            <div style="margin-top:5px;">
                现价: <b>{price}</b><br>
                日涨跌: <font color="{d_color}">{daily_pct:+.2f}%</font><br>
                周期跌: <font color="{p_color}">{period_pct:+.2f}%</font>
            </div>
            <div style="margin-top:8px; color:{color}; font-size:15px;">
                👉 {signal}
            </div>
        </div>
        """
        msg_body += row

    # 组装最终消息
    title = "🇺🇸 美股定投日报"
    if triggers: title += f": {triggers[0]}..."
    
    content = f"""
    <h3>📅 {cur_time} 监控报告</h3>
    {msg_body}
    <p style="font-size:12px; color:#aaa; margin-top:20px;">
        *周期跌幅基准日: 每月15号<br>
        *数据来源: 新浪+腾讯 (无需VPN)
    </p>
    """
    
    send_wechat(title, content)

if __name__ == "__main__":
    try:
        analyze_and_notify()
    except Exception:
        err = traceback.format_exc()
        print(err)
        send_wechat("⚠️ 监控程序报错", f"<pre>{err}</pre>")
