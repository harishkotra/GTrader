# GTrader

This is a sophisticated cryptocurrency trading bot that interfaces with the Hyperliquid exchange. The bot implements various trading strategies using technical analysis and AI-driven decision making.

#2 on [Recall Agents vs Alpha Arena Models](https://app.recall.network/competitions/51cee080-b5de-445d-a532-d1d474a67a30)

<img width="970" height="717" alt="image" src="https://github.com/user-attachments/assets/44fb754f-9984-4090-ae88-f7298e5850a0" />

## Components Overview

### 1. Configuration & Environment Setup
- Uses environment variables for configuration
- Key configuration includes API keys, trading parameters, and asset lists
- Implements logging for debugging and monitoring

### 2. Trade Manager
The `TradeManager` class handles trade tracking and risk management:
- Tracks daily trade counts
- Monitors consecutive losses
- Enforces trading limits
- Resets counters daily
- Implements safety checks before allowing new trades

### 3. Smart Position Sizer
The `SmartPositionSizer` class handles position sizing:
- Calculates optimal position sizes based on:
  - Account value
  - Trade conviction level
  - Current market exposure
  - Risk parameters
- Enforces minimum ($50) and maximum ($300) position sizes
- Adjusts size based on conviction levels (HIGH/MEDIUM/LOW)

### 4. Technical Indicators
The `TechnicalIndicators` class provides market analysis tools:
- Calculates RSI (Relative Strength Index)
- Generates trading signals based on RSI levels
- Provides conviction levels and reasoning for trades
- Implements basic momentum analysis

### 5. Data Sources
The `DataSources` class handles market data retrieval:
- Interfaces with CoinGecko API
- Fetches current prices and 24-hour changes
- Retrieves historical price data
- Manages coin ID mappings

### 6. Hyperliquid API Client
The `HyperliquidAPI` class manages exchange interactions:
- Handles authentication
- Manages order placement
- Implements proper size and price rounding
- Provides retry mechanism for API calls
- Tracks asset-specific parameters (tick sizes, decimals)

### 7. Enhanced Market Analysis
The `EnhancedMarketAnalyzer` class provides detailed market analysis:
- Combines technical indicators
- Analyzes market momentum
- Evaluates market volatility
- Generates quality scores for trading opportunities

### 8. Trading Agent
The `TradingAgent` class implements AI-driven decision making:
- Uses OpenAI/Gaia for trade decisions
- Processes market context
- Generates trade recommendations
- Handles JSON parsing and validation

### 9. Main Agent
The `MainAgent` class orchestrates the entire trading system:
- Initializes all components
- Manages the main trading loop
- Processes trading decisions
- Implements position management
- Handles take-profit and stop-loss orders

## Key Functions

### Trade Execution
```python
async def _process_optimized_decisions(self, decisions, account_value, current_exposure, max_exposure, current_holdings)
```
- Processes trade decisions
- Implements position sizing
- Places orders with proper risk management
- Sets take-profit and stop-loss orders

### Risk Management
```python
async def place_tp_sl_orders(self, coin: str, size: float, entry_price: float, is_long: bool)
```
- Places take-profit orders
- Sets stop-loss orders
- Manages position direction (long/short)
- Implements proper price rounding

### Market Analysis
```python
async def analyze_market_conditions(self, prices_24h: dict) -> dict
```
- Analyzes current market conditions
- Evaluates technical indicators
- Assesses market momentum
- Generates trading signals

## Configuration Parameters

- `MAX_RISK_PER_TRADE`: 3% maximum risk per trade
- `MIN_POSITION_VALUE`: $50 minimum position size
- `MAX_POSITION_VALUE`: $300 maximum position size
- `STOP_LOSS_PCT`: 1.5% stop loss percentage
- `TAKE_PROFIT_PCT`: 3% take profit percentage
- `MAX_TOTAL_EXPOSURE_PERCENTAGE`: 100% maximum total exposure

## Environment Variables Required

- `TAAPI_API_KEY`: (Optional) Technical analysis API key
- `HYPERLIQUID_PRIVATE_KEY`: Private key for Hyperliquid exchange
- `MNEMONIC`: Alternative to private key for authentication
- `GAIA_API_KEY`: API key for AI decision making
- `GAIA_NODE_URL`: URL for AI service
- `ASSETS`: Comma-separated list of assets to trade
- `INTERVAL`: Trading interval (e.g., "15m")
