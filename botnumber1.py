import requests
from datetime import datetime, timedelta
import math
import time
import hmac
import hashlib
import json

# ---------------------------
# THÔNG TIN XÁC THỰC (bạn tự điền vào)
# ---------------------------
API_KEY = "bg_8c194e9f2f3e62a16f70898e631e167b"  # Tự điền key của bạn
API_SECRET = "47dbe023895430d4632186a86a12b947908765ad88a761961f8c781689280b24"  # Tự điền secret của bạn
API_PASSPHRASE = "botnumber1"  # Tự điền passphrase của bạn
BASE_URL = "https://api.bitget.com"

# ---------------------------
# THÔNG TIN TELEGRAM (bạn tự điền vào)
# ---------------------------
TELEGRAM_BOT_TOKEN = "7897151599:AAEMJXA9H0ley35BgnQcfwCxl4PqxUdfLnc"    # Ví dụ: "123456789:ABCdefGhI..."
TELEGRAM_CHAT_ID = "1776484442"          # Ví dụ: "123456789" hoặc "-1001234567890" (nếu gửi tới nhóm)

# ---------------------------
# Hàm gửi tin nhắn lên Telegram (với hỗ trợ tách nếu tin nhắn quá dài)
# ---------------------------
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("Tin nhắn đã được gửi thành công!")
        else:
            print("Gửi tin nhắn thất bại. Response:", response.text)
    except Exception as e:
        print("Exception khi gửi tin nhắn:", e)

def send_long_message(message):
    max_length = 4096  # Telegram giới hạn 4096 ký tự cho mỗi tin nhắn
    if len(message) <= max_length:
        send_telegram_message(message)
    else:
        for i in range(0, len(message), max_length):
            chunk = message[i:i+max_length]
            send_telegram_message(chunk)

# ---------------------------
# 1. Lấy danh sách coin Futures USDT-M từ Bitget
# ---------------------------
def get_bitget_futures_usdtm_coins():
    url = BASE_URL + "/api/mix/v1/market/contracts"
    params = {"productType": "umcbl"}
    response = requests.get(url, params=params)
    coins = []
    if response.status_code == 200:
        data = response.json()
        if data.get("code") != "00000":
            print("Lỗi Bitget API:", data)
            return []
        for contract in data.get("data", []):
            symbol = contract.get("symbol", "")
            if symbol.endswith("_UMCBL"):
                coins.append(symbol)
        return coins
    else:
        print("Lỗi khi lấy danh sách coin từ Bitget:", response.status_code)
        return []

# ---------------------------
# 2. Các hàm lấy dữ liệu và phân tích từ Binance (sử dụng nến 1d)
# ---------------------------
def fetch_candlestick_data(symbol="BTCUSDT", interval="1d", limit=30):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        candles = []
        for kline in data:
            candle = {
                "open_time": datetime.fromtimestamp(kline[0] / 1000),
                "open": float(kline[1]),
                "high": float(kline[2]),
                "low": float(kline[3]),
                "close": float(kline[4]),
                "volume": float(kline[5]),
                "close_time": datetime.fromtimestamp(kline[6] / 1000)
            }
            candles.append(candle)
        return candles
    else:
        print(f"Lỗi khi lấy dữ liệu Binance cho {symbol}: {response.status_code}")
        return None

def get_closed_candles_extended(symbol="BTCUSDT", interval="1d", count=5, window=20):
    total = count + window - 1
    raw_data = fetch_candlestick_data(symbol, interval, limit=total+2)
    if raw_data is None:
        return None
    now = datetime.now()
    closed = [c for c in raw_data if c["close_time"] <= now]
    if len(closed) < total:
        print(f"{symbol}: Không đủ {total} nến đã đóng (chỉ có {len(closed)} nến).")
        return None
    return closed[-total:]

def compute_bollinger_bands(candles, window=20):
    closes = [c['close'] for c in candles[-window:]]
    ma = sum(closes) / window
    variance = sum((price - ma) ** 2 for price in closes) / window
    std = math.sqrt(variance)
    lower = ma - 2 * std
    upper = ma + 2 * std
    return lower, ma, upper

