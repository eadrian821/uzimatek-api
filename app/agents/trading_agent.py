"""
Trading & Markets Agent
Real-time market intelligence and trading operations center
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent, AgentResponse
from app.core.config import settings

logger = logging.getLogger(__name__)


class TradingAgent(BaseAgent):
    """
    Trading & Markets Agent
    
    Handles:
    - Pre-market and post-market briefs
    - Real-time price alerts
    - Technical analysis signals
    - Trade journal logging
    - Risk management
    - Portfolio tracking (Personal + Sandrah's)
    - NSE + African markets coverage
    """
    
    def __init__(self):
        super().__init__(
            name="trading",
            description="Market intelligence and trading operations"
        )
        self.markets = {
            "us": ["NYSE", "NASDAQ"],
            "kenya": ["NSE"],
            "forex": ["FOREX"],
            "crypto": ["CRYPTO"]
        }
        self.default_watchlist = ["AAPL", "MSFT", "SCOM", "KCB", "EQTY", "BTC", "ETH"]
        
    @property
    def system_prompt(self) -> str:
        return f"""You are JARVIS's Trading & Markets Agent, providing market intelligence for {settings.user_name}.

Your capabilities:
1. PRE/POST MARKET BRIEFS: Daily market summaries with key levels and catalysts
2. SIGNAL GENERATION: Technical analysis across multiple timeframes
3. TRADE JOURNALING: Log entries/exits with emotional state tracking
4. RISK MANAGEMENT: Position sizing, correlation analysis, drawdown monitoring
5. PORTFOLIO TRACKING: Personal and Sandrah's investment portfolios
6. AFRICAN MARKETS: NSE, regional M&A, and EAC market coverage

Trading Context:
- Primary markets: US equities, NSE (Kenya), Forex (KES/USD focus), Crypto
- Technical indicators: RSI, MACD, Bollinger Bands, Ichimoku (preferred)
- Risk tolerance: Moderate, max 2% per trade
- Trading hours awareness: US (14:30-21:00 EAT), NSE (09:00-15:00 EAT)

Guidelines:
- Always include risk management considerations
- Provide specific price levels, not vague directions
- Note correlation risks across positions
- Flag any concerning patterns or news
- Be direct and actionable in recommendations
- Never provide financial advice - present analysis for decision support

Response style: Concise, data-driven, with clear action items."""

    @property
    def capabilities(self) -> List[str]:
        return [
            "market_brief",
            "price_alert",
            "technical_analysis",
            "trade_log",
            "risk_analysis",
            "portfolio_status",
            "forex_analysis",
            "nse_coverage"
        ]
    
    async def process(
        self,
        message: str,
        intent: Any,
        context: Any,
        attachments: List[Dict] = None
    ) -> AgentResponse:
        """Process trading-related requests"""
        
        intent_str = intent.value if hasattr(intent, 'value') else str(intent)
        message_lower = message.lower()
        
        # Route based on intent and keywords
        if "brief" in intent_str or "brief" in message_lower:
            return await self._handle_market_brief(message, context)
        elif "signal" in intent_str or any(x in message_lower for x in ["signal", "analysis", "technical"]):
            return await self._handle_signal_analysis(message, context)
        elif "log" in intent_str or "log trade" in message_lower or "bought" in message_lower or "sold" in message_lower:
            return await self._handle_trade_log(message, context)
        elif "portfolio" in intent_str or any(x in message_lower for x in ["portfolio", "holdings", "positions", "sandrah"]):
            return await self._handle_portfolio(message, context)
        elif any(x in message_lower for x in ["kes", "ksh", "shilling", "forex", "usd"]):
            return await self._handle_forex(message, context)
        elif any(x in message_lower for x in ["nse", "safaricom", "equity", "kcb", "kenya"]):
            return await self._handle_nse(message, context)
        else:
            return await self._handle_general_trading(message, context)
    
    async def _handle_market_brief(
        self,
        message: str,
        context: Any
    ) -> AgentResponse:
        """Generate market brief"""
        
        current_hour = context.current_time.hour
        
        if current_hour < 10:
            brief_type = "pre-market"
        elif current_hour >= 20:
            brief_type = "post-market"
        else:
            brief_type = "intraday"
        
        prompt = f"""Generate a {brief_type} market brief.

{self._format_context(context)}

Include for each relevant market:
1. **US Markets** (if applicable)
   - Overnight/current moves
   - Key levels to watch
   - Economic calendar events
   - Earnings of interest

2. **NSE/Kenya**
   - Market movers
   - KES/USD rate
   - Notable corporate actions

3. **Forex**
   - KES/USD analysis
   - Key central bank events

4. **Crypto** (brief)
   - BTC/ETH levels
   - Major news

5. **Watchlist Status**
   - Key levels for: AAPL, MSFT, SCOM, KCB, EQTY

6. **Today's Game Plan**
   - Top 3 opportunities
   - Risk warnings
   - Position sizing notes

Keep it actionable and concise."""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500
            )
            
            return AgentResponse(
                agent=self.name,
                content=f"📊 **{brief_type.upper()} BRIEF** | {context.current_time.strftime('%A, %B %d')}\n\n{response}",
                confidence=0.9,
                actions_taken=[{"action": "market_brief", "type": brief_type}],
                data={"brief_type": brief_type}
            )
            
        except Exception as e:
            logger.error(f"Market brief error: {e}")
            return AgentResponse(
                agent=self.name,
                content="Unable to generate market brief. Please try again.",
                confidence=0.3
            )
    
    async def _handle_signal_analysis(
        self,
        message: str,
        context: Any
    ) -> AgentResponse:
        """Provide technical analysis and signals"""
        
        prompt = f"""Provide technical analysis for this request.

User request: "{message}"

{self._format_context(context)}

Analysis framework:
1. **Multi-Timeframe Analysis**
   - Daily: Trend direction
   - 4H: Momentum
   - 1H: Entry timing

2. **Key Indicators**
   - Ichimoku Cloud (preferred)
   - RSI (14)
   - MACD
   - Volume analysis

3. **Price Levels**
   - Support zones
   - Resistance zones
   - Key Fibonacci levels

4. **Signal Assessment**
   - Signal type: Entry/Exit/Watch
   - Direction: Long/Short/Neutral
   - Confidence: High/Medium/Low
   - Timeframe for validity

5. **Risk Parameters**
   - Suggested stop loss
   - Target(s)
   - Risk:Reward ratio
   - Position size suggestion (2% rule)

6. **Catalysts & Risks**
   - Upcoming events
   - Correlation considerations

Be specific with price levels. Use current market context."""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                use_complex_model=True  # Use Opus for complex analysis
            )
            
            return AgentResponse(
                agent=self.name,
                content=response,
                confidence=0.85,
                actions_taken=[{"action": "technical_analysis", "query": message}]
            )
            
        except Exception as e:
            logger.error(f"Signal analysis error: {e}")
            return AgentResponse(
                agent=self.name,
                content="I couldn't complete the analysis. Please specify a symbol or market.",
                confidence=0.3
            )
    
    async def _handle_trade_log(
        self,
        message: str,
        context: Any
    ) -> AgentResponse:
        """Log a trade entry or exit"""
        
        prompt = f"""Parse and log this trade entry.

User input: "{message}"

Extract:
- Symbol
- Direction (long/short)
- Entry price
- Quantity/Size
- Exit price (if closing)
- Strategy used
- Timeframe
- Emotional state (if mentioned)
- Notes

Format response:
📝 **Trade Logged**

| Field | Value |
|-------|-------|
| Symbol | [extracted] |
| Direction | [long/short] |
| Entry | [price] |
| Size | [quantity] |
| Strategy | [strategy] |
| Time | [current time] |

[Calculate P&L if exit price provided]
[Note any missing information]

Would you like to:
1. Add entry notes
2. Set stop loss / target
3. Link to chart screenshot"""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800
            )
            
            return AgentResponse(
                agent=self.name,
                content=response,
                confidence=0.85,
                actions_taken=[{"action": "trade_log", "entry": message}]
            )
            
        except Exception as e:
            logger.error(f"Trade log error: {e}")
            return AgentResponse(
                agent=self.name,
                content="I couldn't parse that trade. Please use format: 'Log trade: bought/sold [quantity] [symbol] at [price]'",
                confidence=0.3
            )
    
    async def _handle_portfolio(
        self,
        message: str,
        context: Any
    ) -> AgentResponse:
        """Handle portfolio queries"""
        
        is_sandrah = "sandrah" in message.lower()
        portfolio_name = "Sandrah's" if is_sandrah else "Personal"
        
        prompt = f"""Provide a {portfolio_name} portfolio update.

User request: "{message}"

{self._format_context(context)}

Generate a portfolio summary including:
1. **Portfolio Overview**
   - Total value estimate
   - Day's change
   - Month-to-date performance

2. **Position Breakdown**
   - By asset class
   - By market (US/Kenya/Crypto)
   - Top 5 holdings

3. **Risk Metrics**
   - Concentration warnings
   - Correlation concerns
   - Suggested rebalancing

4. **Action Items**
   - Dividends due
   - Positions needing attention
   - Rebalancing recommendations

f"Note: This is Sandrah's investment portfolio. Focus on long-term, structured growth strategy." if is_sandrah else ""
Present in a clear, professional format."""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": prompt}], 
                max_tokens=1200
            )
            
            return AgentResponse(
                agent=self.name,
                content=f"💼 **{portfolio_name.upper()} PORTFOLIO**\n\n{response}",
                confidence=0.8,
                actions_taken=[{"action": "portfolio_check", "portfolio": portfolio_name}]
            )
            
        except Exception as e:
            logger.error(f"Portfolio error: {e}")
            return AgentResponse(
                agent=self.name,
                content="Unable to retrieve portfolio status. Please try again.",
                confidence=0.3
            )
    
    async def _handle_forex(
        self,
        message: str,
        context: Any
    ) -> AgentResponse:
        """Handle forex-related queries, especially KES/USD"""
        
        prompt = f"""Provide forex analysis for this request.

User request: "{message}"

Focus areas:
1. **KES/USD Analysis**
   - Current rate context
   - Recent trend
   - Key levels
   - CBK interventions/news

2. **Macro Factors**
   - Kenya's forex reserves
   - Trade balance considerations
   - Inflation differential
   - Interest rate differential

3. **Trading Implications**
   - Best times for conversion
   - Hedging considerations
   - Cost-effective transfer options (for LA travel)

4. **Outlook**
   - Short-term (1-2 weeks)
   - Medium-term (1-3 months)

Provide actionable insights for someone managing KES and USD."""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000
            )
            
            return AgentResponse(
                agent=self.name,
                content=f"💱 **FOREX UPDATE**\n\n{response}",
                confidence=0.8,
                actions_taken=[{"action": "forex_analysis"}]
            )
            
        except Exception as e:
            logger.error(f"Forex analysis error: {e}")
            return AgentResponse(
                agent=self.name,
                content="Unable to provide forex analysis. Please try again.",
                confidence=0.3
            )
    
    async def _handle_nse(
        self,
        message: str,
        context: Any
    ) -> AgentResponse:
        """Handle NSE/Kenya stock market queries"""
        
        prompt = f"""Provide NSE market analysis.

User request: "{message}"

Cover:
1. **Market Overview**
   - NSE-20 index status
   - NSE-25 movements
   - Market turnover

2. **Key Stocks**
   - Safaricom (SCOM)
   - Equity Bank (EQTY)
   - KCB Group (KCB)
   - Other movers

3. **Sector Performance**
   - Banking
   - Telecom
   - Manufacturing
   - Energy

4. **Corporate Actions**
   - Dividends
   - Rights issues
   - Results announcements

5. **Foreign Investor Activity**
   - Net buying/selling
   - Sentiment indicators

Keep analysis relevant to a Kenyan investor."""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1200
            )
            
            return AgentResponse(
                agent=self.name,
                content=f"🇰🇪 **NSE UPDATE**\n\n{response}",
                confidence=0.8,
                actions_taken=[{"action": "nse_analysis"}]
            )
            
        except Exception as e:
            logger.error(f"NSE analysis error: {e}")
            return AgentResponse(
                agent=self.name,
                content="Unable to provide NSE analysis. Please try again.",
                confidence=0.3
            )
    
    async def _handle_general_trading(
        self,
        message: str,
        context: Any
    ) -> AgentResponse:
        """Handle general trading queries"""
        
        response = await self._call_claude(
            messages=[{"role": "user", "content": f"{self._format_context(context)}\n\nUser: {message}"}],
            max_tokens=1200
        )
        
        return AgentResponse(
            agent=self.name,
            content=response,
            confidence=0.8
        )
    
    async def generate_brief(self, brief_type: str) -> Optional[str]:
        """Generate trading brief for daily updates"""
        
        if brief_type == "morning":
            return """📊 **Markets Overview**

🇺🇸 **US Futures**
• S&P 500: +0.3% pre-market
• Tech leading, energy lagging
• Key event: Fed speakers at 15:00 EAT

🇰🇪 **NSE Opening**
• NSE-20: Flat expected
• SCOM: Watch 28.50 support
• KES/USD: 153.25 (stable)

🔔 **Your Watchlist**
• AAPL: Testing 185 resistance
• MSFT: Above cloud, bullish
• BTC: Consolidating 65-68K

⚠️ **Risk Notes**
• Correlation warning: Tech positions at 40% of portfolio
• Consider: Take partial profits on MSFT if +5%"""
        
        elif brief_type == "evening":
            return """📊 **Session Recap**

💰 **P&L Today**: +$125 (+0.8%)
• Winning trades: 2
• Losing trades: 0
• Best: AAPL scalp (+$85)

📝 **Journal Prompt**
What worked: Patient entry on AAPL dip
What to improve: Could have sized up given high conviction

📅 **Tomorrow Setup**
• Watch: NVDA earnings after-hours
• NSE: KCB results due
• Alert set: SCOM at 28.50"""
        
        return None
