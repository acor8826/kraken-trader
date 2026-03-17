/**
 * Charts Page - Real-time candlestick charts with trade markers
 * TradingView Lightweight Charts, WebSocket live updates, pattern annotations
 *
 * Features:
 *  - Client-side candlestick pattern detection (20+ patterns)
 *  - Multi-timeframe pattern scanning (1m, 5m, 15m, 1h)
 *  - Expandable pattern education (entry/exit points)
 *  - Trade status per pattern (traded / skipped + reason)
 *  - Rate-limited API calls with adaptive refresh intervals
 *  - In-place chart updates (no flicker)
 */

import store from '../store.js';
import api from '../api.js';
import wsManager from '../websocket.js';
import { formatCurrency, formatPercent, formatTimeAgo, setHTML, escapeHTML, getPnLClass } from '../utils.js';

// ─── Intervals ───────────────────────────────────────────────────
const INTERVALS = [
    { label: '1m',  value: 1,  refreshSec: 15 },
    { label: '3m',  value: 3,  refreshSec: 30 },
    { label: '5m',  value: 5,  refreshSec: 45 },
    { label: '15m', value: 15, refreshSec: 60 },
    { label: '1h',  value: 60, refreshSec: 120 },
];

// Timeframes to scan for patterns (separate from chart interval)
const PATTERN_SCAN_TFS = [
    { label: '1m',  value: 1  },
    { label: '5m',  value: 5  },
    { label: '15m', value: 15 },
    { label: '1h',  value: 60 },
];

// ─── Rate Limiter ────────────────────────────────────────────────
class RateLimiter {
    constructor(maxCalls, windowMs) {
        this.maxCalls = maxCalls;
        this.windowMs = windowMs;
        this.calls = [];
    }
    async acquire() {
        const now = Date.now();
        this.calls = this.calls.filter(t => now - t < this.windowMs);
        if (this.calls.length >= this.maxCalls) {
            const wait = this.windowMs - (now - this.calls[0]);
            await new Promise(r => setTimeout(r, wait));
        }
        this.calls.push(Date.now());
    }
}

// Max 8 OHLCV calls per 10 seconds (conservative for Binance/exchange limits)
const ohlcvLimiter = new RateLimiter(8, 10000);