def analyze_candle(candle, prev_candle=None):
    if prev_candle is not None and candle["volume"] < 0.85 * prev_candle["volume"]:
        return ["No pattern (volume condition not met)"]
    o = candle["open"]
    c = candle["close"]
    h = candle["high"]
    l = candle["low"]
    body = abs(c - o)
    total_range = h - l if (h - l) != 0 else 1
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l
    patterns = []
    if c > o and lower_shadow > 2 * body and (lower_shadow / total_range) >= 0.66:
        patterns.append("Bullish Pinbar")
    if o > c and upper_shadow > 2 * body and (upper_shadow / total_range) >= 0.66:
        patterns.append("Bearish Pinbar")
    if c > o and lower_shadow > 2 * body and (h - c) < 0.25 * total_range:
        patterns.append("Bullish Hammer")
    if o > c and upper_shadow > 2 * body and (o - l) < 0.25 * total_range:
        patterns.append("Bearish Hammer")
    if not patterns:
        patterns.append("No pattern")
    return patterns

def analyze_engulfing(candle1, candle2):
    if candle2["volume"] < 0.85 * candle1["volume"]:
        return "No engulfing pattern (volume condition not met)"
    o1, c1 = candle1["open"], candle1["close"]
    o2, c2 = candle2["open"], candle2["close"]
    if o1 > c1 and o2 < c2 and (o2 < c1) and (c2 > o1):
        return "Bullish Engulfing"
    elif o1 < c1 and o2 > c2 and (o2 > c1) and (c2 < o1):
        return "Bearish Engulfing"
    else:
        return "No engulfing pattern"

def check_position(pattern, candle, extended_candles, window=20):
    """
    Với mô hình Bullish: giá đóng (close) của nến phải nằm trong khoảng từ lower đến MA20 (tức là dưới MA20).
    Với mô hình Bearish: giá đóng của nến phải nằm trong khoảng từ MA20 đến upper.
    """
    try:
        idx = extended_candles.index(candle)
    except ValueError:
        return False
    if idx < window - 1:
        return False
    window_slice = extended_candles[idx - window + 1 : idx + 1]
    lower, ma20, upper = compute_bollinger_bands(window_slice, window)
    close = candle["close"]
    if "Bullish" in pattern:
        return (close >= lower) and (close <= ma20)
    elif "Bearish" in pattern:
        return (close >= ma20) and (close <= upper)
    return False

