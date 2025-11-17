import os
import sys
import json
import time
import logging
import asyncio
import re
from datetime import datetime, timezone
import math
import decimal
import requests
from typing import Optional, List, Dict
from contextlib import asynccontextmanager

import aiohttp
from dotenv import load_dotenv
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from openai import OpenAI
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import mysql.connector
from mysql.connector import Error as MySQLError

# --- 1. Configuration & Logging ---
load_dotenv()

def _get_env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

CONFIG = {
    "taapi_api_key": _get_env("TAAPI_API_KEY", required=False),
    "hyperliquid_private_key": _get_env("HYPERLIQUID_PRIVATE_KEY"),
    "mnemonic": _get_env("MNEMONIC"),
    "gaia_api_key": _get_env("GAIA_API_KEY", required=True),
    "gaia_node_url": _get_env("GAIA_NODE_URL", "https://qwen72b.gaia.domains/v1").strip(),
    "gaia_model_name": _get_env("GAIA_MODEL_NAME", "x-ai/grok-4"),
    "assets": _get_env("ASSETS", "BTC,ETH,SOL,XRP,DOGE,BNB"),
    "interval": _get_env("INTERVAL", "15m"),
    # Database config
    "db_host": _get_env("DB_HOST", required=True),
    "db_user": _get_env("DB_USER", required=True),
    "db_password": _get_env("DB_PASSWORD", required=True),
    "db_name": _get_env("DB_NAME", required=True),
    "db_port": int(_get_env("DB_PORT", "3306")),
    # API config
    "api_host": _get_env("API_HOST", "0.0.0.0"),
    "api_port": int(_get_env("API_PORT", "8000")),
}

