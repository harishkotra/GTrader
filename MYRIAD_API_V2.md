# Myriad Protocol API V2 Documentation

# Myriad Protocol API Reference

This document describes the REST API exposed by the Myriad Protocol API service.

## Base URL

- Staging - [`https://api-v2.staging.myriadprotocol.com/`](https://api-v2.staging.myriadprotocol.com/)
- **Production** - [`https://api-v2.myriadprotocol.com/`](https://api-v2.myriadprotocol.com/)

## Authentication

All endpoints (except health) require an API key.

- Header: `x-api-key: <your_api_key>`
- Or Query: `?api_key=<your_api_key>`

To obtain an API key, please reach out to the Myriad team.

## Rate Limiting

- 5 requests/second per IP and/or API key.
- Headers included on responses:
    - `X-RateLimit-Limit`
    - `X-RateLimit-Remaining`
    - `X-RateLimit-Reset`

## Pagination

All list endpoints support pagination:

- `page` (default: 1)
- `limit` (default: 20, max: 100)

Response pagination object:

```json
{
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 123,
    "totalPages": 7,
    "hasNext": true,
    "hasPrev": false
  }
}
```

---

## Questions

A question is the canonical proposition (title + expiration), independent of which chain it's traded on.

The same question can have multiple markets across different chains, each with its own liquidity, prices, and activity.

Questions endpoints return the question with all its markets and a marketCount, letting clients compare performance across chains and build cross‑chain summaries, while trading/price data remains per‑market.

### GET /questions

Paginated list of questions with associated markets and outcome summaries.

Query params:

- `page`, `limit`
- `keyword`: search in question title
- `min_markets`: minimum number of linked markets
- `max_markets`: maximum number of linked markets

Example:

```
GET /questions?keyword=politics&page=2&limit=20&min_markets=2&max_markets=10

```

Response data (per question):

- `id`, `title`, `expiresAt`
- `marketCount`: number of linked markets
- `markets`: array of markets with:
    - `id` (blockchain market id), `slug`, `title`, `description`, `state`, `networkId`
    - `liquidity`, `volume`, `volume24h`, `imageUrl`, `expiresAt`, `topics`
    - `outcomes`: array with summary per outcome: `id`, `title`, `price`, `shares`

---

### GET /questions/:id

Get a single question with markets and outcomes.

Example:

```
GET /questions/1

```

Response (selected fields):

- `id`, `title`, `expiresAt`
- `markets`: array of markets with:
    - `id` (blockchain market id), `slug`, `title`, `description`, `state`, `networkId`
    - `liquidity`, `volume`, `volume24h`, `shares`, `imageUrl`, `expiresAt`, `topics`, `fees`
    - `outcomes`: array with `id`, `title`, `price`, `shares`, `imageUrl`

---

## Markets

### GET /markets

Paginated list of markets with filtering and sorting.

Query params:

- `page`, `limit` (pagination)
- `sort`: `volume` | `volume_24h` | `liquidity` | `expires_at` | `published_at` (default: `volume`)
- `order`: `asc` | `desc` (default: `desc`)
- `network_id`: number
- `state`: `open` | `closed` | `resolved`
- `token_address`: string
- `topics`: comma-separated list of topics
- `keyword`: full-text search across `title`, `description`, and outcome titles

Example:

```
GET /markets?keyword=eth&network_id=2741&page=1&limit=20&sort=volume_24h

```

Response data (per market):

- `id`: blockchain market id
- `networkId`: number
- `slug`, `title`, `description`
- `expiresAt`, `publishedAt`
- `fees`, `state`, `topics`, `resolutionSource`, `resolutionTitle`
- `tokenAddress`, `imageUrl`
- `liquidity`, `liquidityPrice`, `volume`, `volume24h`, `shares`
- `outcomes`: with numeric `id` (blockchain outcome id), `title`, `price`, `shares`, `sharesHeld`, etc.

Notes:

- Numeric monetary/decimal fields are returned as numbers.

---

### GET /markets/:id

Get a single market by slug or by `marketId + network_id`.

Modes:

- By slug: `GET /markets/{slug}`
- By id + network: `GET /markets/{marketId}?network_id=2741`

Price charts:

- Field `outcomes[*].price_charts`.
- Timeframes and buckets
    - `24h`: 5-minute (max 288)
    - `7d`: 30-minute (max 336)
    - `30d`: 4-hour (max 180)
    - `all`: 4-hour
- Series end at `min(now, expiresAt)` with backfill from the last known price before the window start.

Example:

```
GET /markets/164?network_id=2741

```

---

### GET /markets/:id/events

Paginated actions (trades/liquidity/claims) for a market, ordered by `timestamp desc`.

Lookup:

- By slug: `GET /markets/{slug}/events`
- By id + network: `GET /markets/{marketId}/events?network_id=2741`

Query params:

- `page`, `limit`
- `since`: unix seconds (inclusive)
- `until`: unix seconds (inclusive)

Response items:

- `user`: wallet address
- `action`: `buy` | `sell` | `add_liquidity` | `remove_liquidity` | `claim_winnings` | `claim_liquidity` | `claim_fees` | `claim_voided`
- `marketTitle`, `marketSlug`, `marketId`, `networkId`
- `outcomeTitle`, `outcomeId`
- `imageUrl`
- `shares`, `value`: numbers
- `timestamp`: unix seconds
- `blockNumber`: number
- `token`: ERC20 token address used for this market

Example:

```
GET /markets/164/events?network_id=2741&since=1755600000&until=1755800000&page=1&limit=50

```

---

### GET /markets/:id/holders

Market holders grouped by outcome. Aggregates buy/sell actions to compute net shares per user for each outcome, filters holders with at least 1 share, orders by shares, and applies the `limit` per outcome.

Lookup:

- By slug: `GET /markets/{slug}/holders`
- By id + network: `GET /markets/{marketId}/holders?network_id=2741`

Query params:

- `page`, `limit` (pagination; limit applies per outcome)
- `network_id` (required when using marketId)

Response data (per outcome):

- `outcomeId`: number
- `outcomeTitle`: string | null
- `totalHolders`: total addresses with ≥ 1 share in this outcome
- `holders`: array limited per outcome with:
    - `user`: address
    - `shares`: number

Pagination notes:

- `total` equals the maximum `total_holders` across outcomes for this market.
- `totalPages = ceil(max(total_holders) / limit)`; `limit` is applied per outcome.

Example:

```
GET /markets/164/holders?network_id=2741&page=1&limit=50
```

---

### POST /markets/quote

Get a trade quote and transaction calldata for a specific market outcome.

- Method: POST
- Path: `/markets/quote`
- Body: JSON

Request body:

- Exactly one of the following is required (send only one):
    - `market_id` (number): on-chain market id + `network_id` (number): network id
    - `market_slug` (string)
- `outcome_id` (number, required): on-chain outcome id
- `action` (string, required): `buy` | `sell`
- Exactly one of the following is required (send only one):
    - `value` (number): amount of tokens to spend (buy) or receive (sell)
    - `shares` (number): number of shares to buy or sell
- `shares` (number, optional): number of shares to buy/sell
- `slippage` (number, optional, default 0.005): between 0 (0%) and 1 (100%)

Validation rules:

- For **buy**: provide only `value`; `shares` must be omitted.
- For **sell**: provide exactly one of `value` or `shares`.
- Market must exist and be `open`.
- Market must have at least 2 outcomes and sufficient shares/liquidity.

Response body:

- `value` (number): input value used for the calculation
- `shares` (number): expected shares bought/sold
- `shares_threshold` (number): min acceptable based on `slippage` (for buy, min shares; for sell, max shares)
- `price_average` (number): average execution price
- `price_before` (number): price before the trade
- `price_after` (number): price after the trade
- `calldata` (string): hex-encoded calldata for the contract
- `net_amount` (number): value after protocol/treasury/distributor fees
- `fees`:
    - `treasury` (number)
    - `distributor` (number)
    - `fee` (number)

Example request (buy by value):

```json
{
  "market_id": 164,
  "outcome_id": 0,
  "network_id": 2741,
  "action": "buy",
  "value": 100,
  "slippage": 0.01
}
```

Example success response:

```json
{
  "value": 100,
  "shares": 312.3456,
  "shares_threshold": 309.2221,
  "price_average": 0.3201,
  "price_before": 0.315,
  "price_after": 0.3252,
  "calldata": "0x...",
  "net_amount": 99.3,
  "fees": {
    "treasury": 0.2,
    "distributor": 0.1,
    "fee": 0.4
  }
}
```

Possible errors:

- `400` Invalid request parameters, unsupported network, market not open, insufficient liquidity, or invalid slippage/value/shares combination
- `404` Market or outcome not found
- `500` Unable to resolve token decimals or unexpected server error

---

## Users

### GET /users/:address/events

Paginated actions for a user across markets, ordered by `timestamp desc`.

Query params:

- `page`, `limit`
- `marketId`: chain market id (optional)
- `networkId`: number (optional)
- `since`: unix seconds (inclusive)
- `until`: unix seconds (inclusive)

Response items:

- `user`: wallet address
- `action`: action type
- `marketTitle`, `marketSlug`, `marketId`, `networkId`
- `outcomeTitle`, `outcomeId`
- `imageUrl`
- `shares`, `value`: numbers
- `timestamp`: unix seconds
- `blockNumber`: number
- `token`: ERC20 token address

Example:

```
GET /users/0x1234.../events?network_id=2741&market_id=144&page=1&limit=50

```

---

### GET /users/:address/portfolio

Aggregated user positions per market/outcome/network, ordered by latest activity.

Query params:

- `page`, `limit`
- `market_slug`: market unique slug (optional)
- `market_id`: chain market id (optional)
- `network_id`: number (optional)
- `token_address`: ERC20 token address (optional)

Notes:

- Positions with `shares < 1` are excluded.
- Pagination and totals are computed after filtering.
- `price` is the current outcome price; `shares` is net buys minus sells; average buy price follows proportional cost-basis when selling.

Response items:

- `marketId`, `outcomeId`, `networkId`, `imageUrl`
- `shares`: net shares held (number)
- `price`: average buy price (number)
- `value`: `shares * currentPrice`
- `profit`: `shares * (currentPrice - price)`
- `roi`: `(profit - totalAmount) / totalAmount` (null if not computable)
- `winningsToClaim`: true if resolved, holding winning outcome, and no `claim_winnings`
- `winningsClaimed`: true if resolved, holding winning outcome, and `claim_winnings` exists
- `status`: `ongoing` | `lost` | `won` | `claimed` | `sold`

Example:

```
GET /users/0x1234.../portfolio?network_id=2741&token_address=0x84A71ccD554Cc1b02749b35d22F684CC8ec987e1&page=1&limit=20
```

---

## Price Data

- Historical price data is built from on-chain events (`MarketOutcomeShares`) and stored in `prices`.
- Outcome prices are derived from outcome shares.
- Liquidity price computation follows the contract logic; resolved markets use final shares/liquidity, otherwise `#outcomes / (liquidity * Σ(1/shares))`.

---

## Errors

Common errors:

- `401 Unauthorized` – missing/invalid API key
- `429 Too Many Requests` – rate limit exceeded
- `400 Bad Request` – invalid query parameters
- `404 Not Found` – resource not found
- `500 Internal Server Error`

---

## Networks

Myriad Protocol is currently live on [Abstract](https://www.abs.xyz/), [Linea](https://linea.build/), and [BNB Chain](https://www.bnbchain.org/en), with [Celo](https://celo.org/) coming soon. Here are the deployment details for each of them.

### Abstract

**Deployed Contracts**

|  | Mainnet | Testnet |
| --- | --- | --- |
| PredictionMarket | [`0x3e0F5F8F5Fb043aBFA475C0308417Bf72c463289`](https://abscan.org/address/0x3e0F5F8F5Fb043aBFA475C0308417Bf72c463289) | [`0x6c44Abf72085E5e71EeB7C951E3079073B1E7312`](https://sepolia.abscan.org/address/0x6c44Abf72085E5e71EeB7C951E3079073B1E7312) |
| PredictionMarketQuerier | [`0x1d5773Cd0dC74744C1F7a19afEeECfFE64f233Ff`](https://abscan.org/address/0x1d5773Cd0dC74744C1F7a19afEeECfFE64f233Ff) | [`0xa30c60107f9011dd49fc9e04ebe15963064eecc1`](https://sepolia.abscan.org/address/0xa30c60107f9011dd49fc9e04ebe15963064eecc1) |

**Tokens**

| Token | Mainnet | Testnet |
| --- | --- | --- |
| USDC.e | [`0x84A71ccD554Cc1b02749b35d22F684CC8ec987e1`](https://abscan.org/address/0x84A71ccD554Cc1b02749b35d22F684CC8ec987e1) | [`0x8820c84FD53663C2e2EA26e7a4c2b79dCc479765`](https://sepolia.abscan.org/address/0x8820c84FD53663C2e2EA26e7a4c2b79dCc479765) |
| PENGU | [`0x9eBe3A824Ca958e4b3Da772D2065518F009CBa62`](https://abscan.org/address/0x9eBe3A824Ca958e4b3Da772D2065518F009CBa62) | [`0x6ccDDCf494182a3A237ac3f33A303a57961FaF55`](https://sepolia.abscan.org/address/0x6ccddcf494182a3a237ac3f33a303a57961faf55) |
| PTS | [`0x0b07cf011b6e2b7e0803b892d97f751659940f23`](https://abscan.org/address/0x0b07cf011b6e2b7e0803b892d97f751659940f23) | [`0x6cC39C1149aed1fdbf6b11Fd60C18b96446cBc96`](https://sepolia.abscan.org/address/0x6cC39C1149aed1fdbf6b11Fd60C18b96446cBc96) |

### Linea

**Deployed Contracts**

|  | Mainnet | Testnet |
| --- | --- | --- |
| PredictionMarket | [`0x39e66ee6b2ddaf4defded3038e0162180dbef340`](https://lineascan.build/address/0x39e66ee6b2ddaf4defded3038e0162180dbef340) | [`0xED5CCb260f80A7EB1E5779B02115b4dc25aA3cDE`](https://sepolia.lineascan.build/address/0xED5CCb260f80A7EB1E5779B02115b4dc25aA3cDE) |
| PredictionMarketQuerier | [`0x503c9f98398dc3433ABa819BF3eC0b97e02B8D04`](https://lineascan.build/address/0x503c9f98398dc3433ABa819BF3eC0b97e02B8D04) | [`0x90916C3C1a070ED31f6CdFCD42807a38B563392F`](https://sepolia.lineascan.build/address/0x90916C3C1a070ED31f6CdFCD42807a38B563392F) |

**Tokens**

| Token | Mainnet | Testnet |
| --- | --- | --- |
| USDC | [`0x176211869cA2b568f2A7D4EE941E073a821EE1ff`](https://lineascan.build/address/0x176211869cA2b568f2A7D4EE941E073a821EE1ff) | [`0xFEce4462D57bD51A6A552365A011b95f0E16d9B7`](https://sepolia.lineascan.build/address/0xFEce4462D57bD51A6A552365A011b95f0E16d9B7) |

### BNB Chain

**Deployed Contracts**

|  | Mainnet | Testnet |
| --- | --- | --- |
| PredictionMarket | [`0x39E66eE6b2ddaf4DEfDEd3038E0162180dbeF340`](https://bscscan.com/address/0x39E66eE6b2ddaf4DEfDEd3038E0162180dbeF340) | [`0xb5625db4777262460589724693e6E032999FCCd5`](https://testnet.bscscan.com/address/0xb5625db4777262460589724693e6E032999FCCd5) |
| PredictionMarketQuerier | [`0xDeFb36c47754D2e37d44b8b8C647D4D643e03bAd`](https://bscscan.com/address/0xDeFb36c47754D2e37d44b8b8C647D4D643e03bAd) | [`0x289E3908ECDc3c8CcceC5b6801E758549846Ab19`](https://testnet.bscscan.com/address/0x289E3908ECDc3c8CcceC5b6801E758549846Ab19) |

**Tokens**

| Token | Mainnet | Testnet |
| --- | --- | --- |
| USDT | [`0x55d398326f99059fF775485246999027B3197955`](https://bscscan.com/address/0x55d398326f99059fF775485246999027B3197955) | [`0x49Ff827F0C8835ebd8109Cc3b51b80435ce44F09`](https://testnet.bscscan.com/address/0x49Ff827F0C8835ebd8109Cc3b51b80435ce44F09) |

### Celo

**Deployed Contracts**

|  | Mainnet | Testnet |
| --- | --- | --- |
| PredictionMarket | Coming soon | [`0x289E3908ECDc3c8CcceC5b6801E758549846Ab19`](https://celo-sepolia.blockscout.com/address/0x289E3908ECDc3c8CcceC5b6801E758549846Ab19) |
| PredictionMarketQuerier | Coming soon | [`0x49c86faa48facCBaC75920Bb0d5Dd955F8678e15`](https://celo-sepolia.blockscout.com/address/0x49c86faa48facCBaC75920Bb0d5Dd955F8678e15) |

**Tokens**

| Token | Mainnet | Testnet |
| --- | --- | --- |
| USDT | Coming soon | [`0xf74B14ecbAdC9fBb283Fb3c8ae11E186856eae6f`](https://celo-sepolia.blockscout.com/address/0xf74B14ecbAdC9fBb283Fb3c8ae11E186856eae6f) |

---

## Changelog

### **V2.0.0**

- Added API key authentication and request logging
- Added rate limiting
- Markets endpoints with keyword search and charts
- Market events and user events endpoints with timestamp filtering
- Historical prices ingestion + charting

### **V2.0.1**

- Added portfolio endpoint
- Added market holders endpoint

### **V2.0.2**

- Added market quote endpoint