// ─── Pattern Education Database ──────────────────────────────────
const PATTERN_INFO = {
    'Doji': {
        type: 'Reversal / Indecision',
        desc: 'Open and close are nearly equal, forming a cross shape. Signals market indecision and potential reversal.',
        entry: 'Wait for confirmation candle in either direction. Enter on break above high (bullish) or below low (bearish) of the Doji.',
        exit: 'Stop loss at opposite end of Doji wick. Target 1:2 risk-reward ratio.',
        reliability: 'Low alone, moderate with confirmation',
    },
    'Hammer': {
        type: 'Bullish Reversal',
        desc: 'Small body at top with long lower wick (2x+ body). Appears after a downtrend. Buyers rejected lower prices.',
        entry: 'Enter long on the next candle opening above the Hammer close. Aggressive: enter at Hammer close.',
        exit: 'Stop loss below the Hammer low. Take profit at prior resistance or 1.5-2x risk.',
        reliability: 'Moderate-High after downtrend',
    },
    'Inverted Hammer': {
        type: 'Bullish Reversal',
        desc: 'Small body at bottom with long upper wick. Appears after a downtrend. Buyers attempted to push higher.',
        entry: 'Enter long only on confirmation (next candle closes above Inverted Hammer high).',
        exit: 'Stop loss below the low. Target prior resistance level.',
        reliability: 'Moderate, requires confirmation',
    },
    'Hanging Man': {
        type: 'Bearish Reversal',
        desc: 'Same shape as Hammer but appears after an uptrend. Sellers pushed price down during the session.',
        entry: 'Enter short on confirmation candle closing below Hanging Man low.',
        exit: 'Stop loss above Hanging Man high. Target prior support.',
        reliability: 'Moderate, stronger with volume increase',
    },
    'Shooting Star': {
        type: 'Bearish Reversal',
        desc: 'Small body at bottom with long upper wick (2x+ body). Appears after an uptrend. Buyers failed to hold highs.',
        entry: 'Enter short on the next candle opening below the Shooting Star close.',
        exit: 'Stop loss above the Shooting Star high. Target prior support or 1.5-2x risk.',
        reliability: 'Moderate-High after uptrend',
    },
    'Bullish Engulfing': {
        type: 'Bullish Reversal',
        desc: 'Large green candle completely engulfs prior red candle body. Strong shift from sellers to buyers.',
        entry: 'Enter long at close of engulfing candle or on next candle open. More aggressive: enter mid-candle.',
        exit: 'Stop loss below engulfing candle low. Target 1.5-2x risk or next resistance.',
        reliability: 'High, especially at support levels',
    },
    'Bearish Engulfing': {
        type: 'Bearish Reversal',
        desc: 'Large red candle completely engulfs prior green candle body. Strong shift from buyers to sellers.',
        entry: 'Enter short at close of engulfing candle or on next candle open.',
        exit: 'Stop loss above engulfing candle high. Target 1.5-2x risk or next support.',
        reliability: 'High, especially at resistance levels',
    },
    'Morning Star': {
        type: 'Bullish Reversal (3-candle)',
        desc: 'Red candle, small-body indecision candle, then strong green candle. Classic bottom reversal after downtrend.',
        entry: 'Enter long at close of the third candle. Conservative: wait for open above midpoint of first candle.',
        exit: 'Stop loss below the low of the middle candle. Target prior swing high.',
        reliability: 'High, one of the strongest reversal patterns',
    },
    'Evening Star': {
        type: 'Bearish Reversal (3-candle)',
        desc: 'Green candle, small-body indecision candle, then strong red candle. Classic top reversal after uptrend.',
        entry: 'Enter short at close of the third candle. Conservative: wait for open below midpoint of first candle.',
        exit: 'Stop loss above the high of the middle candle. Target prior swing low.',
        reliability: 'High, one of the strongest reversal patterns',
    },
    'Dragonfly Doji': {
        type: 'Bullish Reversal',
        desc: 'Open, close, and high are all near the same level with a long lower wick. Buyers dominated after initial sell-off.',
        entry: 'Enter long on next candle closing above the Dragonfly Doji high.',
        exit: 'Stop loss below the long lower wick. Target 1.5-2x risk.',
        reliability: 'Moderate-High at support levels',
    },
    'Gravestone Doji': {
        type: 'Bearish Reversal',
        desc: 'Open, close, and low are all near the same level with a long upper wick. Sellers dominated after initial rally.',
        entry: 'Enter short on next candle closing below the Gravestone Doji low.',
        exit: 'Stop loss above the long upper wick. Target 1.5-2x risk.',
        reliability: 'Moderate-High at resistance levels',
    },
    'Three White Soldiers': {
        type: 'Strong Bullish Continuation',
        desc: 'Three consecutive large green candles, each closing higher. Very strong buying pressure.',
        entry: 'Enter long at close of the third candle. Be cautious of overextension.',
        exit: 'Trailing stop below each new candle low. Initial stop below first soldier low.',
        reliability: 'Very High, but watch for exhaustion',
    },
    'Three Black Crows': {
        type: 'Strong Bearish Continuation',
        desc: 'Three consecutive large red candles, each closing lower. Very strong selling pressure.',
        entry: 'Enter short at close of the third candle. Be cautious of oversold bounce.',
        exit: 'Trailing stop above each new candle high. Initial stop above first crow high.',
        reliability: 'Very High, but watch for reversal bounce',
    },
    'Piercing Line': {
        type: 'Bullish Reversal (2-candle)',
        desc: 'Red candle followed by green candle that opens below the prior low but closes above the midpoint of the red candle.',
        entry: 'Enter long at close of the green candle or on next candle open above the close.',
        exit: 'Stop loss below the low of the pattern. Target prior resistance.',
        reliability: 'Moderate-High, stronger at key support',
    },
    'Dark Cloud Cover': {
        type: 'Bearish Reversal (2-candle)',
        desc: 'Green candle followed by red candle that opens above the prior high but closes below the midpoint of the green candle.',
        entry: 'Enter short at close of the red candle or on next candle open below the close.',
        exit: 'Stop loss above the high of the pattern. Target prior support.',
        reliability: 'Moderate-High, stronger at key resistance',
    },
    'Bullish Harami': {
        type: 'Bullish Reversal (2-candle)',
        desc: 'Large red candle followed by small green candle contained within the prior body. Selling pressure weakening.',
        entry: 'Enter long on confirmation: next candle closing above the harami high.',
        exit: 'Stop loss below the large red candle low. Target 1.5x risk.',
        reliability: 'Moderate, best with volume confirmation',
    },
    'Bearish Harami': {
        type: 'Bearish Reversal (2-candle)',
        desc: 'Large green candle followed by small red candle contained within the prior body. Buying pressure weakening.',
        entry: 'Enter short on confirmation: next candle closing below the harami low.',
        exit: 'Stop loss above the large green candle high. Target 1.5x risk.',
        reliability: 'Moderate, best with volume confirmation',
    },
    'Tweezer Top': {
        type: 'Bearish Reversal (2-candle)',
        desc: 'Two candles with matching highs. First is green (up), second is red (down). Resistance level confirmed twice.',
        entry: 'Enter short on next candle closing below the second candle low.',
        exit: 'Stop loss above the matched high. Target prior support.',
        reliability: 'Moderate, stronger at key resistance',
    },
    'Tweezer Bottom': {
        type: 'Bullish Reversal (2-candle)',
        desc: 'Two candles with matching lows. First is red (down), second is green (up). Support level confirmed twice.',
        entry: 'Enter long on next candle closing above the second candle high.',
        exit: 'Stop loss below the matched low. Target prior resistance.',
        reliability: 'Moderate, stronger at key support',
    },
    'Spinning Top': {
        type: 'Indecision',
        desc: 'Small body with upper and lower wicks of similar length. Neither buyers nor sellers have control.',
        entry: 'Do not trade alone. Wait for directional confirmation candle.',
        exit: 'N/A - used as context for other setups.',
        reliability: 'Low alone, contextual signal',
    },
    'Marubozu Bullish': {
        type: 'Strong Bullish Continuation',
        desc: 'Large green candle with no wicks (or very small). Buyers dominated the entire session with no pullback.',
        entry: 'Enter long at close or on a pullback to the candle midpoint.',
        exit: 'Stop loss below candle low. Use trailing stop for momentum.',
        reliability: 'High, very strong momentum signal',
    },
    'Marubozu Bearish': {
        type: 'Strong Bearish Continuation',
        desc: 'Large red candle with no wicks (or very small). Sellers dominated the entire session with no bounce.',
        entry: 'Enter short at close or on a bounce to the candle midpoint.',
        exit: 'Stop loss above candle high. Use trailing stop for momentum.',
        reliability: 'High, very strong momentum signal',
    },
    'Rising Three Methods': {
        type: 'Bullish Continuation (5-candle)',
        desc: 'Long green candle, 3 small declining red candles within its range, then another long green candle. Uptrend pause and resume.',
        entry: 'Enter long at close of the fifth candle (second large green).',
        exit: 'Stop loss below the low of the small red candles. Target next resistance.',
        reliability: 'High in established uptrends',
    },
    'Falling Three Methods': {
        type: 'Bearish Continuation (5-candle)',
        desc: 'Long red candle, 3 small rising green candles within its range, then another long red candle. Downtrend pause and resume.',
        entry: 'Enter short at close of the fifth candle (second large red).',
        exit: 'Stop loss above the high of the small green candles. Target next support.',
        reliability: 'High in established downtrends',
    },
};

// ─── Client-side Candlestick Pattern Detection ───────────────────
function detectPatterns(candles) {
    if (!candles || candles.length < 5) return [];
    const patterns = [];

    for (let i = 4; i < candles.length; i++) {
        const c0 = candles[i - 4];
        const c1 = candles[i - 3];
        const c2 = candles[i - 2];
        const c3 = candles[i - 1];
        const c4 = candles[i];
        const detected = detectAt5(c0, c1, c2, c3, c4);
        for (const p of detected) {
            patterns.push({ ...p, time: c4.time, index: i });
        }
    }
    return patterns;
}