# OPTIMIZED Parameters for consistent sizing
MAX_RISK_PER_TRADE = 0.03
MIN_POSITION_VALUE = 50.0
MAX_POSITION_VALUE = 300.0
STOP_LOSS_PCT = 0.015
TAKE_PROFIT_PCT = 0.03
MAX_CONCURRENT_TRADES = 0
MAX_DAILY_TRADES = 0
MAX_TOTAL_EXPOSURE_PERCENTAGE = 1.0

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- 2. MySQL Database Manager ---
class DatabaseManager:
    def __init__(self, skip_init=False):
        self.connection = None
        self.db_available = False
        self.last_error = None
        
        if not skip_init:
            try:
                self.test_connection()
                self.initialize_db()
                self.db_available = True
                logger.info("✅ Database connection successful")
            except Exception as e:
                self.last_error = str(e)
                logger.warning(f"⚠️  Database initialization failed: {e}")
                logger.warning("⚠️  API will work in read-only mode. Decisions will not be persisted.")
                self.db_available = False
    
    def test_connection(self):
        """Test database connection"""
        try:
            conn = mysql.connector.connect(
                host=CONFIG["db_host"],
                port=CONFIG["db_port"],
                user=CONFIG["db_user"],
                password=CONFIG["db_password"],
                database=CONFIG["db_name"],
                connection_timeout=10
            )
            conn.close()
            logger.info(f"✅ Database connection test passed: {CONFIG['db_host']}:{CONFIG['db_port']}")
        except MySQLError as e:
            logger.error(f"❌ Database connection test failed")
            logger.error(f"   Host: {CONFIG['db_host']}:{CONFIG['db_port']}")
            logger.error(f"   User: {CONFIG['db_user']}")
            logger.error(f"   Error: {e}")
            raise
    
    def get_connection(self):
        try:
            if self.connection is None or not self.connection.is_connected():
                self.connection = mysql.connector.connect(
                    host=CONFIG["db_host"],
                    port=CONFIG["db_port"],
                    user=CONFIG["db_user"],
                    password=CONFIG["db_password"],
                    database=CONFIG["db_name"],
                    connection_timeout=10
                )
            return self.connection
        except MySQLError as e:
            logger.error(f"Database connection error: {e}")
            self.db_available = False
            raise
    
    def initialize_db(self):
        """Create tables if they don't exist"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Create decisions table
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS trade_decisions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                token VARCHAR(50) NOT NULL,
                action VARCHAR(20) NOT NULL,
                conviction VARCHAR(20),
                size DECIMAL(20, 8),
                reason TEXT,
                account_value DECIMAL(20, 2),
                pnl_percentage DECIMAL(10, 4),
                daily_trade_count INT,
                consecutive_losses INT,
                INDEX idx_timestamp (timestamp),
                INDEX idx_token (token),
                INDEX idx_action (action)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
            
            cursor.execute(create_table_sql)
            conn.commit()
            logger.info("✅ Database tables verified/created")
            cursor.close()
        except MySQLError as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    def store_decision(self, decision_data: Dict):
        """Store a single trade decision to the database"""
        if not self.db_available:
            logger.warning(f"Database unavailable - decision for {decision_data.get('token')} not stored")
            return None
            
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            insert_sql = """
            INSERT INTO trade_decisions 
            (token, action, conviction, size, reason, account_value, pnl_percentage, daily_trade_count, consecutive_losses)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            cursor.execute(insert_sql, (
                decision_data.get("token"),
                decision_data.get("action"),
                decision_data.get("conviction"),
                decision_data.get("size"),
                decision_data.get("reason"),
                decision_data.get("account_value"),
                decision_data.get("pnl_percentage"),
                decision_data.get("daily_trade_count"),
                decision_data.get("consecutive_losses")
            ))
            
            conn.commit()
            cursor.close()
            logger.debug(f"Decision stored for {decision_data.get('token')}")
            return cursor.lastrowid
        except MySQLError as e:
            logger.error(f"Error storing decision: {e}")
            self.db_available = False
            return None
    
    def get_decisions(self, token: Optional[str] = None, action: Optional[str] = None, 
                     limit: int = 100, offset: int = 0) -> List[Dict]:
        """Retrieve decisions from database with optional filters"""
        if not self.db_available:
            logger.warning("Database unavailable - returning empty results")
            return []
            
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            query = "SELECT * FROM trade_decisions WHERE 1=1"
            params = []
            
            if token:
                query += " AND token = %s"
                params.append(token)
            
            if action:
                query += " AND action = %s"
                params.append(action)
            
            query += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            cursor.close()
            return results
        except MySQLError as e:
            logger.error(f"Error retrieving decisions: {e}")
            self.db_available = False
            return []
    
    def get_decision_stats(self, token: Optional[str] = None) -> Dict:
        """Get statistics about stored decisions"""
        if not self.db_available:
            logger.warning("Database unavailable - returning empty stats")
            return {"total_decisions": 0, "by_action": {}, "average_conviction_score": 0}
            
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Total decisions
            query = "SELECT COUNT(*) as total FROM trade_decisions WHERE 1=1"
            params = []
            
            if token:
                query += " AND token = %s"
                params.append(token)
            
            cursor.execute(query, params)
            total = cursor.fetchone()["total"]
            
            # Count by action
            query = "SELECT action, COUNT(*) as count FROM trade_decisions WHERE 1=1"
            params = []
            
            if token:
                query += " AND token = %s"
                params.append(token)
            
            query += " GROUP BY action"
            cursor.execute(query, params)
            action_counts = {row["action"]: row["count"] for row in cursor.fetchall()}
            
            # Average conviction
            query = "SELECT AVG(CAST(CASE WHEN conviction='HIGH' THEN 3 WHEN conviction='MEDIUM' THEN 2 ELSE 1 END AS DECIMAL)) as avg_conviction FROM trade_decisions WHERE 1=1"
            params = []
            
            if token:
                query += " AND token = %s"
                params.append(token)
            
            cursor.execute(query, params)
            avg_conv = cursor.fetchone()["avg_conviction"] or 0
            
            cursor.close()
            
            return {
                "total_decisions": total,
                "by_action": action_counts,
                "average_conviction_score": float(avg_conv)
            }
        except MySQLError as e:
            logger.error(f"Error retrieving stats: {e}")
            self.db_available = False
            return {"total_decisions": 0, "by_action": {}, "average_conviction_score": 0}
    
    def close(self):
        """Close database connection"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            logger.info("Database connection closed")

# --- 3. Trade Manager for Consistent Sizing ---
class TradeManager:
    def __init__(self):
        self.daily_trade_count = 0
        self.last_trade_day = None
        self.consecutive_losses = 0
        self.max_consecutive_losses = 5
        
    def reset_daily_count_if_new_day(self):
        today = datetime.now().date()
        if self.last_trade_day != today:
            self.daily_trade_count = 0
            self.last_trade_day = today
            self.consecutive_losses = 0
            logger.info("Daily trade count reset")
    
    def can_trade(self, current_trades_count: int) -> bool:
        self.reset_daily_count_if_new_day()
        
        if current_trades_count >= MAX_CONCURRENT_TRADES:
            logger.warning(f"Cannot trade: {current_trades_count} open positions (max: {MAX_CONCURRENT_TRADES})")
            return False
            
        if self.daily_trade_count >= MAX_DAILY_TRADES:
            logger.warning(f"Cannot trade: {self.daily_trade_count} trades today (max: {MAX_DAILY_TRADES})")
            return False
            
        if self.consecutive_losses >= self.max_consecutive_losses:
            logger.warning(f"Cannot trade: {self.consecutive_losses} consecutive losses")
            return False
            
        return True
    
    def record_trade(self, success: bool):
        self.daily_trade_count += 1
        if success:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        
        logger.info(f"Trade recorded: success={success}, daily_count={self.daily_trade_count}, consecutive_losses={self.consecutive_losses}")

# --- 4. Smart Position Sizer ---
class SmartPositionSizer:
    @staticmethod
    def calculate_optimal_size(account_value: float, current_price: float, conviction: str, 
                             current_exposure: float, max_exposure: float) -> float:
        base_values = {
            "HIGH": account_value * 0.25,
            "MEDIUM": account_value * 0.15,
            "LOW": account_value * 0.08
        }
        
        base_value = base_values.get(conviction, account_value * 0.1)
        available_exposure = max_exposure - current_exposure
        base_value = min(base_value, available_exposure * 0.8)
        base_value = max(MIN_POSITION_VALUE, min(base_value, MAX_POSITION_VALUE))
        
        position_size = base_value / current_price
        
        logger.info(f"Smart sizing: account=${account_value:.2f}, base=${base_value:.2f}, size={position_size:.4f}, conviction={conviction}")
        
        return position_size

# --- 5. Technical Indicators Class ---
class TechnicalIndicators:
    @staticmethod
    def calculate_rsi(prices, period=14):
        if len(prices) < period + 1:
            return 50
            
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def get_trading_signal(prices, current_price):
        if len(prices) < 26:
            return "HOLD", "LOW", 0.3, "Insufficient data"
            
        rsi = TechnicalIndicators.calculate_rsi(prices)
        
        if rsi < 28:
            return "LONG", "HIGH", 0.8, f"RSI strongly oversold ({rsi:.1f})"
        elif rsi > 72:
            return "SHORT", "HIGH", 0.8, f"RSI strongly overbought ({rsi:.1f})"
        elif rsi < 32:
            return "LONG", "MEDIUM", 0.6, f"RSI oversold ({rsi:.1f})"
        elif rsi > 68:
            return "SHORT", "MEDIUM", 0.6, f"RSI overbought ({rsi:.1f})"
        elif 45 < rsi < 55:
            return "HOLD", "LOW", 0.2, f"RSI neutral ({rsi:.1f}) - no edge"
        
        return "HOLD", "LOW", 0.4, f"RSI: {rsi:.1f} - waiting for better setup"

# --- 6. Data Sources ---
class DataSources:
    COINGECKO_IDS = { 
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", 
        "XRP": "ripple", "DOGE": "dogecoin", "BNB": "binancecoin" 
    }
    
    async def get_coingecko_prices(self, symbols: list) -> dict:
        ids = ",".join(self.COINGECKO_IDS[sym] for sym in symbols if sym in self.COINGECKO_IDS)
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    response.raise_for_status()
                    data = await response.json()
                    prices = {}
                    for sym in symbols:
                        if sym in self.COINGECKO_IDS:
                            cg_id = self.COINGECKO_IDS[sym]
                            if cg_id in data:
                                prices[sym] = {
                                    "price": data[cg_id]["usd"],
                                    "change_24h_pct": data[cg_id].get("usd_24h_change", 0.0)
                                }
                    return prices
        except Exception as e:
            logger.error(f"Failed to fetch CoinGecko prices: {e}")
            return {}

    async def fetch_historical_prices(self, coin: str, limit: int = 100):
        try:
            cg_id = self.COINGECKO_IDS.get(coin)
            if not cg_id:
                return []
                
            url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days=7&interval=hourly"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    response.raise_for_status()
                    data = await response.json()
                    prices = [point[1] for point in data.get('prices', [])[-limit:]]
                    return prices
        except Exception as e:
            logger.error(f"Failed to fetch historical prices for {coin}: {e}")
            return []

# --- 7. Hyperliquid API Client ---
class HyperliquidAPI:
    def __init__(self):
        if CONFIG["hyperliquid_private_key"]: 
            self.wallet = Account.from_key(CONFIG["hyperliquid_private_key"])
        elif CONFIG["mnemonic"]: 
            self.wallet = Account.from_mnemonic(CONFIG["mnemonic"])
        else: 
            raise ValueError("Either HYPERLIQUID_PRIVATE_KEY or MNEMONIC must be provided")
        
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.exchange = Exchange(self.wallet, constants.MAINNET_API_URL)
        self.account_address = self.wallet.address
        self.meta = self.info.meta()
        self.asset_info = {asset['name']: asset for asset in self.meta['universe']}
        
        self.asset_tick_sizes = {}
        self.asset_sz_decimals = {}
        
        for asset in self.meta['universe']:
            asset_name = asset['name']
            tick_size = float(asset.get('tickSize', '0.01'))
            self.asset_tick_sizes[asset_name] = tick_size
            sz_decimals = asset.get('szDecimals', 8)
            self.asset_sz_decimals[asset_name] = sz_decimals
            
        logger.info(f"Hyperliquid client initialized for account: {self.account_address}")

    async def _retry(self, fn, *args, **kwargs):
        for attempt in range(3):
            try: 
                return await asyncio.to_thread(fn, *args, **kwargs)
            except Exception as e:
                logger.warning(f"Hyperliquid call failed (attempt {attempt + 1}): {e}")
                if attempt == 2: 
                    raise
                await asyncio.sleep(1.0 * (2 ** attempt))

    def get_sz_decimals(self, coin): 
        return self.asset_sz_decimals.get(coin, 8)

    def get_tick_size(self, coin):
        return self.asset_tick_sizes.get(coin, 0.01)

    def round_to_tick_size(self, price: float, coin: str) -> float:
        tick_size = self.get_tick_size(coin)
        if tick_size <= 0:
            return price
            
        decimal_price = decimal.Decimal(str(price))
        decimal_tick = decimal.Decimal(str(tick_size))
        
        num_ticks = decimal_price / decimal_tick
        rounded_ticks = num_ticks.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP)
        rounded_price = float(rounded_ticks * decimal_tick)
        
        return rounded_price

    def round_size(self, size: float, coin: str) -> float:
        sz_decimals = self.get_sz_decimals(coin)
        return round(size, sz_decimals)

    async def get_user_state(self): 
        return await self._retry(self.info.user_state, self.account_address)
    
    async def get_all_mids(self): 
        return await self._retry(self.info.all_mids)
    
    async def get_user_fills(self): 
        return await self._retry(self.info.user_fills, self.account_address)

    async def place_order(self, coin, is_buy, sz, limit_px, reduce_only=False):
        rounded_sz = self.round_size(sz, coin)
        rounded_px = self.round_to_tick_size(limit_px, coin)
        
        logger.info(f"Attempting to place order: {'BUY' if is_buy else 'SELL'} {rounded_sz} {coin} @ {rounded_px}")

        order_type = {"limit": {"tif": "Gtc"}}
        
        try:
            result = await self._retry(self.exchange.order, coin, is_buy, rounded_sz, rounded_px, order_type, reduce_only=reduce_only)
            
            if result.get("status") == "ok":
                statuses = result["response"]["data"]["statuses"]
                for status in statuses:
                    if "resting" in status: 
                        logger.info(f"✅ Order successfully placed. OID: {status['resting']['oid']}")
                        return result
                    elif "filled" in status: 
                        logger.info(f"✅ Order was filled immediately. OID: {status['filled']['oid']}")
                        return result
                    elif "error" in status: 
                        logger.error(f"❌ Order REJECTED by Hyperliquid: {status['error']}")
                        return result
            else:
                logger.error(f"❌ Order placement failed with non-OK status")
            return result
        except Exception as e:
            logger.error(f"An exception occurred during order placement: {e}")
            return {"status": "error", "message": str(e)}

# --- 8. Enhanced Market Analysis ---
class EnhancedMarketAnalyzer:
    def __init__(self, data_sources):
        self.data_sources = data_sources

    async def analyze_market_conditions(self, prices_24h: dict) -> dict:
        analysis = {}
        
        for asset, data in prices_24h.items():
            price = data.get('price', 0)
            change_24h = data.get('change_24h_pct', 0)
            
            historical_prices = await self.data_sources.fetch_historical_prices(asset)
            tech_signal, conviction, quality_score, tech_reason = "HOLD", "LOW", 0.3, "No historical data"
            
            if historical_prices:
                tech_signal, conviction, quality_score, tech_reason = TechnicalIndicators.get_trading_signal(historical_prices, price)
            
            momentum_score = min(10, abs(change_24h) * 1.5)
            momentum_strength = "STRONG" if abs(change_24h) > 8 else "MODERATE" if abs(change_24h) > 4 else "WEAK"
            direction = "BULLISH" if change_24h > 0 else "BEARISH"
            volatility = "HIGH" if abs(change_24h) > 12 else "MEDIUM" if abs(change_24h) > 6 else "LOW"
            
            analysis[asset] = {
                'momentum': momentum_strength, 'direction': direction, 'momentum_score': momentum_score,
                'volatility': volatility, 'tech_signal': tech_signal, 'tech_conviction': conviction,
                'quality_score': quality_score, 'tech_reason': tech_reason, 'abs_change': abs(change_24h)
            }
        
        return analysis

# --- 9. Enhanced Trading Agent ---
class TradingAgent:
    def __init__(self):
        self.client = OpenAI(api_key=CONFIG["gaia_api_key"], base_url=CONFIG["gaia_node_url"])
        self.model = CONFIG["gaia_model_name"]

    def _robust_json_load(self, text: str):
        text = text.strip()
        match = re.search(r"```(json)?\s*([\[\{].*?[\]\}])\s*```", text, re.DOTALL)
        if match:
            text = match.group(2)

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return [parsed]
            return parsed
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            raise

    def get_trade_decision(self, assets, context, current_holdings, competition_mode="BALANCED"):
        system_prompt = """You are a professional trader in a competition. Current PnL: -2%. You need to achieve 10%+ profit.

