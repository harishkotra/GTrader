"""
Myriad Protocol API V2 Client

This module provides a client to interact with the Myriad Protocol API V2.
See MYRIAD_API_V2.md for full API documentation.
"""

import os
import logging
from typing import Dict, List, Optional, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class MyriadAPIClient:
    """Client for interacting with Myriad Protocol API V2"""

    # Network IDs
    ABSTRACT_MAINNET = 2741
    ABSTRACT_TESTNET = 11124
    LINEA_MAINNET = 59144
    LINEA_TESTNET = 59141
    BNB_MAINNET = 56
    BNB_TESTNET = 97
    CELO_TESTNET = 44787

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api-v2.myriadprotocol.com/",
        timeout: int = 30
    ):
        """
        Initialize Myriad API client

        Args:
            api_key: API key for authentication (can also use MYRIAD_API_KEY env var)
            base_url: Base URL for API (default: production)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key or os.getenv("MYRIAD_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        # Setup session with retry logic
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Set default headers
        if self.api_key:
            self.session.headers.update({"x-api-key": self.api_key})

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Make HTTP request to API

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (without base URL)
            params: Query parameters
            json: JSON body for POST requests

        Returns:
            Response data as dict

        Raises:
            requests.exceptions.RequestException: On API errors
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {method} {url} - {str(e)}")
            raise

    # Questions endpoints

    def get_questions(
        self,
        page: int = 1,
        limit: int = 20,
        keyword: Optional[str] = None,
        min_markets: Optional[int] = None,
        max_markets: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get paginated list of questions with associated markets

        Args:
            page: Page number (default: 1)
            limit: Results per page (default: 20, max: 100)
            keyword: Search keyword for question title
            min_markets: Minimum number of linked markets
            max_markets: Maximum number of linked markets

        Returns:
            Response with questions data and pagination info
        """
        params = {"page": page, "limit": limit}
        if keyword:
            params["keyword"] = keyword
        if min_markets is not None:
            params["min_markets"] = min_markets
        if max_markets is not None:
            params["max_markets"] = max_markets

        return self._make_request("GET", "/questions", params=params)

    def get_question(self, question_id: int) -> Dict[str, Any]:
        """
        Get a single question with markets and outcomes

        Args:
            question_id: Question ID

        Returns:
            Question data with markets
        """
        return self._make_request("GET", f"/questions/{question_id}")

    # Markets endpoints

    def get_markets(
        self,
        page: int = 1,
        limit: int = 20,
        sort: str = "volume",
        order: str = "desc",
        network_id: Optional[int] = None,
        state: Optional[str] = None,
        token_address: Optional[str] = None,
        topics: Optional[str] = None,
        keyword: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get paginated list of markets with filtering and sorting

        Args:
            page: Page number (default: 1)
            limit: Results per page (default: 20, max: 100)
            sort: Sort field (volume, volume_24h, liquidity, expires_at, published_at)
            order: Sort order (asc, desc)
            network_id: Filter by network ID
            state: Filter by state (open, closed, resolved)
            token_address: Filter by token address
            topics: Comma-separated list of topics
            keyword: Full-text search across title, description, outcome titles

        Returns:
            Response with markets data and pagination info
        """
        params = {"page": page, "limit": limit, "sort": sort, "order": order}
        if network_id is not None:
            params["network_id"] = network_id
        if state:
            params["state"] = state
        if token_address:
            params["token_address"] = token_address
        if topics:
            params["topics"] = topics
        if keyword:
            params["keyword"] = keyword

        return self._make_request("GET", "/markets", params=params)

    def get_market(
        self,
        market_id: Optional[int] = None,
        slug: Optional[str] = None,
        network_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get a single market by slug or by marketId + network_id

        Args:
            market_id: Blockchain market ID
            slug: Market slug
            network_id: Network ID (required if using market_id)

        Returns:
            Market data with price charts
        """
        if slug:
            return self._make_request("GET", f"/markets/{slug}")
        elif market_id is not None and network_id is not None:
            return self._make_request("GET", f"/markets/{market_id}", params={"network_id": network_id})
        else:
            raise ValueError("Must provide either slug or (market_id + network_id)")

    def get_market_events(
        self,
        market_id: Optional[int] = None,
        slug: Optional[str] = None,
        network_id: Optional[int] = None,
        page: int = 1,
        limit: int = 50,
        since: Optional[int] = None,
        until: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get paginated market events (trades, liquidity, claims)

        Args:
            market_id: Blockchain market ID
            slug: Market slug
            network_id: Network ID (required if using market_id)
            page: Page number
            limit: Results per page
            since: Unix timestamp (inclusive)
            until: Unix timestamp (inclusive)

        Returns:
            Market events data
        """
        params = {"page": page, "limit": limit}
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        if network_id is not None:
            params["network_id"] = network_id

        if slug:
            endpoint = f"/markets/{slug}/events"
        elif market_id is not None:
            endpoint = f"/markets/{market_id}/events"
        else:
            raise ValueError("Must provide either slug or market_id")

        return self._make_request("GET", endpoint, params=params)

    def get_market_holders(
        self,
        market_id: Optional[int] = None,
        slug: Optional[str] = None,
        network_id: Optional[int] = None,
        page: int = 1,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Get market holders grouped by outcome

        Args:
            market_id: Blockchain market ID
            slug: Market slug
            network_id: Network ID (required if using market_id)
            page: Page number
            limit: Results per page (applied per outcome)

        Returns:
            Market holders data grouped by outcome
        """
        params = {"page": page, "limit": limit}
        if network_id is not None:
            params["network_id"] = network_id

        if slug:
            endpoint = f"/markets/{slug}/holders"
        elif market_id is not None:
            endpoint = f"/markets/{market_id}/holders"
        else:
            raise ValueError("Must provide either slug or market_id")

        return self._make_request("GET", endpoint, params=params)

    def get_market_quote(
        self,
        outcome_id: int,
        action: str,
        market_id: Optional[int] = None,
        market_slug: Optional[str] = None,
        network_id: Optional[int] = None,
        value: Optional[float] = None,
        shares: Optional[float] = None,
        slippage: float = 0.005
    ) -> Dict[str, Any]:
        """
        Get trade quote and transaction calldata for a market outcome

        Args:
            outcome_id: On-chain outcome ID
            action: Trade action ('buy' or 'sell')
            market_id: On-chain market ID
            market_slug: Market slug
            network_id: Network ID (required if using market_id)
            value: Amount of tokens to spend (buy) or receive (sell)
            shares: Number of shares to buy or sell
            slippage: Slippage tolerance (0-1, default: 0.005 = 0.5%)

        Returns:
            Quote data with expected shares, prices, fees, and calldata
        """
        if market_slug:
            body = {"market_slug": market_slug}
        elif market_id is not None and network_id is not None:
            body = {"market_id": market_id, "network_id": network_id}
        else:
            raise ValueError("Must provide either market_slug or (market_id + network_id)")

        body["outcome_id"] = outcome_id
        body["action"] = action
        body["slippage"] = slippage

        # For buy: only value; for sell: value or shares
        if action == "buy":
            if value is None:
                raise ValueError("For buy action, 'value' is required")
            body["value"] = value
        elif action == "sell":
            if value is None and shares is None:
                raise ValueError("For sell action, either 'value' or 'shares' is required")
            if value is not None:
                body["value"] = value
            elif shares is not None:
                body["shares"] = shares
        else:
            raise ValueError("Action must be 'buy' or 'sell'")

        return self._make_request("POST", "/markets/quote", json=body)

    # Users endpoints

    def get_user_events(
        self,
        address: str,
        page: int = 1,
        limit: int = 50,
        market_id: Optional[int] = None,
        network_id: Optional[int] = None,
        since: Optional[int] = None,
        until: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get paginated user events across markets

        Args:
            address: User wallet address
            page: Page number
            limit: Results per page
            market_id: Filter by market ID
            network_id: Filter by network ID
            since: Unix timestamp (inclusive)
            until: Unix timestamp (inclusive)

        Returns:
            User events data
        """
        params = {"page": page, "limit": limit}
        if market_id is not None:
            params["marketId"] = market_id
        if network_id is not None:
            params["networkId"] = network_id
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until

        return self._make_request("GET", f"/users/{address}/events", params=params)

    def get_user_portfolio(
        self,
        address: str,
        page: int = 1,
        limit: int = 20,
        market_slug: Optional[str] = None,
        market_id: Optional[int] = None,
        network_id: Optional[int] = None,
        token_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get aggregated user positions per market/outcome/network

        Args:
            address: User wallet address
            page: Page number
            limit: Results per page
            market_slug: Filter by market slug
            market_id: Filter by market ID
            network_id: Filter by network ID
            token_address: Filter by token address

        Returns:
            User portfolio data
        """
        params = {"page": page, "limit": limit}
        if market_slug:
            params["market_slug"] = market_slug
        if market_id is not None:
            params["market_id"] = market_id
        if network_id is not None:
            params["network_id"] = network_id
        if token_address:
            params["token_address"] = token_address

        return self._make_request("GET", f"/users/{address}/portfolio", params=params)


# Example usage
if __name__ == "__main__":
    # Initialize client
    client = MyriadAPIClient()

    # Get markets on Abstract mainnet
    markets = client.get_markets(
        network_id=MyriadAPIClient.ABSTRACT_MAINNET,
        state="open",
        limit=10
    )
    print(f"Found {len(markets.get('data', []))} open markets on Abstract")

    # Get market quote
    if markets.get("data"):
        market = markets["data"][0]
        quote = client.get_market_quote(
            market_slug=market["slug"],
            outcome_id=0,
            action="buy",
            value=100,
            slippage=0.01
        )
        print(f"Quote for buying $100: {quote['shares']} shares at avg price {quote['price_average']}")
