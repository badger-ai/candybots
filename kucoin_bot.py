import asyncio
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
import ccxt.async_support as ccxt
import logging
import websockets
import json
import time
from datetime import datetime

# Set up logging to track everything
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("kucoin_bot.log"), logging.StreamHandler()]
)

# Storage for prices and trading info
price_data = {}
fee = 0.001  # KuCoin fee
INITIAL_BALANCE = 12.00  # $12 in KuCoin
total_balance = INITIAL_BALANCE
trade_count = 0
MAX_TRADES_PER_DAY = 150
trade_log = []

# KuCoin API key - Add your real key here!
EXCHANGE = {
    "kucoin": {"apiKey": "67c7bb1e45e41a000167408c", "secret": "9e4663ba-6931-4cff-b889-5a4f37c87ed9", "password": "David@942003"}
}

# Initialize KuCoin
async def init_exchange():
    exchange = ccxt.kucoin({
        "apiKey": EXCHANGE["kucoin"]["apiKey"],
        "secret": EXCHANGE["kucoin"]["secret"],
        "password": EXCHANGE["kucoin"]["password"],
        "enableRateLimit": True,
        "asyncio_loop": asyncio.get_event_loop()
    })
    await exchange.load_markets()
    balance = await exchange.fetch_balance()
    usdt = balance["total"].get("USDT", 0)
    logging.info(f"kucoin connected! USDT balance: {usdt}")
    if usdt < 10:
        logging.warning(f"kucoin has low funds: {usdt} USDT - Fund it!")
    return exchange

# WebSocket for KuCoin prices
WS_URL = "wss://ws-api.kucoin.com/endpoint"

async def websocket_listener():
    retry_count = 0
    max_retries = 5
    while retry_count < max_retries:
        try:
            async with websockets.connect(WS_URL, ping_interval=20) as ws:
                token = await exchange.public_get_bullet_public()
                await ws.send(json.dumps({"id": 1, "type": "subscribe", "topic": "/market/ticker:XRP-USDT", "privateChannel": False, "response": True}))
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=30)
                        data = json.loads(msg)
                        if "data" in data and "price" in data["data"]:
                            price = float(data["data"]["price"])
                            price_data["kucoin"] = {"price": price, "timestamp": asyncio.get_event_loop().time()}
                    except asyncio.TimeoutError:
                        logging.warning("kucoin WebSocket timed out - retrying...")
                        break
                    except Exception as e:
                        logging.error(f"kucoin WebSocket error: {e}")
                        break
        except Exception as e:
            retry_count += 1
            logging.warning(f"kucoin WebSocket failed, retry {retry_count}/{max_retries}: {e}")
            await asyncio.sleep(min(2 ** retry_count, 30))
    logging.error("kucoin WebSocket gave up after 5 retries!")

# Trade logic (buy low, sell high on KuCoin)
async def trade_logic(exchange):
    last_day = time.localtime().tm_mday
    while True:
        await asyncio.sleep(0.001)
        current_day = time.localtime().tm_mday
        if current_day != last_day:
            global trade_count
            trade_count = 0
            last_day = current_day
            logging.info(f"New day: {current_day}, Trade count reset.")

        if "kucoin" not in price_data:
            continue

        price = price_data["kucoin"]["price"]
        timestamp = price_data["kucoin"]["timestamp"]
        if asyncio.get_event_loop().time() - timestamp > 0.5:
            continue

        # Simple logic: Buy if price drops, sell if it rises
        avg_price = total_balance / INITIAL_BALANCE * price  # Rough average holding price
        amount = total_balance / price

        if price < avg_price * 0.995:  # Buy 0.5% below average
            await execute_trade(exchange, "buy", amount, price)
        elif price > avg_price * 1.005:  # Sell 0.5% above average
            await execute_trade(exchange, "sell", amount, price)
        await asyncio.sleep(0.1)

async def execute_trade(exchange, side, amount, price):
    global total_balance, trade_count, trade_log
    if trade_count >= MAX_TRADES_PER_DAY:
        logging.info("Daily trade limit reached!")
        return
    try:
        if side == "buy":
            order = await exchange.create_limit_buy_order("XRP/USDT", amount, price)
            cost = amount * price * (1 + fee)
            total_balance -= cost
            logging.info(f"Trade #{trade_count+1}: Bought {amount:.6f} XRP at ${price:.4f}, Cost: ${cost:.2f}, Balance: ${total_balance:.2f}")
        elif side == "sell":
            order = await exchange.create_limit_sell_order("XRP/USDT", amount, price)
            profit = amount * price * (1 - fee)
            total_balance += profit
            logging.info(f"Trade #{trade_count+1}: Sold {amount:.6f} XRP at ${price:.4f}, Profit: ${profit:.2f}, Balance: ${total_balance:.2f}")
        trade_count += 1
        trade_log.append({"time": datetime.now().isoformat(), "side": side, "amount": amount, "price": price, "balance": total_balance})
    except Exception as e:
        logging.error(f"Trade failed: {e}")
        await asyncio.sleep(1)

# Main function
async def main():
    logging.info("Starting KuCoin XRP/USDT Bot - $12 to More!")
    logging.info(f"Initial Balance: ${total_balance:.2f}")
    global exchange
    exchange = await init_exchange()
    await asyncio.gather(
        asyncio.create_task(websocket_listener()),
        asyncio.create_task(trade_logic(exchange))
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info(f"Stopped by user. Final Balance: ${total_balance:.2f}")
    except Exception as e:
        logging.error(f"Main failed: {e}")