CRITICAL RULES:
1. Only take HIGH conviction trades (RSI <30 for LONG, RSI >70 for SHORT)
2. Minimum position size: $50, Maximum: $300
3. Maximum 4 concurrent positions
4. Maximum 10 trades per day
5. Use 1.5% stop-loss and 3% take-profit
6. Focus on QUALITY over quantity

TRADE SELECTION PRIORITY:
1. STRONG RSI signals only (RSI <28 or RSI >72) - HIGH conviction
2. Good RSI signals (RSI <32 or RSI >68) - MEDIUM conviction  
3. Avoid neutral RSI (45-55) - no edge
4. Focus on 2-3 best opportunities, not all assets

POSITION SIZING:
- HIGH conviction: $200-$300 position size
- MEDIUM conviction: $100-$200 position size  
- LOW conviction: HOLD or $50-$100 only if no better options

BE SELECTIVE. Wait for high-quality setups. Your goal is 10%+ profit.

JSON OUTPUT:
[{"token": "BTC", "action": "LONG", "size": "0.008", "conviction": "HIGH", "reason": "RSI 26.5 strong oversold"}]

Your response MUST be ONLY a valid JSON array. NO MARKDOWN, NO EXPLANATORY TEXT."""

        if len(current_holdings) == 0:
            system_prompt += "\n\nPORTFOLIO IS EMPTY: Look for 1-2 high conviction entries to start."
        else:
            system_prompt += f"\n\nCURRENT HOLDINGS: {list(current_holdings)}. Manage these first, then look for new opportunities."

        user_prompt = f"Assets to analyze: {json.dumps(assets)}\n\nCurrent Context:\n{context}"
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

        try:
            response = self.client.chat.completions.create(model=self.model, messages=messages)
            final_content = response.choices[0].message.content
            return self._robust_json_load(final_content)
        except Exception as e:
            logger.error(f"Error in LLM decision making: {e}")
            return None

# --- 10. Global Database Instance ---
db_manager: Optional[DatabaseManager] = None

# --- 11. API Routes with Lifespan Context Manager ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI app startup/shutdown"""
    global db_manager
    logger.info("✅ API STARTUP: Initializing database manager")
    db_manager = DatabaseManager(skip_init=False)
    if db_manager.db_available:
        logger.info("✅ Database connection established")
    else:
        logger.warning("⚠️  Database unavailable - API running in read-only mode")
    yield
    logger.info("API SHUTDOWN: Closing database connection")
    if db_manager:
        db_manager.close()