# ---------------------------
# 3. Hàm lấy số dư ví Futures USDT-M từ Bitget
# ---------------------------
def get_futures_usdtm_balance():
    request_path = "/api/mix/v1/account/accounts"
    url = BASE_URL + request_path
    method = "GET"
    timestamp = str(int(time.time() * 1000))
    signature = generate_signature(timestamp, method, request_path, "", API_SECRET)
    headers = {
        "Content-Type": "application/json",
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        if data.get("code") == "00000":
            for account in data.get("data", []):
                if account.get("marginCoin") == "USDT":
                    return float(account.get("available", 0))
            return 0.0
        else:
            print("Lỗi Bitget API khi lấy số dư:", data)
            return 0.0
    else:
        print("Error getting futures balance:", response.status_code, response.text)
        return 0.0

# ---------------------------
# 4. Hàm tạo chữ ký cho Bitget
# ---------------------------
def generate_signature(timestamp, method, request_path, body, secret):
    if body is None:
        body = ""
    prehash = str(timestamp) + method.upper() + request_path + body
    return hmac.new(secret.encode('utf-8'), prehash.encode('utf-8'), hashlib.sha256).hexdigest()

# ---------------------------
# 5. Main: Phân tích các coin và gửi tin nhắn Telegram với danh sách "position OK"
# ---------------------------
if __name__ == "__main__":
    futures_balance = get_futures_usdtm_balance()
    print("Số dư ví Futures USDT-M:", futures_balance)

    bitget_coin_list = get_bitget_futures_usdtm_coins()
    if not bitget_coin_list:
        print("Không tìm thấy coin từ Bitget.")
    else:
        print("Danh sách coin lấy từ Bitget:", bitget_coin_list)

    # Dictionary lưu mapping: coin (theo Binance) -> {pattern, entry_price, stop_loss, take_profit}
    coin_to_details = {}

    for coin in bitget_coin_list:
        binance_symbol = coin.replace("_UMCBL", "").replace("_", "")
        print(f"\n====== Phân tích {binance_symbol} ======")
        extended_data = get_closed_candles_extended(binance_symbol, interval="1d", count=5, window=20)
        if extended_data is None:
            print(f"Bỏ qua {binance_symbol}: không đủ dữ liệu nến đã đóng cửa.")
            continue

        last_candle = extended_data[-1]
        prev_candle = extended_data[-2] if len(extended_data) >= 2 else None
        patterns = analyze_candle(last_candle, prev_candle)
        chosen_pattern = None

        # Ưu tiên mẫu Pinbar/Hammer nếu đạt điều kiện vị trí
        for pat in patterns:
            if (pat.startswith("Bullish") or pat.startswith("Bearish")) and check_position(pat, last_candle, extended_data, window=20):
                chosen_pattern = pat
                break

        # Nếu không có mẫu Pinbar/Hammer, thử mẫu Engulfing
        if chosen_pattern is None and prev_candle is not None:
            engulfing_pattern = analyze_engulfing(prev_candle, last_candle)
            if (engulfing_pattern.startswith("Bullish") or engulfing_pattern.startswith("Bearish")) and check_position(engulfing_pattern, last_candle, extended_data, window=20):
                chosen_pattern = engulfing_pattern

        if chosen_pattern is not None:
            entry_price = last_candle["close"]
            # Nếu mẫu là Engulfing, sử dụng giá của cây nến cũ để đặt SL
            if "Engulfing" in chosen_pattern and prev_candle is not None:
                if chosen_pattern.startswith("Bullish"):
                    stop_loss = prev_candle["low"]
                    risk = entry_price - stop_loss
                    take_profit = entry_price + 1.5 * risk
                elif chosen_pattern.startswith("Bearish"):
                    stop_loss = prev_candle["high"]
                    risk = stop_loss - entry_price
                    take_profit = entry_price - 1.5 * risk
                else:
                    stop_loss = take_profit = 0.0
            else:
                if chosen_pattern.startswith("Bullish"):
                    stop_loss = last_candle["low"]
                    risk = entry_price - stop_loss
                    take_profit = entry_price + 1.5 * risk
                elif chosen_pattern.startswith("Bearish"):
                    stop_loss = last_candle["high"]
                    risk = stop_loss - entry_price
                    take_profit = entry_price - 1.5 * risk
                else:
                    stop_loss = take_profit = 0.0

            coin_to_details[binance_symbol] = {
                "pattern": chosen_pattern,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit
            }
            print(f"{binance_symbol}: Position OK với mẫu {chosen_pattern}")
        else:
            print(f"Bỏ qua {binance_symbol}: không xác định được mẫu lệnh.")

    # Chuẩn bị tin nhắn Telegram chứa toàn bộ danh sách coin "position OK"
    if coin_to_details:
        message = "*Danh sách coin có 'position OK' (nến ngày):*\n\n"
        for coin, details in coin_to_details.items():
            message += (f"*{coin}*\n"
                        f"Pattern: {details['pattern']}\n"
                        f"Entry Price: {details['entry_price']:.2f} USDT\n"
                        f"Stop Loss (SL): {details['stop_loss']:.2f} USDT\n"
                        f"Take Profit (TP): {details['take_profit']:.2f} USDT\n\n")
    else:
        message = "Không có coin nào đạt 'position OK'."

    print("\n===== Gửi tin nhắn lên Telegram =====")
    send_long_message(message)
