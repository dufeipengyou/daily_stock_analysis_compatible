import pandas as pd
import numpy as np
import yfinance as yf
import akshare as ak
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

def convert_code_format(code):
    """统一代码格式，兼容 hk 前缀和 A股"""
    code_str = str(code).strip().lower()
    if code_str.startswith('hk'):
        hk_num = code_str[2:].lstrip('0')
        return f"{hk_num}.HK" if hk_num else f"{code_str[2:]}.HK"
    elif code_str.endswith('.sz'):
        return code_str[:6].upper() + '.SZ'
    elif code_str.endswith('.sh'):
        return code_str[:6].upper() + '.SS'
    elif '.' not in code_str:
        return code_str.upper() + ('.SS' if code_str.startswith('6') or code_str.startswith('9') else '.SZ')
    return code_str.upper()

def get_yf_prices(yf_codes):
    """yfinance 获取逻辑"""
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
        except: continue
    return pd.DataFrame(results)

def get_ak_prices(original_codes):
    """AKShare 获取逻辑 (仅针对 A 股)"""
    results = []
    for code in original_codes:
        try:
            code_str = str(code).strip()
            # 仅 A 股使用 AKShare
            if code_str.endswith('.SS') or code_str.endswith('.SZ'):
                pure_code = code_str[:6]
                # 获取昨日数据
                yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
                df = ak.stock_zh_a_hist(symbol=pure_code, period="daily", start_date=yesterday, end_date=yesterday, adjust="qfq")
                if not df.empty:
                    results.append({
                        'code': code_str, 
                        'close': float(df.iloc[-1]['收盘']), 
                        'date': yesterday
                    })
        except Exception as e:
            print(f"AKShare 获取 {code} 失败: {e}")
    return pd.DataFrame(results)

def get_market_prices(code_list):
    """双引擎容错获取"""
    if not code_list: return pd.DataFrame()
    original_codes = [convert_code_format(c) for c in code_list]
    yf_codes = list(set(original_codes))

    # 1. 尝试 yfinance
    try:
        print("🔄 正在尝试 yfinance 获取数据...")
        df = get_yf_prices(yf_codes)
        if not df.empty and len(df) >= len(yf_codes) * 0.8:
            print("✅ yfinance 获取成功")
            return df
    except Exception as e:
        print(f"⚠️ yfinance 异常: {e}")

    # 2. 降级到 AKShare
    print("🔄 yfinance 数据不全，切换至 AKShare 获取 A 股昨日数据...")
    df_ak = get_ak_prices(original_codes)
    if not df_ak.empty:
        print("✅ AKShare 获取成功")
        return df_ak

    return pd.DataFrame()

def 观察池(df):
    jiegou1 = df.copy()
    jiegou1['代码'] = jiegou1['代码'].apply(convert_code_format)
    stock_prices = get_market_prices(jiegou1['代码'].unique().tolist())

    if stock_prices.empty: 
        print("❌ 两个数据源均未获取到行情数据")
        return pd.DataFrame()

    jiegou1 = jiegou1.merge(stock_prices, left_on='代码', right_on='code', how='left')
    for col in ['close', '加仓点', '回踩点', '成本价格', '数量']:
        jiegou1[col] = pd.to_numeric(jiegou1.get(col, np.nan), errors='coerce')

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
            print("✅ 盯盘处理完成")
        else:
            print("❌ 结果为空")
    except Exception as e:
        print(f"运行出错: {e}")