app = FastAPI(title="Trading Agent API", version="1.0.0", lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    db_status = "connected" if db_manager and db_manager.db_available else "disconnected"
    return {
        "status": "healthy",
        "database": db_status,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/decisions")
async def get_decisions(
    token: Optional[str] = Query(None, description="Filter by token symbol"),
    action: Optional[str] = Query(None, description="Filter by action (LONG/SHORT/HOLD)"),
    limit: int = Query(100, ge=1, le=1000, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """Get trade decisions from database with optional filters"""
    try:
        if not db_manager or not db_manager.db_available:
            raise HTTPException(status_code=503, detail="Database connection unavailable")
        
        results = db_manager.get_decisions(token=token, action=action, limit=limit, offset=offset)
        return {
            "count": len(results),
            "limit": limit,
            "offset": offset,
            "decisions": results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in GET /decisions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/decisions/stats")
async def get_stats(token: Optional[str] = Query(None, description="Filter by token symbol")):
    """Get statistics about stored decisions"""
    try:
        if not db_manager or not db_manager.db_available:
            raise HTTPException(status_code=503, detail="Database connection unavailable")
        
        stats = db_manager.get_decision_stats(token=token)
        return {
            "token": token or "all",
            "stats": stats,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in GET /decisions/stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/decisions/{token}")
async def get_token_decisions(
    token: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """Get all decisions for a specific token"""
    try:
        if not db_manager or not db_manager.db_available:
            raise HTTPException(status_code=503, detail="Database connection unavailable")
        
        results = db_manager.get_decisions(token=token.upper(), limit=limit, offset=offset)
        return {
            "token": token.upper(),
            "count": len(results),
            "limit": limit,
            "offset": offset,
            "decisions": results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in GET /decisions/{{token}}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- 12. Optimized Main Agent ---
class MainAgent:
    def __init__(self, assets, interval):
        self.assets = assets
        self.interval_seconds = self._get_interval_seconds(interval)
        self.hyperliquid = HyperliquidAPI()
        self.agent = TradingAgent()
        self.data_sources = DataSources()
        self.analyzer = EnhancedMarketAnalyzer(self.data_sources)
        self.trade_manager = TradeManager()
        self.position_sizer = SmartPositionSizer()
        self.initial_account_value = 1000.0

    def _get_interval_seconds(self, interval_str):
        unit = interval_str[-1].lower()
        value = int(interval_str[:-1])
        return value * 60 if unit == 'm' else value * 3600 if unit == 'h' else 86400

    async def run(self):
        logger.info(f"--- OPTIMIZED AGENT STARTING - Focus on Quality Trades ---")
        
        while True:
            try:
                state = await self.hyperliquid.get_user_state()
                account_value = float(state["marginSummary"]["accountValue"])
                
                mids = await self.hyperliquid.get_all_mids()
                current_exposure = 0
                current_holdings = set()
                for p in state.get('assetPositions', []):
                    coin = p["position"]["coin"]
                    size = abs(float(p["position"]["szi"]))
                    price = float(mids.get(coin, 0))
                    current_exposure += size * price
                    current_holdings.add(coin)
                
                max_exposure = account_value * MAX_TOTAL_EXPOSURE_PERCENTAGE
                
                if not self.trade_manager.can_trade(len(current_holdings)):
                    logger.info("Trade limits reached - skipping cycle")
                    await asyncio.sleep(self.interval_seconds)
                    continue
                
                context = await self._build_enhanced_context(state, account_value, current_holdings)
                decisions = self.agent.get_trade_decision(self.assets, context, current_holdings, "BALANCED")
                
                if decisions: 
                    await self._process_optimized_decisions(decisions, account_value, current_exposure, max_exposure, current_holdings)
                
                await asyncio.sleep(self.interval_seconds)
                
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                await asyncio.sleep(60)

    async def _build_enhanced_context(self, state, account_value, current_holdings):
        mids, gecko_prices = await asyncio.gather(
            self.hyperliquid.get_all_mids(), 
            self.data_sources.get_coingecko_prices(self.assets)
        )
        
        market_analysis = await self.analyzer.analyze_market_conditions(gecko_prices)
        return_pct = ((account_value - self.initial_account_value) / self.initial_account_value) * 100
        
        context = f"""## Performance & Limits
- Account Value: ${account_value:.2f}
- PnL: {return_pct:.2f}% (Target: 10%+)
- Daily Trades: {self.trade_manager.daily_trade_count}/{MAX_DAILY_TRADES}
- Consecutive Losses: {self.trade_manager.consecutive_losses}
- Current Holdings: {list(current_holdings)}
- Position Limits: ${MIN_POSITION_VALUE}-${MAX_POSITION_VALUE}

## Market Analysis with Technical Signals
"""
        
        for asset in self.assets:
            hl_price = mids.get(asset, 'N/A')
            cg_data = gecko_prices.get(asset, {})
            cg_price = cg_data.get("price", 'N/A')
            cg_change = cg_data.get("change_24h_pct", 'N/A')
            analysis = market_analysis.get(asset, {})
            
            context += (f"- {asset}: Price=${cg_price}, 24h Change={cg_change}%, "
                       f"Signal={analysis.get('tech_signal', 'N/A')}, "
                       f"Conviction={analysis.get('tech_conviction', 'N/A')}\n")

        high_conviction_assets = [asset for asset, analysis in market_analysis.items() 
                                 if analysis.get('tech_conviction') == 'HIGH']
        if high_conviction_assets:
            context += f"\n## HIGH Conviction Opportunities: {', '.join(high_conviction_assets)}\n"

        return context

    async def _process_optimized_decisions(self, decisions, account_value, current_exposure, max_exposure, current_holdings):
        """Process decisions with enhanced Token Metrics signals"""
        logger.info(f"Processing {len(decisions)} optimized decisions")
        mids = await self.hyperliquid.get_all_mids()
        
        trade_executed = False
        return_pct = ((account_value - self.initial_account_value) / self.initial_account_value) * 100

        for decision in decisions:
            if trade_executed:
                break
                
            try:
                action, token = decision.get("action", "").upper(), decision.get("token")
                conviction = decision.get("conviction", "LOW").upper()
                reason = decision.get("reason", "No reason provided")
                size = float(decision.get("size", 0))
                
                if not token or token not in self.assets:
                    continue

                # Store decision in database
                decision_data = {
                    "token": token,
                    "action": action,
                    "conviction": conviction,
                    "size": size,
                    "reason": reason,
                    "account_value": account_value,
                    "pnl_percentage": return_pct,
                    "daily_trade_count": self.trade_manager.daily_trade_count,
                    "consecutive_losses": self.trade_manager.consecutive_losses
                }
                
                try:
                    if db_manager and db_manager.db_available:
                        db_manager.store_decision(decision_data)
                except Exception as e:
                    logger.warning(f"Failed to store decision for {token}: {e}")

                if action == "HOLD":
                    logger.info(f"Holding {token} - {reason}")
                    continue

                logger.info(f"Processing {action} for {token} (Conviction: {conviction})")

                if action in ("LONG", "SHORT"):
                    current_price = float(mids.get(token, 0))
                    if current_price == 0:
                        continue

                    # Calculate optimal position size
                    position_size = self.position_sizer.calculate_optimal_size(
                        account_value, current_price, conviction, current_exposure, max_exposure
                    )
                    
                    position_value = position_size * current_price
                    if position_value < MIN_POSITION_VALUE:
                        logger.warning(f"Position too small for {token}: ${position_value:.2f}")
                        continue
                        
                    if position_value > MAX_POSITION_VALUE:
                        logger.warning(f"Position too large for {token}: ${position_value:.2f}")
                        continue

                    # Calculate entry price with tight slippage
                    slippage = 0.0005
                    if action == "LONG":
                        limit_price = current_price * (1 + slippage)
                        is_buy = True
                    else:  # SHORT
                        limit_price = current_price * (1 - slippage)
                        is_buy = False
                    
                    rounded_sz = self.hyperliquid.round_size(position_size, token)
                    rounded_px = self.hyperliquid.round_to_tick_size(limit_price, token)
                    
                    logger.info(f"Executing {action} {token}: size={rounded_sz}, value=${rounded_sz * rounded_px:.2f}")

                    # Place order
                    result = await self.hyperliquid.place_order(token, is_buy, rounded_sz, rounded_px)
                    
                    if result and result.get("status") == "ok":
                        # Check if order was actually placed (not rejected)
                        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                        order_placed = any(status.get("resting") or status.get("filled") for status in statuses)
                        
                        if order_placed:
                            trade_executed = True
                            self.trade_manager.record_trade(True)
                            logger.info(f"✅ Trade executed: {action} {rounded_sz} {token} @ ${rounded_px:.4f}")
                            
                            # Place take profit and stop loss with CORRECT direction
                            await self.place_tp_sl_orders(token, rounded_sz, rounded_px, is_buy)
                        else:
                            logger.error("Order was rejected by exchange")
                            self.trade_manager.record_trade(False)
                    else:
                        self.trade_manager.record_trade(False)

            except Exception as e:
                logger.error(f"Failed to process decision: {e}")
                self.trade_manager.record_trade(False)

        return trade_executed

    async def place_tp_sl_orders(self, coin: str, size: float, entry_price: float, is_long: bool):
        """Place take profit and stop loss orders with correct direction"""
        try:
            # Get current price to ensure TP/SL are reasonable
            mids = await self.hyperliquid.get_all_mids()
            current_price = float(mids.get(coin, entry_price))
            
            if is_long:
                # For LONG positions:
                # - Take Profit: SELL to close at higher price
                # - Stop Loss: SELL to close at lower price
                tp_price = entry_price * (1 + TAKE_PROFIT_PCT)
                sl_price = entry_price * (1 - STOP_LOSS_PCT)
                
                # Ensure TP is above current price and SL is below current price
                tp_price = max(tp_price, current_price * 1.001)  # At least 0.1% above current
                sl_price = min(sl_price, current_price * 0.999)  # At least 0.1% below current
                
                # For LONG positions, we SELL to close (is_buy=False)
                tp_is_buy = False
                sl_is_buy = False
                
            else:
                # For SHORT positions:
                # - Take Profit: BUY to close at lower price  
                # - Stop Loss: BUY to close at higher price
                tp_price = entry_price * (1 - TAKE_PROFIT_PCT)
                sl_price = entry_price * (1 + STOP_LOSS_PCT)
                
                # Ensure TP is below current price and SL is above current price
                tp_price = min(tp_price, current_price * 0.999)  # At least 0.1% below current
                sl_price = max(sl_price, current_price * 1.001)  # At least 0.1% above current
                
                # For SHORT positions, we BUY to close (is_buy=True)
                tp_is_buy = True
                sl_is_buy = True
            
            # Round prices to valid tick sizes
            tp_price = self.hyperliquid.round_to_tick_size(tp_price, coin)
            sl_price = self.hyperliquid.round_to_tick_size(sl_price, coin)
            
            logger.info(f"Placing TP/SL for {coin}: TP=${tp_price:.4f} ({'BUY' if tp_is_buy else 'SELL'}), "
                    f"SL=${sl_price:.4f} ({'BUY' if sl_is_buy else 'SELL'}) (entry: ${entry_price:.4f}, "
                    f"position: {'LONG' if is_long else 'SHORT'})")
            
            # Place take profit (close position)
            tp_result = await self.hyperliquid.place_order(coin, tp_is_buy, size, tp_price, reduce_only=True)
            if tp_result and tp_result.get("status") == "ok":
                statuses = tp_result.get("response", {}).get("data", {}).get("statuses", [])
                if any(status.get("resting") or status.get("filled") for status in statuses):
                    logger.info(f"✅ Take profit placed: {coin} @ ${tp_price:.4f}")
                else:
                    logger.error(f"Failed to place take profit for {coin}: Order rejected")
            else:
                logger.error(f"Failed to place take profit for {coin}: {tp_result}")
            
            # Place stop loss (close position)
            sl_result = await self.hyperliquid.place_order(coin, sl_is_buy, size, sl_price, reduce_only=True)
            if sl_result and sl_result.get("status") == "ok":
                statuses = sl_result.get("response", {}).get("data", {}).get("statuses", [])
                if any(status.get("resting") or status.get("filled") for status in statuses):
                    logger.info(f"✅ Stop loss placed: {coin} @ ${sl_price:.4f}")
                else:
                    logger.error(f"Failed to place stop loss for {coin}: Order rejected")
            else:
                logger.error(f"Failed to place stop loss for {coin}: {sl_result}")
            
        except Exception as e:
            logger.error(f"Failed to place TP/SL for {coin}: {e}")

# --- Main Execution ---
if __name__ == "__main__":
    logger.info("="*80)
    logger.info("STARTING TRADING AGENT WITH API SERVER")
    logger.info("="*80)
    
    assets = [asset.strip().upper() for asset in CONFIG["assets"].split(',')]
    
    # Start FastAPI server in a separate thread
    import threading
    
    def run_server():
        logger.info(f"🚀 Starting FastAPI server on {CONFIG['api_host']}:{CONFIG['api_port']}")
        try:
            uvicorn.run(
                app,
                host=CONFIG["api_host"],
                port=CONFIG["api_port"],
                log_level="info"
            )
        except Exception as e:
            logger.error(f"❌ API server error: {e}")
    
    server_thread = threading.Thread(target=run_server, daemon=False)
    server_thread.start()
    
    # Give the server a moment to start
    time.sleep(2)
    logger.info("✅ API SERVER STARTED - Ready to accept requests")
    logger.info(f"📊 API endpoints available at http://localhost:{CONFIG['api_port']}")
    
    # Start the main trading agent
    agent = MainAgent(assets=assets, interval=CONFIG["interval"])
    
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        logger.info("⏹️  Optimized Agent shutdown by user.")
    except Exception as e:
        logger.critical(f"❌ Optimized Agent stopped: {e}")
        sys.exit(1)