function detectAt5(c0, c1, c2, c3, c4) {
    const results = [];
    const body4 = Math.abs(c4.close - c4.open);
    const range4 = c4.high - c4.low;
    const body3 = Math.abs(c3.close - c3.open);
    const range3 = c3.high - c3.low;
    const body2 = Math.abs(c2.close - c2.open);
    const range2 = c2.high - c2.low;
    const body1 = Math.abs(c1.close - c1.open);
    const body0 = Math.abs(c0.close - c0.open);

    if (range4 === 0) return results;

    const lowerWick4 = Math.min(c4.open, c4.close) - c4.low;
    const upperWick4 = c4.high - Math.max(c4.open, c4.close);
    const lowerWick3 = Math.min(c3.open, c3.close) - c3.low;
    const upperWick3 = c3.high - Math.max(c3.open, c3.close);

    // Price tolerance for tweezer matching (0.1% of price)
    const priceTol = c4.close * 0.001;

    // ── Doji ──
    if (body4 / range4 < 0.1) {
        results.push({ name: 'Doji', signal: 0, strength: 0.3, direction: 'neutral' });
    }

    // ── Spinning Top ──
    if (body4 / range4 > 0.1 && body4 / range4 < 0.35 &&
        upperWick4 > body4 * 0.8 && lowerWick4 > body4 * 0.8) {
        results.push({ name: 'Spinning Top', signal: 0, strength: 0.2, direction: 'neutral' });
    }

    // ── Hammer (bullish) ──
    if (lowerWick4 > body4 * 2 && upperWick4 < body4 * 0.5 && c3.close < c3.open) {
        results.push({ name: 'Hammer', signal: 0.6, strength: 0.6, direction: 'bullish' });
    }

    // ── Inverted Hammer (bullish) ──
    if (upperWick4 > body4 * 2 && lowerWick4 < body4 * 0.5 && c3.close < c3.open) {
        results.push({ name: 'Inverted Hammer', signal: 0.5, strength: 0.5, direction: 'bullish' });
    }

    // ── Hanging Man (bearish) ──
    if (lowerWick4 > body4 * 2 && upperWick4 < body4 * 0.5 && c3.close > c3.open) {
        results.push({ name: 'Hanging Man', signal: -0.5, strength: 0.5, direction: 'bearish' });
    }

    // ── Shooting Star (bearish) ──
    if (upperWick4 > body4 * 2 && lowerWick4 < body4 * 0.5 && c3.close > c3.open) {
        results.push({ name: 'Shooting Star', signal: -0.6, strength: 0.6, direction: 'bearish' });
    }

    // ── Marubozu Bullish ──
    if (c4.close > c4.open && body4 / range4 > 0.92 && range4 > 0) {
        results.push({ name: 'Marubozu Bullish', signal: 0.7, strength: 0.7, direction: 'bullish' });
    }

    // ── Marubozu Bearish ──
    if (c4.close < c4.open && body4 / range4 > 0.92 && range4 > 0) {
        results.push({ name: 'Marubozu Bearish', signal: -0.7, strength: 0.7, direction: 'bearish' });
    }

    // ── Bullish Engulfing ──
    if (c3.close < c3.open && c4.close > c4.open &&
        c4.open <= c3.close && c4.close >= c3.open && body4 > body3) {
        results.push({ name: 'Bullish Engulfing', signal: 0.7, strength: 0.7, direction: 'bullish' });
    }

    // ── Bearish Engulfing ──
    if (c3.close > c3.open && c4.close < c4.open &&
        c4.open >= c3.close && c4.close <= c3.open && body4 > body3) {
        results.push({ name: 'Bearish Engulfing', signal: -0.7, strength: 0.7, direction: 'bearish' });
    }

    // ── Piercing Line ──
    if (c3.close < c3.open && c4.close > c4.open &&
        c4.open < c3.low && c4.close > (c3.open + c3.close) / 2 && c4.close < c3.open) {
        results.push({ name: 'Piercing Line', signal: 0.65, strength: 0.65, direction: 'bullish' });
    }

    // ── Dark Cloud Cover ──
    if (c3.close > c3.open && c4.close < c4.open &&
        c4.open > c3.high && c4.close < (c3.open + c3.close) / 2 && c4.close > c3.open) {
        results.push({ name: 'Dark Cloud Cover', signal: -0.65, strength: 0.65, direction: 'bearish' });
    }

    // ── Bullish Harami ──
    if (c3.close < c3.open && c4.close > c4.open &&
        c4.open > c3.close && c4.close < c3.open && body4 < body3 * 0.6) {
        results.push({ name: 'Bullish Harami', signal: 0.45, strength: 0.45, direction: 'bullish' });
    }

    // ── Bearish Harami ──
    if (c3.close > c3.open && c4.close < c4.open &&
        c4.open < c3.close && c4.close > c3.open && body4 < body3 * 0.6) {
        results.push({ name: 'Bearish Harami', signal: -0.45, strength: 0.45, direction: 'bearish' });
    }

    // ── Tweezer Bottom (bullish) ──
    if (c3.close < c3.open && c4.close > c4.open &&
        Math.abs(c3.low - c4.low) < priceTol) {
        results.push({ name: 'Tweezer Bottom', signal: 0.55, strength: 0.55, direction: 'bullish' });
    }

    // ── Tweezer Top (bearish) ──
    if (c3.close > c3.open && c4.close < c4.open &&
        Math.abs(c3.high - c4.high) < priceTol) {
        results.push({ name: 'Tweezer Top', signal: -0.55, strength: 0.55, direction: 'bearish' });
    }

    // ── Morning Star (3-candle bullish reversal) ──
    if (c2.close < c2.open && body3 / (range3 || 1) < 0.3 &&
        c4.close > c4.open && c4.close > (c2.open + c2.close) / 2) {
        results.push({ name: 'Morning Star', signal: 0.8, strength: 0.8, direction: 'bullish' });
    }

    // ── Evening Star (3-candle bearish reversal) ──
    if (c2.close > c2.open && body3 / (range3 || 1) < 0.3 &&
        c4.close < c4.open && c4.close < (c2.open + c2.close) / 2) {
        results.push({ name: 'Evening Star', signal: -0.8, strength: 0.8, direction: 'bearish' });
    }

    // ── Dragonfly Doji (bullish) ──
    if (body4 / range4 < 0.05 && lowerWick4 > range4 * 0.7 && upperWick4 < range4 * 0.05) {
        results.push({ name: 'Dragonfly Doji', signal: 0.5, strength: 0.5, direction: 'bullish' });
    }

    // ── Gravestone Doji (bearish) ──
    if (body4 / range4 < 0.05 && upperWick4 > range4 * 0.7 && lowerWick4 < range4 * 0.05) {
        results.push({ name: 'Gravestone Doji', signal: -0.5, strength: 0.5, direction: 'bearish' });
    }

    // ── Three White Soldiers (strong bullish) ──
    if (c2.close > c2.open && c3.close > c3.open && c4.close > c4.open &&
        c3.close > c2.close && c4.close > c3.close &&
        body2 > range4 * 0.3 && body3 > range4 * 0.3 && body4 > range4 * 0.3) {
        results.push({ name: 'Three White Soldiers', signal: 0.9, strength: 0.9, direction: 'bullish' });
    }

    // ── Three Black Crows (strong bearish) ──
    if (c2.close < c2.open && c3.close < c3.open && c4.close < c4.open &&
        c3.close < c2.close && c4.close < c3.close &&
        body2 > range4 * 0.3 && body3 > range4 * 0.3 && body4 > range4 * 0.3) {
        results.push({ name: 'Three Black Crows', signal: -0.9, strength: 0.9, direction: 'bearish' });
    }

    // ── Rising Three Methods (5-candle bullish continuation) ──
    if (c0.close > c0.open && body0 > range4 * 0.4 &&
        c1.close < c1.open && c2.close < c2.open && c3.close < c3.open &&
        c1.low > c0.low && c2.low > c0.low && c3.low > c0.low &&
        c1.high < c0.high && c2.high < c0.high && c3.high < c0.high &&
        c4.close > c4.open && c4.close > c0.high) {
        results.push({ name: 'Rising Three Methods', signal: 0.85, strength: 0.85, direction: 'bullish' });
    }

    // ── Falling Three Methods (5-candle bearish continuation) ──
    if (c0.close < c0.open && body0 > range4 * 0.4 &&
        c1.close > c1.open && c2.close > c2.open && c3.close > c3.open &&
        c1.high < c0.high && c2.high < c0.high && c3.high < c0.high &&
        c1.low > c0.low && c2.low > c0.low && c3.low > c0.low &&
        c4.close < c4.open && c4.close < c0.low) {
        results.push({ name: 'Falling Three Methods', signal: -0.85, strength: 0.85, direction: 'bearish' });
    }

    return results;
}

