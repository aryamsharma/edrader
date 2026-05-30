# Strategy Catalog

Strategies that can be built on the existing event-driven architecture.
Each follows the same pattern: override `event_types()` and `on_event()`, call `emit_signal()` — no orders, no positions, no IBKR calls.

---

## BarCloseEvent Strategies

All use `symbol, open, high, low, close, volume` per bar.

| Strategy | Signal Logic | Existing Example |
|---|---|---|
| **SMA Crossover** | BUY when fast SMA > slow SMA, SELL when reverse | `sma_crossover.py` |
| **Mean Reversion (Z-score)** | BUY when z-score ≤ -entry_z, SELL when z-score ≥ +entry_z; exit at exit_z | `mean_reversion.py` |
| **RSI / Momentum** | BUY when RSI < 30 (oversold), SELL when RSI > 70 (overbought). Rolling-window pattern. Lookback ~14 bars. | — |
| **Bollinger Bands** | BUY when price touches lower band (SMA - k*std), SELL at upper band (SMA + k*std). Entry/exit zones. | — |
| **Breakout (Donchian Channel)** | BUY when close > N-bar high, SELL when close < N-bar low. Rolling max/min over window. | — |
| **MACD** | EMA crossover (12, 26) with signal line (9). BUY when MACD crosses above signal, SELL below. Needs EMA. | — |
| **Pullback to MA** | BUY when price pulls back to touch a rising SMA (trend-following), SELL at a falling SMA. | — |
| **High-Low Range Breakout** | BUY when close > open + k * (high - low) — momentum expansion. | — |
| **Keltner Channels** | BUY when close above upper ATR-based channel, SELL below lower channel. | — |
| **Ichimoku Cloud** | Tenkan-sen/Kijun-sen crossover, cloud twist, lagging span confirmation. Multi-component. | — |
| **Parabolic SAR** | BUY when SAR flips below price (trend up), SELL when SAR flips above (trend down). | — |

---

## MarketTickEvent Strategies

Use `symbol, price, volume, bid, ask` — tick-level data, no bar aggregation.

| Strategy | Signal Logic |
|---|---|
| **VWAP (Running)** | Cumulative (price * volume) / cumulative volume. BUY when price < VWAP by N std, SELL when > VWAP by N std. |
| **Bid/Ask Imbalance** | (bid_size - ask_size) / (bid_size + ask_size). BUY when imbalance > threshold, SELL when < -threshold. |
| **Tick Direction Momentum** | Uptick/downtick ratio in rolling window. BUY when > 0.7, SELL when < 0.3. |
| **Microstructure Spread** | BUY at bid, SELL at ask. Short-duration, high-frequency. Needs spread check. |
| **Volume Surge** | Tick volume spikes above rolling average * multiplier. Momentum signal on expansion. |
| **Accumulation/Distribution** | Classify ticks as buy/sell via bid/ask comparison. Cumulative pressure direction. |

---

## Combined Tick + Bar Strategies

Use `MarketTickEvent` for intra-bar state, act on `BarCloseEvent`.

| Strategy | Signal Logic |
|---|---|
| **VWAP + Bar Confirm** | Build VWAP from ticks. Only emit BUY/SELL when bar close confirms the deviation. |
| **Tick Pressure + Breakout** | Compute buying pressure during bar. Only emit breakout if pressure supports direction. |
| **Opening Range Breakout** | Track first N minutes of ticks after `MarketOpenEvent`. BUY/SELL when price breaks that range. |
| **Trailing Stop Builder** | Track tick-level peak price. Emit SELL if price drops N% from peak. Risk-managed position builder. |

---

## Event-Driven Strategies (non-OHLCV)

Use lifecycle and broker events.

| Strategy | Events Used | Logic |
|---|---|---|
| **Kill Switch Avoider** | `BrokerDisconnectedEvent`, `BrokerReconnectedEvent` | Pause signals on disconnect, resume on reconnect. Protective. |
| **Market Session** | `MarketOpenEvent`, `MarketCloseEvent` | Only trade during specific sessions. Flatten at close. |
| **Volatility Regime** | `ExposureUpdatedEvent` or tick data | Scale position sizes based on current volatility (VIX-like proxy or ATR). Reduce in high vol. |

---

## External Data Strategies (need new event types)

These require a new data source component + new event type.

