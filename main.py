#!/usr/bin/env python3
import requests
import base64
import pandas as pd
import numpy as np
import yfinance as yf
import akshare as ak
from datetime import datetime, timedelta
import warnings
import json

warnings.filterwarnings('ignore')

import os

# 安全地读取环境变量
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
WECOM_WEBHOOK = os.getenv("WECOM_WEBHOOK_URL")

# 增加防御性检查，防止因为漏配 Secrets 导致程序报错
if not GITHUB_TOKEN:
    raise ValueError("❌ 错误：未检测到 GITHUB_TOKEN，请在 GitHub 仓库的 Secrets 中配置！")

if not WECOM_WEBHOOK:
    raise ValueError("❌ 错误：未检测到 WECOM_WEBHOOK_URL，请在 GitHub 仓库的 Secrets 中配置！")
REPO = "daily_stock_analysis_compatible"

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "DSA-Fix-Script"
}


# ==================== 核心：代码格式转换器 ====================
class CodeConverter:
    @staticmethod
    def to_yf(code):
        """转换为 yfinance 格式"""
        code_str = str(code).strip().lower()
        if code_str.startswith('hk'):
            hk_num = code_str[2:].lstrip('0')
            return f"{hk_num}.HK" if hk_num else f"{code_str[2:]}.HK"
        elif code_str.endswith('.xshe'):
            return code_str[:6].upper() + '.SZ'
        elif code_str.endswith('.xshg'):
            return code_str[:6].upper() + '.SS'
        elif '.' not in code_str:
            return code_str.upper() + ('.SS' if code_str.startswith('6') or code_str.startswith('9') else '.SZ')
        return code_str.upper()

    @staticmethod
    def to_ak(code):
        """转换为 AKShare 格式"""
        code_str = str(code).strip().lower()
        if code_str.startswith('hk'):
            return code_str[2:]  # 保留前导零，如 09988
        elif code_str.endswith('.xshe') or code_str.endswith('.xshg') or code_str.endswith('.XSHG') or code_str.endswith('.XSHE'):
            return code_str[:6]
        elif '.' in code_str:
            return code_str.split('.')[0]
        return code_str

    @staticmethod
    def get_ak_type(code):
        """判断 AKShare 类型: A股 / HK / B股"""
        pure_code = CodeConverter.to_ak(code)
        if len(pure_code) in (5, 4):
            return 'HK'
        elif pure_code.startswith('s'):
            return 'B'
        return 'A'


# ==================== 数据获取双引擎 ====================
def get_yf_prices(codes):
    yf_codes = list(set([CodeConverter.to_yf(c) for c in codes]))
    data = yf.download(yf_codes, period="5d", group_by='ticker', progress=False)
    if data.empty: return pd.DataFrame()
    results = []
    for yf_code in yf_codes:
        try:
            ticker_data = data[yf_code] if len(yf_codes) > 1 else data
            ticker_data = ticker_data.dropna()
            if ticker_data.empty: continue
            latest = ticker_data.iloc[-1]
            results.append({
                'code': yf_code, 'close': float(latest['Close']),
                'date': latest.name.strftime('%Y-%m-%d') if hasattr(latest.name, 'strftime') else str(latest.name)[:10]
            })
        except:
            continue
    return pd.DataFrame(results)


