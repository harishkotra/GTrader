"""
GTrader REST API Service

This module provides a REST API to interact with GTrader's trading decisions
and integrates with the Myriad Protocol API V2.

Run with: uvicorn api:app --host 0.0.0.0 --port 8000
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import asyncio
from myriad_client import MyriadAPIClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="GTrader API",
    description="REST API for GTrader trading bot and Myriad Protocol integration",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state for tracking GTrader data
# In production, use a database like PostgreSQL or MongoDB
gtrader_state = {
    "status": "idle",
    "last_update": None,
    "account_value": 0.0,
    "positions": [],
    "recent_decisions": [],
    "trade_history": [],
    "market_analyses": [],
}


# Pydantic models

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str


class AccountInfo(BaseModel):
    account_value: float
    total_positions: int
    status: str
    last_update: Optional[str]


class Position(BaseModel):
    asset: str
    side: str
    size: float
    entry_price: float
    current_price: float
    pnl: float
    pnl_percentage: float


class TradeDecision(BaseModel):
    timestamp: str
    asset: str
    action: str
    conviction: str
    signal_type: str
    reasoning: str
    position_size: Optional[float] = None
    entry_price: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None


class MarketAnalysis(BaseModel):
    asset: str
    timestamp: str
    price: float
    change_24h: float
    rsi: float
    signal: str
    conviction: str
    quality_score: float


class Trade(BaseModel):
    timestamp: str
    asset: str
    action: str
    size: float
    price: float
    value: float
    status: str


class ConfigUpdate(BaseModel):
    max_risk_per_trade: Optional[float] = Field(None, ge=0, le=10)
    max_concurrent_trades: Optional[int] = Field(None, ge=0, le=20)
    max_daily_trades: Optional[int] = Field(None, ge=0, le=100)
    stop_loss_pct: Optional[float] = Field(None, ge=0, le=10)
    take_profit_pct: Optional[float] = Field(None, ge=0, le=20)


class MyriadMarketRequest(BaseModel):
    network_id: Optional[int] = None
    state: Optional[str] = None
    keyword: Optional[str] = None
    limit: int = Field(20, ge=1, le=100)


class MyriadQuoteRequest(BaseModel):
    market_id: Optional[int] = None
    market_slug: Optional[str] = None
    network_id: Optional[int] = None
    outcome_id: int
    action: str
    value: Optional[float] = None
    shares: Optional[float] = None
    slippage: float = 0.005


# Dependency to get Myriad client
def get_myriad_client() -> MyriadAPIClient:
    """Get Myriad API client instance"""
    api_key = os.getenv("MYRIAD_API_KEY")
    base_url = os.getenv("MYRIAD_API_URL", "https://api-v2.myriadprotocol.com/")
    return MyriadAPIClient(api_key=api_key, base_url=base_url)


# GTrader API Endpoints

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0"
    }


@app.get("/account", response_model=AccountInfo)
async def get_account_info():
    """Get GTrader account information"""
    return {
        "account_value": gtrader_state["account_value"],
        "total_positions": len(gtrader_state["positions"]),
        "status": gtrader_state["status"],
        "last_update": gtrader_state["last_update"]
    }


@app.get("/positions", response_model=List[Position])
async def get_positions():
    """Get current open positions"""
    return gtrader_state["positions"]


@app.get("/decisions", response_model=List[TradeDecision])
async def get_decisions(
    limit: int = Query(20, ge=1, le=100),
    asset: Optional[str] = None
):
    """
    Get recent trading decisions made by GTrader's AI

    Args:
        limit: Maximum number of decisions to return
        asset: Filter by asset (e.g., 'BTC', 'ETH')

    Returns:
        List of recent trading decisions
    """
    decisions = gtrader_state["recent_decisions"]

    if asset:
        decisions = [d for d in decisions if d.get("asset") == asset.upper()]

    return decisions[:limit]


@app.get("/market-analysis", response_model=List[MarketAnalysis])
async def get_market_analysis(
    asset: Optional[str] = None
):
    """
    Get current market analysis for tracked assets

    Args:
        asset: Filter by specific asset

    Returns:
        List of market analyses
    """
    analyses = gtrader_state["market_analyses"]

    if asset:
        analyses = [a for a in analyses if a.get("asset") == asset.upper()]

    return analyses


@app.get("/trades", response_model=List[Trade])
async def get_trade_history(
    limit: int = Query(50, ge=1, le=500),
    asset: Optional[str] = None,
    status: Optional[str] = None
):
    """
    Get trade history

    Args:
        limit: Maximum number of trades to return
        asset: Filter by asset
        status: Filter by status ('executed', 'filled', 'cancelled')

    Returns:
        List of historical trades
    """
    trades = gtrader_state["trade_history"]

    if asset:
        trades = [t for t in trades if t.get("asset") == asset.upper()]

    if status:
        trades = [t for t in trades if t.get("status") == status]

    return trades[:limit]


@app.get("/config")
async def get_config():
    """Get current GTrader configuration"""
    return {
        "max_risk_per_trade": 3.0,
        "min_position_value": 50.0,
        "max_position_value": 300.0,
        "stop_loss_pct": 1.5,
        "take_profit_pct": 3.0,
        "max_concurrent_trades": 4,
        "max_daily_trades": 10,
        "assets": os.getenv("ASSETS", "BTC,ETH,SOL,XRP,DOGE,BNB").split(","),
        "interval": os.getenv("INTERVAL", "15m")
    }


@app.put("/config")
async def update_config(config: ConfigUpdate):
    """
    Update GTrader configuration

    Note: This is a placeholder. In production, you would validate
    and apply changes to the running agent.
    """
    logger.info(f"Configuration update requested: {config.dict(exclude_none=True)}")
    return {
        "status": "success",
        "message": "Configuration updated (placeholder - implement actual update logic)",
        "updated_fields": config.dict(exclude_none=True)
    }


@app.get("/performance")
async def get_performance():
    """Get performance metrics and statistics"""
    trades = gtrader_state["trade_history"]

    total_trades = len(trades)
    winning_trades = len([t for t in trades if t.get("pnl", 0) > 0])
    losing_trades = len([t for t in trades if t.get("pnl", 0) < 0])

    total_pnl = sum(t.get("pnl", 0) for t in trades)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

    return {
        "account_value": gtrader_state["account_value"],
        "total_pnl": total_pnl,
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": win_rate,
        "positions": len(gtrader_state["positions"]),
        "status": gtrader_state["status"]
    }


# Myriad Protocol API Integration Endpoints

@app.get("/myriad/markets")
async def get_myriad_markets(
    network_id: Optional[int] = Query(None),
    state: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    myriad_client: MyriadAPIClient = Depends(get_myriad_client)
):
    """
    Get prediction markets from Myriad Protocol

    Args:
        network_id: Filter by network (2741=Abstract, 59144=Linea, 56=BNB)
        state: Filter by state (open, closed, resolved)
        keyword: Search keyword
        page: Page number
        limit: Results per page

    Returns:
        List of prediction markets
    """
    try:
        markets = myriad_client.get_markets(
            page=page,
            limit=limit,
            network_id=network_id,
            state=state,
            keyword=keyword
        )
        return markets
    except Exception as e:
        logger.error(f"Error fetching Myriad markets: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/myriad/markets/{market_id}")
async def get_myriad_market(
    market_id: int,
    network_id: int = Query(...),
    myriad_client: MyriadAPIClient = Depends(get_myriad_client)
):
    """
    Get a specific prediction market from Myriad Protocol

    Args:
        market_id: Market ID
        network_id: Network ID (required)

    Returns:
        Market details with price charts
    """
    try:
        market = myriad_client.get_market(
            market_id=market_id,
            network_id=network_id
        )
        return market
    except Exception as e:
        logger.error(f"Error fetching Myriad market {market_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/myriad/quote")
async def get_myriad_quote(
    request: MyriadQuoteRequest,
    myriad_client: MyriadAPIClient = Depends(get_myriad_client)
):
    """
    Get a trade quote from Myriad Protocol

    Args:
        request: Quote request parameters

    Returns:
        Quote with expected shares, prices, fees, and calldata
    """
    try:
        quote = myriad_client.get_market_quote(
            market_id=request.market_id,
            market_slug=request.market_slug,
            network_id=request.network_id,
            outcome_id=request.outcome_id,
            action=request.action,
            value=request.value,
            shares=request.shares,
            slippage=request.slippage
        )
        return quote
    except Exception as e:
        logger.error(f"Error getting Myriad quote: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/myriad/user/{address}/portfolio")
async def get_myriad_user_portfolio(
    address: str,
    network_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    myriad_client: MyriadAPIClient = Depends(get_myriad_client)
):
    """
    Get user portfolio from Myriad Protocol

    Args:
        address: User wallet address
        network_id: Filter by network
        page: Page number
        limit: Results per page

    Returns:
        User's positions across markets
    """
    try:
        portfolio = myriad_client.get_user_portfolio(
            address=address,
            network_id=network_id,
            page=page,
            limit=limit
        )
        return portfolio
    except Exception as e:
        logger.error(f"Error fetching Myriad portfolio for {address}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Helper endpoints for updating GTrader state
# These would be called by the main agent.py to update API state

@app.post("/internal/update-state")
async def update_state(state_data: Dict[str, Any]):
    """
    Internal endpoint to update GTrader state
    (Called by agent.py during trading loop)
    """
    gtrader_state.update(state_data)
    gtrader_state["last_update"] = datetime.utcnow().isoformat()
    return {"status": "success"}


@app.post("/internal/add-decision")
async def add_decision(decision: TradeDecision):
    """
    Internal endpoint to add a trading decision
    (Called by agent.py when making decisions)
    """
    gtrader_state["recent_decisions"].insert(0, decision.dict())
    # Keep only last 100 decisions
    gtrader_state["recent_decisions"] = gtrader_state["recent_decisions"][:100]
    return {"status": "success"}


@app.post("/internal/add-trade")
async def add_trade(trade: Trade):
    """
    Internal endpoint to add a completed trade
    (Called by agent.py when trades execute)
    """
    gtrader_state["trade_history"].insert(0, trade.dict())
    return {"status": "success"}


# Startup/shutdown events

@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    logger.info("GTrader API starting up...")
    gtrader_state["status"] = "running"
    gtrader_state["last_update"] = datetime.utcnow().isoformat()


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("GTrader API shutting down...")
    gtrader_state["status"] = "stopped"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
