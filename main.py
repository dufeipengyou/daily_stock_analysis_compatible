import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import warnings
import time
from requests_ratelimiter import LimiterSession, RequestRate, Duration
warnings.filterwarnings('ignore')

# 初始化限流会话：每秒最多2次请求，防止触发 Yahoo 限流
session = LimiterSession(limiter=Limiter(RequestRate(2, Duration.SECOND)))

def convert_code_format(code):
    """统一代码格式，完美兼容你的 hk 前缀和 A股"""
    code_str = str(code).strip().lower()
    if code_str.startswith('hk'):
        # 港股: hk00700 -> 700.HK
        hk_num = code_str[2:].lstrip('0')
        return f"{hk_num}.HK" if hk_num else f"{code_str[2:]}.HK"
    elif code_str.endswith('.sz'):
        return code_str[:6].upper() + '.SZ'
    elif code_str.endswith('.sh'):
        return code_str[:6].upper() + '.SS'
    elif '.' not in code_str:
        # 纯数字默认A股
        return code_str.upper() + ('.SS' if code_str.startswith('6') or code_str.startswith('9') else '.SZ')
    return code_str.upper()

def get_market_prices(code_list, max_retries=3):
    """带重试和限流的 yfinance 获取函数"""
    if not code_list: return pd.DataFrame()

    yf_codes = list(set([convert_code_format(c) for c in code_list]))

    for attempt in range(max_retries):
        try:
            data = yf.download(yf_codes, period="5d", group_by='ticker', progress=False, session=session)
            if data.empty: continue

            results = []
            for yf_code in yf_codes:
                try:
                    ticker_data = data[yf_code] if len(yf_codes) > 1 else data
                    ticker_data = ticker_data.dropna()
                    if ticker_data.empty: continue
                    latest = ticker_data.iloc[-1]
                    results.append({
                        'code': yf_code, 'close': float(latest['Close']),
                        'open': float(latest['Open']), 'high': float(latest['High']),
                        'low': float(latest['Low']), 'volume': int(latest['Volume']),
                        'date': latest.name.strftime('%Y-%m-%d') if hasattr(latest.name, 'strftime') else str(latest.name)[:10]
                    })
                except: continue
            return pd.DataFrame(results)
        except Exception as e:
            wait = 2 ** attempt
            print(f"⚠️ 触发限流或网络错误，等待 {wait}秒 后重试...")
            time.sleep(wait)
    return pd.DataFrame()

def 观察池(df):
    jiegou1 = df.copy()
    jiegou1['代码'] = jiegou1['代码'].apply(convert_code_format)
    stock_prices = get_market_prices(jiegou1['代码'].unique().tolist())

    if stock_prices.empty: 
        print("❌ 未获取到行情数据")
        return pd.DataFrame()

    jiegou1 = jiegou1.merge(stock_prices, left_on='代码', right_on='code', how='left')
    for col in ['close', '加仓点', '回踩点', '成本价格', '数量']:
        jiegou1[col] = pd.to_numeric(jiegou1.get(col, np.nan), errors='coerce')

    # 核心盯盘逻辑
    jiegou1['sig'] = np.where(jiegou1['close'] < jiegou1['加仓点'], 1,
                              np.where(jiegou1['close'] > jiegou1['回踩点'], 2, 0))
    jiegou1['亏损金额'] = (jiegou1['close'] - jiegou1['成本价格']) * jiegou1['数量']

    cols_to_keep = ['sig', '代码', '标的', '底极值', '顶极值', '加仓点', '回踩点', '已下本金', '成本价格', '数量', 'close', '亏损金额']
    return jiegou1[[c for c in cols_to_keep if c in jiegou1.columns]].sort_values('sig', ascending=False)

if __name__ == '__main__':
    try:
        df = pd.read_excel('观察池.xlsx')
        result = 观察池(df)
        if not result.empty:
            result.to_excel('观察池2.xlsx', index=False)
            result[['sig', '标的', '代码', 'close']].set_index('sig').to_csv(f"{datetime.today().date()}观察池跟踪.csv")
            print("✅ 处理完成")
        else:
            print("❌ 结果为空")
    except Exception as e:
        print(f"运行出错: {e}")
