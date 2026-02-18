import requests
import datetime
import sys
import traceback
import os
import time

# 强制设置输出编码
sys.stdout.reconfigure(encoding='utf-8')

# ==============================================================================
# ⚙️ 配置区域
# ==============================================================================
# 🔴 你的 PushPlus Token
PUSHPLUS_TOKEN = '229e6e58116042c8a0065709dd98eabc' 

# 监控名单 (新浪代码 gb_xxx, 腾讯代码 us.xxx)
TARGETS = {
    "SPX":  {"name": "标普500",   "sina_code": "gb_inx",   "qq_code": "us.INX"},
    "NDX":  {"name": "纳指100",   "sina_code": "gb_ndx",   "qq_code": "us.NDX"},
    "BRK":  {"name": "伯克希尔B", "sina_code": "gb_brkb",  "qq_code": "us.BRK.B"},
    "AAPL": {"name": "苹果",       "sina_code": "gb_aapl",  "qq_code": "us.AAPL"},
    "PDD":  {"name": "拼多多",     "sina_code": "gb_pdd",   "qq_code": "us.PDD"}
}

# 策略阈值 (负数代表跌幅)
# 稳健组(SPX/BRK) vs 激进组(NDX/AAPL/PDD)
STRATEGY = {
    "RULE_1_PERIOD_DROP":  {"SPX": -2.0, "NDX": -2.0, "BRK": -2.0, "AAPL": -2.0, "PDD": -2.0},
    "RULE_2_DAILY_DROP":   {"SPX": -2.0, "NDX": -2.0, "BRK": -2.0, "AAPL": -2.0, "PDD": -2.0},
    "RULE_3_PERIOD_DROP":  {"SPX": -5.0, "NDX": -5.0, "BRK": -5.0, "AAPL": -5.0, "PDD": -5.0},
    "RULE_4_CRASH_DROP":   {"SPX": -5.0, "NDX": -10.0, "BRK": -5.0, "AAPL": -10.0, "PDD": -10.0}
}

def send_wechat(title, content):
    url = 'http://www.pushplus.plus/send'
    data = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "html"}
    try:
        requests.post(url, json=data, timeout=5)
        print(f"✅ 微信推送已发送: {title}")
    except Exception as e:
        print(f"❌ 微信推送失败: {e}")