| Strategy | Data Source | Proposed Event | Logic |
|---|---|---|---|
| **Sentiment** | News API (Polygon, FinnHub, Alpha Vantage) | `NewsEvent(symbol, headline, sentiment, source)` | BUY on positive sentiment spike with price confirmation. |
| **Corporate Events** | SEC filings, earnings calendar API | `EarningsEvent(symbol, surprise_pct)` | Pre-earnings drift, post-earnings gap fade. |
| **Macro / Economic** | FRED, BLS, macroeconomic API | `MacroEvent(indicator, value, forecast)` | Rate decisions, CPI, NFP — position ahead of releases. |
| **Options Flow** | Options data feed (Polygon, TOS) | `OptionTradeEvent(symbol, strike, call/put, premium)` | Follow large block options trades as directional signals. |
| **Social Sentiment** | StockTwits, Twitter API | `SocialSentimentEvent(symbol, bull_bear_ratio, volume)` | Early retail sentiment detection. |
| **Insider Trading** | SEC Form 4 filings API | `InsiderTradeEvent(symbol, insider, side, size)` | Follow insider buying signals. |
| **Alternative Data** | Satellite, web scraping, credit card | Custom per source | Web traffic → revenue prediction, foot traffic → retail. |

---

## References & Research

### Foundational Books
- *Evidence-Based Technical Analysis* — David Aronson (rigor, hypothesis testing)
- *Algorithmic Trading: Winning Strategies and Their Rationale* — Ernie Chan (systematic, practical)
- *Quantitative Trading* — Ernie Chan (startup quant mindset, infrastructure)
- *Trading and Exchanges* — Larry Harris (market microstructure, order types, mechanics)
- *Market Microstructure Theory* — Maureen O'Hara (academic, depth)
- *Advances in Financial Machine Learning* — Marcos López de Prado (features, backtest overfitting, deflated Sharpe)
- *The Evaluation and Optimization of Trading Strategies* — Robert Pardo (walk-forward, robustness)

### Specific Strategy References
- **MACD**: Appel, Gerald. *Technical Analysis: Power Tools for Active Investors*
- **Bollinger Bands**: Bollinger, John. *Bollinger on Bollinger Bands*
- **Ichimoku**: Linton, David. *Cloud Charts: Trading with the Ichimoku Technique*
- **VWAP**: Berkowitz, Dennis. *A VWAP Trading Strategy* (Journal of Trading)
- **Order Flow / Tick**: Easley, D., López de Prado, M., O'Hara, M. — *Flow Toxicity and Volatility* (VPIN concept)

### Research Papers (key ones)
- *Does Algorithmic Trading Improve Liquidity?* — Hendershott, Jones, Menkveld (2008)
- *An Ordered Probit Analysis of Transaction Stock Prices* — Hausman, Lo, MacKinlay (1992)
- *Trading Frequency and Asset Values* — Chordia, Roll, Subrahmanyam (various)
- *Mean Reversion of Stock Prices* — Poterba, Summers (1988) — foundation for mean reversion
- *The Profitability of Technical Analysis* — Brock, Lakonishok, LeBaron (1992) — early evidence
- *Carrion (2014) — Very fast money: High-frequency trading on NASDAQ

### Strategy Research Sites
- [QuantConnect Research](https://www.quantconnect.com/research/) — open-source algorithm library with backtests
- [Quantpedia](https://quantpedia.com/) — encyclopedia of quantitative strategies with paper references
- [SSRN](https://www.ssrn.com/) — search "trading strategy" or "algorithmic trading" for current papers
- [Journal of Financial Economics](https://www.jfe.rochester.edu/) / [Journal of Finance](https://afajof.org/)
- [AQR Clarity](https://www.aqr.com/Insights) — systematic factor research, practical
- [Quantitative Finance Stack Exchange](https://quant.stackexchange.com/) — discussion, code, references

### Risk & Practical Implementation
- *López de Prado (2018) — Deflated Sharpe Ratio* — corrects for multiple testing in strategy search
- *Bailey et al. (2014) — The Probability of Backtest Overfitting*
- *Zakamulin (2015) — A Comprehensive Look at the Performance of Moving Average Strategies*
- *Kritzman, Page, Turkington (2012) — Regime Shifts: Implications for Dynamic Strategies*

### Libraries & Tools
- [TA-Lib](https://ta-lib.org/) — 150+ technical indicators (RSI, MACD, Bollinger, etc.)
- [QuantLib](https://www.quantlib.org/) — derivatives pricing, risk analytics
- [bt (Python)](https://github.com/pmorissette/bt) — flexible backtesting framework
- [zipline](https://github.com/quantopian/zipline) — historical backtester (Quantopian)
- [pandas-ta](https://github.com/twopirllc/pandas-ta) — Technical Analysis indicators in pandas
- [ta](https://github.com/bukosabino/ta) — lightweight technical analysis library