def get_ak_prices(codes):
    """
    优化版：按市场分组，批量获取数据，避免频繁请求。
    """
    if not codes:
        return pd.DataFrame()

    # 1. 按市场分类股票代码
    stock_groups = {'A': [], 'HK': [], 'B': []}
    for code in codes:
        stock_type = CodeConverter.get_ak_type(code)
        pure_code = CodeConverter.to_ak(code)
        if pure_code:  # 确保代码有效
            stock_groups[stock_type].append(pure_code)

    all_results = []
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')

    # 2. 按组批量请求数据
     # --- A股市场 ---
    if stock_groups['A']:

        try:
            # ak.stock_zh_a_hist 支持传入代码列表
            df_a = ak.stock_zh_a_spot_em()
            df_a = df_a.loc[df_a['代码'].isin(stock_groups['A'])]
            print(df_a)
            if not df_a.empty:
                for _, row in df_a.iterrows():
                    all_results.append({
                        'code': row['代码'],
                        'close': float(row['昨收']),
                        'date': yesterday_str
                    })
        except Exception as e:
            print(f"⚠️ AKShare A股批量获取失败: {e}")

    # --- 港股市场 ---
    if stock_groups['HK']:
        try:
            # ak.stock_hk_hist 同样支持列表
            df_hk = ak.stock_hk_famous_spot_em()
            df_hk = df_hk.loc[df_hk['代码'].isin(stock_groups['HK'])]
            if not df_hk.empty:
                for _, row in df_hk.iterrows():
                    all_results.append({
                        'code': row['代码'],
                        'close': float(row['昨收']),
                        'date': yesterday_str
                    })
        except Exception as e:
            print(f"⚠️ AKShare 港股批量获取失败: {e}")
    print(all_results)
    # --- B股市场 ---
    # 注意：AKShare的B股接口可能不支持列表，如果失败则回退到单只获取
    if stock_groups['B']:

        try:
            df_b = ak.stock_zh_b_spot_em()
            df_b = df_b.loc[df_b['代码'].isin(stock_groups['B'])]
            if not df_b.empty:
                for _, row in df_b.iterrows():
                    all_results.append({
                        'code': row['代码'],
                        'close': float(row['昨收']),
                        'date': yesterday_str
                    })
        except Exception as e:
            print(f"AKShare 获取B股 {code} 失败: {e}")
    print(all_results)
    return pd.DataFrame(all_results)

def get_market_prices(code_list):
    if not code_list: return pd.DataFrame()   

    print("🔄 切换至 AKShare...")
    df_ak = get_ak_prices(code_list)
    if not df_ak.empty:
        print("✅ AKShare 成功")
        return df_ak
    return pd.DataFrame()


# ==================== 企业微信推送 ====================
def send_wecom(content):
    payload = {"msgtype": "text", "text": {"content": content[:2000]}}
    try:
        resp = requests.post(WECOM_WEBHOOK, json=payload, timeout=10)
        if resp.json().get('errcode') == 0:
            print("✅ 企业微信推送成功")
        else:
            print(f"❌ 企业微信推送失败: {resp.text}")
    except Exception as e:
        print(f"❌ 推送异常: {e}")


# ==================== 观察池分析逻辑 ====================
def analyze_pool(excel_path):
    df = pd.read_excel(excel_path)
    stock_prices = get_market_prices(df['代码'].unique().tolist())
    if stock_prices.empty: return "❌ 未获取到行情数据"

    df = df.merge(stock_prices, left_on='代码', right_on='code', how='left')
    for col in ['close', '加仓点', '回踩点', '成本价格', '数量']:
        df[col] = pd.to_numeric(df.get(col, np.nan), errors='coerce')

    df['sig'] = np.where(df['close'] < df['加仓点'], 1, np.where(df['close'] > df['回踩点'], 2, 0))
    df['亏损金额'] = (df['close'] - df['成本价格']) * df['数量']

    cols = ['sig', '代码',  'close'] #'标的',
    result = df[[c for c in cols if c in df.columns]].sort_values('sig', ascending=False)
    return result.to_string(index=False)


# ==================== GitHub 自动推送与本地测试 ====================
def update_github_file(path, content, message):
    username = requests.get("https://api.github.com/user", headers=HEADERS).json()["login"]
    repo_full_name = f"{username}/{REPO}"
    content_b64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    check = requests.get(f"https://api.github.com/repos/{repo_full_name}/contents/{path}", headers=HEADERS)
    data = {"message": message, "content": content_b64, "branch": "main"}
    if check.status_code == 200: data["sha"] = check.json()["sha"]
    resp = requests.put(f"https://api.github.com/repos/{repo_full_name}/contents/{path}", headers=HEADERS, json=data)
    print(f"{'✅' if resp.status_code in (200, 201) else '❌'} GitHub 更新: {path}")


if __name__ == '__main__':

    print("🚀 开始执行每日股票分析任务...")
    try:
        report = f"📈 每日盯盘报告 ({datetime.now().strftime('%Y-%m-%d')})"
        report += "【观察池规则监控】"
        # 注意：在 GitHub Actions 环境中，你需要确保 '观察池.xlsx' 文件也在仓库里
        report += analyze_pool('观察池.xlsx')
        send_wecom(report)
    except Exception as e:
        error_msg = f"❌ 任务执行出错: {e}"
        print(error_msg)
        send_wecom(error_msg)     