// ─── Charts Page ────────────────────────────────────────────────
const ChartsPage = {
    name: 'charts',
    chart: null,
    candleSeries: null,
    volumeSeries: null,
    priceLines: [],
    tradeMarkers: [],
    patternMarkers: [],
    selectedPair: null,
    selectedInterval: 5,
    pairs: [],
    refreshInterval: null,
    unsubscribers: [],
    events: [],
    maxEvents: 50,
    _lastOhlcvCandles: null,
    _multiTfPatterns: [],
    _patternScanInterval: null,
    _recentTrades: [],       // cached trade history for pattern trade-status matching

    async render(container) {
        const html = `
            <div class="page charts-page">
                <div class="charts-layout">
                    <!-- Main Chart Area -->
                    <div class="charts-main">
                        <!-- Toolbar -->
                        <div class="charts-toolbar">
                            <div class="charts-pair-selector" id="charts-pair-tabs"></div>
                            <div class="charts-interval-selector" id="charts-interval-tabs"></div>
                        </div>
                        <!-- Chart Container -->
                        <div class="charts-container" id="charts-canvas"></div>
                        <!-- Event Feed -->
                        <div class="charts-event-feed" id="charts-events">
                            <div class="event-feed-header">
                                <i data-lucide="activity"></i>
                                <span class="font-display">LIVE FEED</span>
                            </div>
                            <div class="event-feed-list" id="event-feed-list"></div>
                        </div>
                    </div>

                    <!-- Sidebar -->
                    <div class="charts-sidebar">
                        <!-- Position Panel -->
                        <div class="charts-panel" id="charts-position-panel">
                            <div class="panel-header font-display">
                                <i data-lucide="briefcase"></i> POSITION
                            </div>
                            <div class="panel-body" id="charts-position-body">
                                <div class="no-position">No active position</div>
                            </div>
                        </div>
                        <!-- Intel Panel -->
                        <div class="charts-panel" id="charts-intel-panel">
                            <div class="panel-header font-display">
                                <i data-lucide="brain"></i> INTEL
                            </div>
                            <div class="panel-body" id="charts-intel-body">
                                <div class="no-intel">Waiting for analysis...</div>
                            </div>
                        </div>
                        <!-- Patterns Panel (multi-timeframe) -->
                        <div class="charts-panel" id="charts-patterns-panel">
                            <div class="panel-header font-display">
                                <i data-lucide="scan"></i> PATTERNS
                                <span class="pattern-scan-badge font-mono" id="pattern-scan-status">SCANNING</span>
                            </div>
                            <div class="panel-body patterns-scrollable" id="charts-patterns-body">
                                <div class="no-patterns">Scanning timeframes...</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        setHTML(container, html);
        if (window.lucide) lucide.createIcons();

        await this.loadPairs();
        this.renderPairTabs();
        this.renderIntervalTabs();

        if (this.pairs.length > 0) {
            this.selectPair(this.pairs[0]);
        }

        this.subscribeToEvents();
        this._startRefreshTimer();

        return this;
    },

    // ─── Adaptive refresh: faster for shorter candles ──────────
    _getRefreshMs() {
        const iv = INTERVALS.find(i => i.value === this.selectedInterval);
        return (iv?.refreshSec || 30) * 1000;
    },

    _startRefreshTimer() {
        this._stopRefreshTimer();
        const ms = this._getRefreshMs();
        this.refreshInterval = setInterval(() => this.refreshChart(), ms);
    },

    _stopRefreshTimer() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    },

    async loadPairs() {
        try {
            const status = await api.get('/api/status');
            this.pairs = status?.pairs || ['BTC/AUD', 'ETH/AUD', 'SOL/AUD', 'DOT/AUD'];
        } catch {
            this.pairs = ['BTC/AUD', 'ETH/AUD', 'SOL/AUD', 'DOT/AUD'];
        }
    },

    renderPairTabs() {
        const container = document.getElementById('charts-pair-tabs');
        if (!container) return;
        container.innerHTML = this.pairs.map((pair, i) => {
            const base = pair.split('/')[0];
            return `<button class="chart-tab ${i === 0 ? 'active' : ''}" data-pair="${escapeHTML(pair)}">${escapeHTML(base)}</button>`;
        }).join('');
        container.querySelectorAll('.chart-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.chart-tab').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.selectPair(btn.dataset.pair);
            });
        });
    },

    renderIntervalTabs() {
        const container = document.getElementById('charts-interval-tabs');
        if (!container) return;
        container.innerHTML = INTERVALS.map(iv => {
            return `<button class="chart-tab interval-tab ${iv.value === this.selectedInterval ? 'active' : ''}" data-interval="${iv.value}">${iv.label}</button>`;
        }).join('');
        container.querySelectorAll('.interval-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.interval-tab').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.selectedInterval = parseInt(btn.dataset.interval);
                this._startRefreshTimer();
                this.loadChartData();
            });
        });
    },

    async selectPair(pair) {
        this.selectedPair = pair;
        this.tradeMarkers = [];
        this.patternMarkers = [];
        this._multiTfPatterns = [];
        this._lastOhlcvCandles = null;
        this._recentTrades = [];
        await this._loadRecentTrades();
        await this.loadChartData();
        this.loadPosition();
        this.loadIntel();
        this.scanMultiTimeframePatterns();
    },

    // ─── Helpers ────────────────────────────────────────────────
    _toSec(ts) {
        return ts > 1e12 ? Math.floor(ts / 1000) : Math.floor(ts);
    },

    _transformCandles(rawCandles) {
        return rawCandles.map(c => {
            if (Array.isArray(c)) {
                return { time: this._toSec(c[0]), open: c[1], high: c[2], low: c[3], close: c[4] };
            }
            return {
                time: this._toSec(new Date(c.timestamp || c.time).getTime()),
                open: c.open, high: c.high, low: c.low, close: c.close,
            };
        }).sort((a, b) => a.time - b.time);
    },

    _transformVolumes(rawCandles) {
        return rawCandles.map(c => {
            if (Array.isArray(c)) {
                return {
                    time: this._toSec(c[0]),
                    value: c[5] || 0,
                    color: c[4] >= c[1] ? 'rgba(0,255,136,0.2)' : 'rgba(255,71,87,0.2)',
                };
            }
            return {
                time: this._toSec(new Date(c.timestamp || c.time).getTime()),
                value: c.volume || 0,
                color: c.close >= c.open ? 'rgba(0,255,136,0.2)' : 'rgba(255,71,87,0.2)',
            };
        }).sort((a, b) => a.time - b.time);
    },

    _createChart(container) {
        this.chart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: container.clientHeight || 500,
            layout: {
                background: { type: 'solid', color: '#0A0D14' },
                textColor: '#8B95A5',
                fontFamily: "'JetBrains Mono', monospace",
            },
            grid: {
                vertLines: { color: 'rgba(42, 46, 57, 0.4)' },
                horzLines: { color: 'rgba(42, 46, 57, 0.4)' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: { color: 'rgba(0, 212, 255, 0.4)', width: 1, style: 2 },
                horzLine: { color: 'rgba(0, 212, 255, 0.4)', width: 1, style: 2 },
            },
            rightPriceScale: {
                borderColor: 'rgba(42, 46, 57, 0.6)',
                scaleMargins: { top: 0.05, bottom: 0.15 },
            },
            timeScale: {
                borderColor: 'rgba(42, 46, 57, 0.6)',
                timeVisible: true,
                secondsVisible: false,
            },
        });

        this.candleSeries = this.chart.addCandlestickSeries({
            upColor: '#00FF88', downColor: '#FF4757',
            borderUpColor: '#00FF88', borderDownColor: '#FF4757',
            wickUpColor: '#00FF88', wickDownColor: '#FF4757',
        });

        this.volumeSeries = this.chart.addHistogramSeries({
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
            scaleMargins: { top: 0.85, bottom: 0 },
        });
        this.chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

        if (this._resizeObserver) this._resizeObserver.disconnect();
        this._resizeObserver = new ResizeObserver(() => {
            if (this.chart && container.clientWidth > 0) {
                this.chart.applyOptions({ width: container.clientWidth, height: container.clientHeight || 500 });
            }
        });
        this._resizeObserver.observe(container);
    },

    // ─── Trade History (for pattern status matching) ──────────
    async _loadRecentTrades() {
        try {
            const history = await api.getHistory(100);
            this._recentTrades = (history?.trades || []).filter(t => t.pair === this.selectedPair);
        } catch {
            this._recentTrades = [];
        }
    },

    _getPatternTradeStatus(pattern) {
        if (!this._recentTrades.length || !pattern.time) {
            return { traded: false, reason: 'No trade history available' };
        }

        const patternTimeSec = pattern.time;
        const patternName = (pattern.name || '').toLowerCase().replace(/\s+/g, '_');
        // Window around the pattern: allow trades slightly before (bot detects same candle)
        // and after. Wider windows for higher timeframes.
        const tfWindows = { '1m': 300, '5m': 1200, '15m': 3600, '1h': 14400 };
        const windowAfter = tfWindows[pattern.timeframe] || 1200;
        const windowBefore = 600; // 10 min before (one bot cycle)

        for (const trade of this._recentTrades) {
            const tradeSec = Math.floor(new Date(trade.timestamp).getTime() / 1000);
            const diff = tradeSec - patternTimeSec;

            // Check time window: trade can be slightly before or after pattern
            if (diff >= -windowBefore && diff <= windowAfter) {
                const tradeAligns = (pattern.signal > 0 && trade.action === 'BUY') ||
                                    (pattern.signal < 0 && trade.action === 'SELL');
                // Also match if trade reasoning mentions this pattern type
                const reasoningMatch = trade.reasoning &&
                    trade.reasoning.toLowerCase().includes(patternName);

                if (tradeAligns || reasoningMatch) {
                    const tradePrice = trade.average_price || trade.price;
                    return {
                        traded: true,
                        action: trade.action,
                        price: tradePrice,
                        reason: `${trade.action} @ ${formatCurrency(tradePrice)}`,
                    };
                }
            }
        }

        // Pattern not traded - determine likely reason
        const strength = Math.abs(pattern.signal);
        let reason;
        if (strength < 0.3) {
            reason = 'Signal too weak (below 38% confidence threshold)';
        } else if (pattern.direction === 'neutral') {
            reason = 'Neutral pattern - no directional signal';
        } else if (strength < 0.5) {
            reason = 'Moderate signal - may not pass confidence gate with other factors';
        } else {
            reason = 'Pattern detected but other signals (trend, sentiment) may have conflicted';
        }

        return { traded: false, reason };
    },

    // ─── Chart Data ──────────────────────────────────────────────
    async loadChartData() {
        if (!this.selectedPair || !window.LightweightCharts) return;
        const container = document.getElementById('charts-canvas');
        if (!container) return;

        try {
            await ohlcvLimiter.acquire();
            const ohlcv = await api.getOHLCV(this.selectedPair, this.selectedInterval, 200);
            if (!ohlcv?.candles || ohlcv.candles.length === 0) {
                container.innerHTML = '<div class="chart-no-data">No OHLCV data available</div>';
                return;
            }

            const candles = this._transformCandles(ohlcv.candles);
            const volumes = this._transformVolumes(ohlcv.candles);
            this._lastOhlcvCandles = candles;

            if (this.chart && this.candleSeries && this.volumeSeries) {
                this.candleSeries.setData(candles);
                this.volumeSeries.setData(volumes);
            } else {
                if (this.chart) { this.chart.remove(); this.chart = null; this.candleSeries = null; this.volumeSeries = null; this.priceLines = []; }
                this._createChart(container);
                this.candleSeries.setData(candles);
                this.volumeSeries.setData(volumes);
                this.chart.timeScale().fitContent();
            }

            const chartPatterns = detectPatterns(candles);
            this._applyChartPatternMarkers(chartPatterns);

            await this.loadTradeMarkers();

        } catch (error) {
            console.error('Failed to load chart data:', error);
            if (!this.chart) container.innerHTML = '<div class="chart-no-data">Failed to load chart data</div>';
        }
    },

    _applyChartPatternMarkers(chartPatterns) {
        const markers = [];
        const recent = chartPatterns.filter(p => p.index >= (this._lastOhlcvCandles?.length || 0) - 30);
        for (const p of recent) {
            const bullish = p.signal > 0;
            markers.push({
                time: p.time,
                position: bullish ? 'belowBar' : 'aboveBar',
                color: bullish ? '#00FFAA' : '#FF6B81',
                shape: 'circle',
                text: p.name,
            });
        }
        this.patternMarkers = markers;
        this._syncMarkers();
    },

    // ─── Multi-Timeframe Pattern Scan ─────────────────────────────
    async scanMultiTimeframePatterns() {
        if (!this.selectedPair) return;

        const badge = document.getElementById('pattern-scan-status');
        if (badge) { badge.textContent = 'SCANNING'; badge.className = 'pattern-scan-badge font-mono scanning'; }

        const allPatterns = [];
        const pair = this.selectedPair;

        for (const tf of PATTERN_SCAN_TFS) {
            if (this.selectedPair !== pair) return;
            try {
                await ohlcvLimiter.acquire();
                const ohlcv = await api.getOHLCV(pair, tf.value, 50);
                if (!ohlcv?.candles || ohlcv.candles.length < 5) continue;

                const candles = this._transformCandles(ohlcv.candles);
                const detected = detectPatterns(candles);

                const recentCount = 5;
                const cutoff = candles.length - recentCount;
                const recent = detected.filter(p => p.index >= cutoff);

                for (const p of recent) {
                    allPatterns.push({ ...p, timeframe: tf.label });
                }
            } catch (e) {
                console.warn(`Pattern scan ${tf.label} failed:`, e);
            }
        }

        allPatterns.sort((a, b) => Math.abs(b.signal) - Math.abs(a.signal));
        this._multiTfPatterns = allPatterns;

        if (badge) { badge.textContent = 'LIVE'; badge.className = 'pattern-scan-badge font-mono live'; }

        this.renderPatterns();
    },

    renderPatterns() {
        const body = document.getElementById('charts-patterns-body');
        if (!body) return;

        const patterns = this._multiTfPatterns;

        if (!patterns || patterns.length === 0) {
            body.innerHTML = '<div class="no-patterns">No patterns detected across timeframes</div>';
            return;
        }

        // Group by timeframe
        const byTf = {};
        for (const p of patterns) {
            if (!byTf[p.timeframe]) byTf[p.timeframe] = [];
            byTf[p.timeframe].push(p);
        }

        let html = '';
        let patternIdx = 0;
        for (const tf of PATTERN_SCAN_TFS) {
            const tfPatterns = byTf[tf.label];
            if (!tfPatterns || tfPatterns.length === 0) continue;

            html += `<div class="pattern-tf-group">
                <div class="pattern-tf-label font-display">${tf.label}</div>`;

            // Deduplicate same pattern name within timeframe (keep strongest)
            const seen = new Map();
            for (const p of tfPatterns) {
                if (!seen.has(p.name) || Math.abs(p.signal) > Math.abs(seen.get(p.name).signal)) {
                    seen.set(p.name, p);
                }
            }

            for (const [, p] of seen) {
                const bullish = p.signal > 0;
                const neutral = p.signal === 0;
                const cls = neutral ? 'neutral' : (bullish ? 'bullish' : 'bearish');
                const info = PATTERN_INFO[p.name];
                const tradeStatus = this._getPatternTradeStatus(p);
                const id = `pat-detail-${patternIdx++}`;

                html += `
                    <div class="pattern-item-wrap">
                        <div class="pattern-item ${cls}" data-toggle="${id}">
                            <span class="pattern-icon">${neutral ? '\u25C6' : (bullish ? '\u25B2' : '\u25BC')}</span>
                            <span class="pattern-name">${escapeHTML(p.name)}</span>
                            <span class="pattern-strength font-mono">${(Math.abs(p.signal) * 100).toFixed(0)}%</span>
                            <span class="pattern-trade-status ${tradeStatus.traded ? 'traded' : 'skipped'}">${tradeStatus.traded ? 'TRADED' : 'SKIPPED'}</span>
                            <span class="pattern-chevron">&#9662;</span>
                        </div>
                        <div class="pattern-detail" id="${id}">
                            ${info ? `
                                <div class="pd-row pd-type">
                                    <span class="pd-label">Type</span>
                                    <span class="pd-value">${escapeHTML(info.type)}</span>
                                </div>
                                <div class="pd-row pd-desc">
                                    <span class="pd-text">${escapeHTML(info.desc)}</span>
                                </div>
                                <div class="pd-section">
                                    <div class="pd-section-title entry">ENTRY</div>
                                    <div class="pd-text">${escapeHTML(info.entry)}</div>
                                </div>
                                <div class="pd-section">
                                    <div class="pd-section-title exit">EXIT / STOP</div>
                                    <div class="pd-text">${escapeHTML(info.exit)}</div>
                                </div>
                                <div class="pd-row">
                                    <span class="pd-label">Reliability</span>
                                    <span class="pd-value">${escapeHTML(info.reliability)}</span>
                                </div>
                            ` : `<div class="pd-text">No detailed info available for this pattern.</div>`}
                            <div class="pd-trade-status ${tradeStatus.traded ? 'traded' : 'skipped'}">
                                <span class="pd-status-icon">${tradeStatus.traded ? '\u2713' : '\u2717'}</span>
                                <span class="pd-status-label">${tradeStatus.traded ? 'System Traded' : 'System Skipped'}</span>
                                <span class="pd-status-reason">${escapeHTML(tradeStatus.reason)}</span>
                            </div>
                        </div>
                    </div>`;
            }
            html += '</div>';
        }

        body.innerHTML = html;

        // Bind toggle clicks
        body.querySelectorAll('.pattern-item[data-toggle]').forEach(item => {
            item.addEventListener('click', () => {
                const detailId = item.dataset.toggle;
                const detail = document.getElementById(detailId);
                if (!detail) return;
                const isOpen = detail.classList.contains('open');
                detail.classList.toggle('open', !isOpen);
                item.classList.toggle('expanded', !isOpen);
            });
        });
    },

    // ─── Trade Markers ───────────────────────────────────────────
    async loadTradeMarkers() {
        if (!this.candleSeries || !this.selectedPair) return;
        try {
            const history = await api.getHistory(50);
            if (!history?.trades) { this.tradeMarkers = []; this._syncMarkers(); return; }
            const markers = [];
            for (const trade of history.trades) {
                if (trade.pair !== this.selectedPair) continue;
                const isBuy = trade.action === 'BUY';
                markers.push({
                    time: Math.floor(new Date(trade.timestamp).getTime() / 1000),
                    position: isBuy ? 'belowBar' : 'aboveBar',
                    color: isBuy ? '#00FF88' : '#FF4757',
                    shape: isBuy ? 'arrowUp' : 'arrowDown',
                    text: `${trade.action} @ ${formatCurrency(trade.average_price || trade.price)}`,
                });
            }
            this.tradeMarkers = markers;
            this._syncMarkers();
        } catch {
            this.tradeMarkers = [];
            this._syncMarkers();
        }
    },

    _syncMarkers() {
        if (!this.candleSeries) return;
        const all = [...this.tradeMarkers, ...this.patternMarkers].sort((a, b) => a.time - b.time);
        this.candleSeries.setMarkers(all);
    },

    // ─── Position ────────────────────────────────────────────────
    async loadPosition() {
        const body = document.getElementById('charts-position-body');
        if (!body || !this.selectedPair) return;
        try {
            const portfolio = await api.getPortfolio();
            if (!portfolio?.positions) { body.innerHTML = '<div class="no-position">No active position</div>'; this.clearPriceLines(); return; }
            const base = this.selectedPair.split('/')[0];
            const pos = portfolio.positions[base];
            if (!pos || !pos.amount || pos.amount <= 0) { body.innerHTML = '<div class="no-position">No active position</div>'; this.clearPriceLines(); return; }

            const pnl = pos.unrealized_pnl || 0;
            const pnlPct = pos.unrealized_pnl_pct || 0;
            const pnlClass = getPnLClass(pnl);

            body.innerHTML = `
                <div class="position-detail">
                    <div class="pos-row"><span class="pos-label">Side</span><span class="pos-value">LONG</span></div>
                    <div class="pos-row"><span class="pos-label">Size</span><span class="pos-value font-mono">${pos.amount}</span></div>
                    <div class="pos-row"><span class="pos-label">Entry</span><span class="pos-value font-mono">${formatCurrency(pos.entry_price)}</span></div>
                    <div class="pos-row"><span class="pos-label">Current</span><span class="pos-value font-mono">${formatCurrency(pos.current_price)}</span></div>
                    <div class="pos-row"><span class="pos-label">Value</span><span class="pos-value font-mono">${formatCurrency(pos.value_quote || pos.amount * pos.current_price)}</span></div>
                    <div class="pos-row"><span class="pos-label">P&L</span><span class="pos-value font-mono ${pnlClass}">${formatCurrency(pnl)} (${formatPercent(pnlPct / 100)})</span></div>
                    ${pos.stop_loss_price ? `<div class="pos-row"><span class="pos-label">Stop Loss</span><span class="pos-value font-mono danger">${formatCurrency(pos.stop_loss_price)}</span></div>` : ''}
                    ${pos.take_profit_price ? `<div class="pos-row"><span class="pos-label">Take Profit</span><span class="pos-value font-mono profit">${formatCurrency(pos.take_profit_price)}</span></div>` : ''}
                </div>
            `;
            this.drawPositionLines(pos);
        } catch {
            body.innerHTML = '<div class="no-position">No active position</div>';
        }
    },

    clearPriceLines() {
        if (this.candleSeries) {
            for (const line of this.priceLines) { try { this.candleSeries.removePriceLine(line); } catch {} }
        }
        this.priceLines = [];
    },

    drawPositionLines(pos) {
        this.clearPriceLines();
        if (!this.candleSeries) return;
        if (pos.entry_price) {
            this.priceLines.push(this.candleSeries.createPriceLine({ price: pos.entry_price, color: '#00D4FF', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: 'Entry' }));
        }
        if (pos.stop_loss_price) {
            this.priceLines.push(this.candleSeries.createPriceLine({ price: pos.stop_loss_price, color: '#FF4757', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: true, title: 'SL' }));
        }
        if (pos.take_profit_price) {
            this.priceLines.push(this.candleSeries.createPriceLine({ price: pos.take_profit_price, color: '#00FF88', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: true, title: 'TP' }));
        }
    },

    // ─── Intel ────────────────────────────────────────────────────
    async loadIntel() {
        const body = document.getElementById('charts-intel-body');
        if (!body || !this.selectedPair) return;
        try {
            const data = await api.get('/api/ai/intel');
            const intel = data?.intel?.[this.selectedPair];
            if (!intel) { body.innerHTML = '<div class="no-intel">Waiting for analysis...</div>'; return; }

            const dirClass = intel.direction > 0 ? 'profit' : intel.direction < 0 ? 'loss' : '';
            const dirLabel = intel.direction > 0 ? 'BULLISH' : intel.direction < 0 ? 'BEARISH' : 'NEUTRAL';

            body.innerHTML = `
                <div class="intel-detail">
                    <div class="intel-direction ${dirClass}">
                        <span class="intel-dir-label">${dirLabel}</span>
                        <span class="intel-dir-value font-mono">${intel.direction > 0 ? '+' : ''}${intel.direction.toFixed(3)}</span>
                    </div>
                    <div class="pos-row"><span class="pos-label">Confidence</span><span class="pos-value font-mono">${formatPercent(intel.confidence)}</span></div>
                    <div class="pos-row"><span class="pos-label">Regime</span><span class="pos-value regime-badge">${escapeHTML(intel.regime || 'unknown')}</span></div>
                    <div class="pos-row"><span class="pos-label">Signals</span><span class="pos-value font-mono">${intel.signal_count || 0}</span></div>
                    ${intel.disagreement !== undefined ? `<div class="pos-row"><span class="pos-label">Disagreement</span><span class="pos-value font-mono">${(intel.disagreement * 100).toFixed(1)}%</span></div>` : ''}
                </div>
            `;
        } catch {
            body.innerHTML = '<div class="no-intel">Waiting for analysis...</div>';
        }
    },

    // ─── WebSocket Events ────────────────────────────────────────
    subscribeToEvents() {
        const unsubTrade = wsManager.subscribe('trade_executed', (data) => {
            this.addEvent('trade', data);
            if (data.pair === this.selectedPair && this.candleSeries) {
                this.loadTradeMarkers();
                this._loadRecentTrades().then(() => this.renderPatterns());
            }
        });

        const unsubIntel = wsManager.subscribe('intel_update', (data) => {
            this.addEvent('intel', data);
            if (data.pair === this.selectedPair) this.loadIntel();
        });

        const unsubPortfolio = wsManager.subscribe('portfolio', () => this.loadPosition());

        this.unsubscribers.push(unsubTrade, unsubIntel, unsubPortfolio);
    },

    addEvent(type, data) {
        this.events.unshift({ type, data, timestamp: Date.now() });
        if (this.events.length > this.maxEvents) this.events = this.events.slice(0, this.maxEvents);
        this.renderEvents();
    },

    renderEvents() {
        const list = document.getElementById('event-feed-list');
        if (!list) return;
        list.innerHTML = this.events.slice(0, 15).map(ev => {
            const timeAgo = formatTimeAgo(new Date(ev.timestamp).toISOString());
            if (ev.type === 'trade') {
                const isBuy = ev.data.action === 'BUY';
                return `<div class="event-item event-trade"><span class="event-dot ${isBuy ? 'buy' : 'sell'}"></span><span class="event-text">${ev.data.action} ${escapeHTML(ev.data.pair)} @ ${formatCurrency(ev.data.price)}</span><span class="event-time">${timeAgo}</span></div>`;
            } else if (ev.type === 'intel') {
                const dir = ev.data.direction > 0 ? 'bullish' : ev.data.direction < 0 ? 'bearish' : 'neutral';
                return `<div class="event-item event-intel"><span class="event-dot ${dir}"></span><span class="event-text">${escapeHTML(ev.data.pair)} intel: ${dir} (${formatPercent(ev.data.confidence)})</span><span class="event-time">${timeAgo}</span></div>`;
            }
            return '';
        }).join('');
    },

    // ─── Refresh ─────────────────────────────────────────────────
    async refreshChart() {
        if (this.selectedPair) {
            await this.loadChartData();
            this.loadPosition();
            this.loadIntel();
            this._refreshCount = (this._refreshCount || 0) + 1;
            if (this._refreshCount % 3 === 0) {
                this.scanMultiTimeframePatterns();
            }
        }
    },

    // ─── Cleanup ─────────────────────────────────────────────────
    destroy() {
        this._stopRefreshTimer();
        if (this._patternScanInterval) { clearInterval(this._patternScanInterval); this._patternScanInterval = null; }
        this.unsubscribers.forEach(unsub => unsub());
        this.unsubscribers = [];
        if (this._resizeObserver) { this._resizeObserver.disconnect(); this._resizeObserver = null; }
        if (this.chart) { this.chart.remove(); this.chart = null; this.candleSeries = null; this.volumeSeries = null; }
        this.priceLines = [];
        this.tradeMarkers = [];
        this.patternMarkers = [];
        this._multiTfPatterns = [];
        this._lastOhlcvCandles = null;
        this._recentTrades = [];
        this.events = [];
    }
};

export default ChartsPage;