def get_realtime_sina():
    """从新浪获取实时价格 (批量)"""
    # 拼接代码: gb_ndx,gb_inx,gb_brkb...
    codes = ",".join([t['sina_code'] for t in TARGETS.values()])
    url = f"http://hq.sinajs.cn/list={codes}"
    headers = {"Referer": "https://finance.sina.com.cn"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        content = resp.text
        results = {}
        
        for key, conf in TARGETS.items():
            s_code = conf['sina_code']
            # 解析格式: var hq_str_gb_xxx="名称,当前价,涨跌幅,..."
            # 搜索 var hq_str_gb_xxx="
            target_str = f'var hq_str_{s_code}="'
            
            if target_str in content:
                try:
                    # 截取数据部分
                    line = content.split(target_str)[1].split('";')[0]
                    parts = line.split(',')
                    if len(parts) > 2:
                        price = float(parts[1])
                        pct = float(parts[2])
                        # 新浪偶尔返回 0，简单过滤
                        if price > 0:
                            results[key] = {"price": price, "daily_pct": pct}
                        else:
                            print(f"⚠️ {key} 新浪返回价格为0，跳过")
                except:
                    pass
        return results
    except Exception as e:
        print(f"❌ 新浪接口报错: {e}")
        return None

def get_salary_day_price(qq_code):
    """计算发薪日基准价 (腾讯K线)"""
    today = datetime.datetime.now()
    if today.day >= 15:
        salary_date = today.replace(day=15)
    else:
        first_day = today.replace(day=1)
        last_month = first_day - datetime.timedelta(days=1)
        salary_date = last_month.replace(day=15)
    
    salary_date_str = salary_date.strftime("%Y-%m-%d")
    
    # 腾讯K线接口
    url = f"https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get?param={qq_code},day,,,60,qfq"
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        
        # 兼容 key (例如 us.AAPL 可能在 data['data']['AAPL'] 或 data['data']['us.AAPL'])
        k_lines = []
        if qq_code in data['data']:
            k_lines = data['data'][qq_code]['day']
        else:
            short_code = qq_code.split('.')[-1] # us.AAPL -> AAPL
            if short_code in data['data']:
                k_lines = data['data'][short_code]['day']
            elif "BRK" in short_code and "brk" in str(data['data']).lower(): # 暴力尝试找一下BRK
                 # 腾讯BRK有时候key很怪，这里做个简单兜底，找不到就拉倒
                 pass

        if not k_lines: 
            return None, salary_date_str

        ref_price = None
        for k in k_lines:
            if k[0] >= salary_date_str:
                ref_price = float(k[2])
                break
        
        if ref_price is None: ref_price = float(k_lines[-1][2])

        return ref_price, salary_date_str
    except:
        return None, salary_date_str

def analyze_and_notify():
    sina_data = get_realtime_sina()
    if not sina_data: 
        print("❌ 未获取到行情数据，取消推送")
        return

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
        
        if period_pct <= STRATEGY['RULE_4_CRASH_DROP'][key]:
            signal = "🚨 <b>暴跌时刻 (买2份!)</b>"
            color = "#FF0000" # 红色
            triggers.append(f"{conf['name']}暴跌")
        elif period_pct <= STRATEGY['RULE_3_PERIOD_DROP'][key]:
            signal = "⭐ <b>周期大跌 (买1份)</b>"
            color = "#FF4500" # 橙红
            triggers.append(f"{conf['name']}大跌")
        elif daily_pct <= STRATEGY['RULE_2_DAILY_DROP'][key]:
            signal = "⚡ <b>日内急跌 (买1份)</b>"
            color = "#FF8C00" # 深橙
            triggers.append(f"{conf['name']}急跌")
        elif period_pct <= STRATEGY['RULE_1_PERIOD_DROP'][key]:
            signal = "✅ <b>周期达标 (买1份)</b>"
            color = "#228B22" # 绿色
            triggers.append(f"{conf['name']}达标")

        # 格式化 HTML
        d_color = "green" if daily_pct > 0 else "red" # 美股涨是绿，跌是红(国内习惯) -> 这里修正一下，既然是美股，我们用 涨green/跌red 还是 涨red/跌green？
        # 为了符合国内看盘习惯（红涨绿跌），我们按国内习惯来：
        d_color_cn = "red" if daily_pct > 0 else "green"
        p_color_cn = "red" if period_pct > 0 else "green"

        row = f"""
        <div style="border-bottom:1px solid #eee; padding: 10px 0;">
            <div style="font-size:16px;"><b>{conf['name']}</b> <span style="font-size:12px;color:#999;">({salary_date}起)</span></div>
            <div style="margin-top:5px; display: flex; justify-content: space-between;">
                <span>现价: <b>{price}</b></span>
                <span>日: <font color="{d_color_cn}">{daily_pct:+.2f}%</font></span>
                <span>周: <font color="{p_color_cn}">{period_pct:+.2f}%</font></span>
            </div>
            <div style="margin-top:8px; color:{color}; font-size:15px; font-weight:bold;">
                👉 {signal}
            </div>
        </div>
        """
        msg_body += row

    # 组装最终消息
    title = f"🇺🇸 美股日报: {triggers[0]}" if triggers else "🇺🇸 美股日报: 今日无操作"
    
    content = f"""
    <h3>📅 {cur_time} 定投监控</h3>
    {msg_body}
    <p style="font-size:12px; color:#aaa; margin-top:20px; text-align:center;">
        基于新浪财经接口 | 周期基准: 每月15日
    </p>
    """
    
    send_wechat(title, content)

if __name__ == "__main__":
    try:
        analyze_and_notify()
    except Exception:
        err = traceback.format_exc()
        print(err)
        # 出错了也发个通知告诉我
        # send_wechat("⚠️ 监控程序报错", f"<pre>{err}</pre>")
