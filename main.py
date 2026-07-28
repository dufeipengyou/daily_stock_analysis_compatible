#!/usr/bin/env python3
"""
兼容版每日股票盯盘脚本
融合：AI 研报 (daily_stock_analysis) + 规则引擎 (观察池逻辑)
"""
import os
import sys
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# ==================== 配置 ====================
SILICONFLOW_API_KEY = os.environ.get("OPENAI_API_KEY")
SILICONFLOW_BASE_URL = os.environ.get("OPENAI_API_BASE", "https://api.siliconflow.cn/v1")
SILICONFLOW_MODEL = os.environ.get("OPENAI_MODEL", "Qwen/Qwen3-8B")
WECOM_WEBHOOK = os.environ.get("WECOM_WEBHOOK_URL")
STOCK_LIST_AI = os.environ.get("STOCK_LIST_AI", "").split(",")

# ==================== 辅助函数 ====================
def convert_code_format(code):
    """统一代码格式"""
    code_str = str(code).strip()
    if code_str.endswith('.SZ'): return code_str[0:6] + '.XSHE'
    elif code_str.endswith('.SH'): return code_str[0:6] + '.XSHG'
    elif '.' in code_str: return code_str
    else: return code_str + ('.XSHG' if code_str.startswith('6') else '.XSHE')

def get_sina_price(code_list):
    """从新浪财经获取实时行情"""
    codes = [convert_code_format(c).replace('.XSHE', '').replace('.XSHG', '') for c in code_list if c]
    if not codes: return pd.DataFrame()

    url = f"http://hq.sinajs.cn/list={''.join(['sh' + c if c.startswith('6') else 'sz' + c for c in codes])}"
    try:
        resp = requests.get(url, timeout=10)
        lines = resp.text.strip().split(';')
        data = []
        for line in lines:
            if '=' in line:
                parts = line.split('=')[1].strip('"').split(',')
                if len(parts) > 30:
                    code = parts[0].replace('sh', '').replace('sz', '')
                    data.append({
                        'code': code,
                        'close': float(parts[3]),
                        'open': float(parts[1]),
                        'high': float(parts[4]),
                        'low': float(parts[5]),
                        'volume': int(parts[8]),
                        'date': datetime.now().strftime('%Y-%m-%d')
                    })
        return pd.DataFrame(data)
    except Exception as e:
        print(f"获取行情失败: {e}")
        return pd.DataFrame()

def analyze_with_ai(stock_info):
    """调用 SiliconFlow API 进行 AI 分析"""
    prompt = f"""请对以下股票进行简要分析：
股票信息：{stock_info}
请给出：1. 综合结论 2. 操作建议 3. 风险提示。保持简洁。"""

    payload = {
        "model": SILICONFLOW_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 1024
    }
    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(f"{SILICONFLOW_BASE_URL}/chat/completions", json=payload, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"AI 分析失败: {e}"
    return "AI 分析超时"

def process_rule_based_pool(excel_path):
    """处理观察池规则引擎"""
    if not os.path.exists(excel_path):
        return "观察池文件不存在"

    try:
        df = pd.read_excel(excel_path)
        df['代码'] = df['代码'].apply(convert_code_format)

        # 获取行情
        codes = df['代码'].unique().tolist()
        prices = get_sina_price(codes)

        if prices.empty:
            return "无法获取行情数据"

        # 合并数据
        prices['code'] = prices['code'].astype(str)
        df['代码'] = df['代码'].str[:6]
        merged = pd.merge(df, prices, left_on='代码', right_on='code', how='left')

        # 计算信号
        merged['sig'] = np.where(merged['close'] < merged['加仓点'], 1, 
                                np.where(merged['close'] > merged['回踩点'], 2, 0))

        # 格式化输出
        result = merged[['sig', '标的', '代码', 'close', '加仓点', '回踩点', '底极值']]
        return result.to_string(index=False)
    except Exception as e:
        return f"观察池处理失败: {e}"

def send_wecom(message):
    """发送企业微信消息"""
    if not WECOM_WEBHOOK:
        print("未配置企业微信 Webhook")
        return

    payload = {
        "msgtype": "text",
        "text": {"content": message[:2000]}  # 限制长度
    }
    try:
        requests.post(WECOM_WEBHOOK, json=payload, timeout=10)
        print("✅ 企业微信消息已发送")
    except Exception as e:
        print(f"发送失败: {e}")

def main():
    print("🚀 开始每日股票盯盘...")
    report = f"📈 每日股票盯盘报告 ({datetime.now().strftime('%Y-%m-%d')})\n\n"

    # 1. 处理观察池 (规则引擎)
    report += "【观察池规则监控】\n"
    rule_result = process_rule_based_pool("观察池.xlsx")
    report += f"{rule_result}\n\n"

    # 2. 处理 AI 分析股票
    if STOCK_LIST_AI and STOCK_LIST_AI[0]:
        report += "【AI 智能研报】\n"
        prices = get_sina_price(STOCK_LIST_AI)
        if not prices.empty:
            for _, row in prices.head(3).iterrows():  # 只分析前3只避免超时
                ai_res = analyze_with_ai(row.to_dict())
                report += f"📊 {row['code']}: {ai_res}\n\n"
        else:
            report += "无法获取 AI 分析所需行情\n\n"

    send_wecom(report)
    print("✅ 任务完成")

if __name__ == "__main__":
    main()
