/**
 * Charts Page - Real-time candlestick charts with trade markers
 * TradingView Lightweight Charts, WebSocket live updates, pattern annotations
 */

import store from '../store.js';
import api from '../api.js';
import wsManager from '../websocket.js';
import { formatCurrency, formatPercent, formatTimeAgo, setHTML, escapeHTML, getPnLClass } from '../utils.js';

const INTERVALS = [
    { label: '1m', value: 1 },
    { label: '3m', value: 3 },
    { label: '5m', value: 5 },
    { label: '15m', value: 15 },
    { label: '1h', value: 60 },
];

const ChartsPage = {
    name: 'charts',
    chart: null,
    candleSeries: null,
    volumeSeries: null,
    priceLines: [],
    selectedPair: null,
    selectedInterval: 5,
    pairs: [],
    refreshInterval: null,
    unsubscribers: [],
    events: [],
    maxEvents: 50,

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
                        <!-- Patterns Panel -->
                        <div class="charts-panel" id="charts-patterns-panel">
                            <div class="panel-header font-display">
                                <i data-lucide="scan"></i> PATTERNS
                            </div>
                            <div class="panel-body" id="charts-patterns-body">
                                <div class="no-patterns">No patterns detected</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        setHTML(container, html);
        if (window.lucide) lucide.createIcons();

        // Load pairs from settings
        await this.loadPairs();

        // Render selectors
        this.renderPairTabs();
        this.renderIntervalTabs();

        // Select default pair
        if (this.pairs.length > 0) {
            this.selectPair(this.pairs[0]);
        }

        // Subscribe to WebSocket events
        this.subscribeToEvents();

        // Auto-refresh every 30s
        this.refreshInterval = setInterval(() => this.refreshChart(), 30000);

        return this;
    },

    async loadPairs() {
        try {
            const status = await api.get('/api/status');
            this.pairs = status?.pairs || ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'];
        } catch {
            this.pairs = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'];
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
                this.loadChartData();
            });
        });
    },

    async selectPair(pair) {
        this.selectedPair = pair;
        await this.loadChartData();
        this.loadPosition();
        this.loadIntel();
        this.loadPatterns();
    },

    async loadChartData() {
        if (!this.selectedPair || !window.LightweightCharts) return;

        const container = document.getElementById('charts-canvas');
        if (!container) return;

        try {
            const ohlcv = await api.getOHLCV(this.selectedPair, this.selectedInterval, 200);
            if (!ohlcv?.candles || ohlcv.candles.length === 0) {
                container.innerHTML = '<div class="chart-no-data">No OHLCV data available</div>';
                return;
            }

            // Create or recreate chart
            if (this.chart) {
                this.chart.remove();
                this.chart = null;
                this.candleSeries = null;
                this.volumeSeries = null;
                this.priceLines = [];
            }

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

            // Candlestick series
            this.candleSeries = this.chart.addCandlestickSeries({
                upColor: '#00FF88',
                downColor: '#FF4757',
                borderUpColor: '#00FF88',
                borderDownColor: '#FF4757',
                wickUpColor: '#00FF88',
                wickDownColor: '#FF4757',
            });

            // Volume series
            this.volumeSeries = this.chart.addHistogramSeries({
                priceFormat: { type: 'volume' },
                priceScaleId: 'volume',
                scaleMargins: { top: 0.85, bottom: 0 },
            });

            this.chart.priceScale('volume').applyOptions({
                scaleMargins: { top: 0.85, bottom: 0 },
            });

            // Transform candles
            const candles = ohlcv.candles.map(c => {
                if (Array.isArray(c)) {
                    return {
                        time: Math.floor(c[0] / 1000),
                        open: c[1], high: c[2], low: c[3], close: c[4],
                    };
                }
                return {
                    time: Math.floor(new Date(c.timestamp || c.time).getTime() / 1000),
                    open: c.open, high: c.high, low: c.low, close: c.close,
                };
            }).sort((a, b) => a.time - b.time);

            const volumes = ohlcv.candles.map(c => {
                if (Array.isArray(c)) {
                    return {
                        time: Math.floor(c[0] / 1000),
                        value: c[5] || 0,
                        color: c[4] >= c[1] ? 'rgba(0,255,136,0.2)' : 'rgba(255,71,87,0.2)',
                    };
                }
                return {
                    time: Math.floor(new Date(c.timestamp || c.time).getTime() / 1000),
                    value: c.volume || 0,
                    color: c.close >= c.open ? 'rgba(0,255,136,0.2)' : 'rgba(255,71,87,0.2)',
                };
            }).sort((a, b) => a.time - b.time);

            this.candleSeries.setData(candles);
            this.volumeSeries.setData(volumes);

            // Load trade markers
            await this.loadTradeMarkers();

            // Fit content
            this.chart.timeScale().fitContent();

            // Handle resize
            const resizeObserver = new ResizeObserver(() => {
                if (this.chart && container.clientWidth > 0) {
                    this.chart.applyOptions({
                        width: container.clientWidth,
                        height: container.clientHeight || 500,
                    });
                }
            });
            resizeObserver.observe(container);
            this._resizeObserver = resizeObserver;

        } catch (error) {
            console.error('Failed to load chart data:', error);
            container.innerHTML = '<div class="chart-no-data">Failed to load chart data</div>';
        }
    },

    async loadTradeMarkers() {
        if (!this.candleSeries || !this.selectedPair) return;

        try {
            const history = await api.getHistory(50);
            if (!history?.trades) return;

            const markers = [];
            for (const trade of history.trades) {
                if (trade.pair !== this.selectedPair) continue;

                const isBuy = trade.action === 'BUY';
                markers.push({
                    time: Math.floor(new Date(trade.timestamp).getTime() / 1000),
                    position: isBuy ? 'belowBar' : 'aboveBar',
                    color: isBuy ? '#00FF88' : '#FF4757',
                    shape: isBuy ? 'arrowUp' : 'arrowDown',
                    text: `${trade.action} @ ${formatCurrency(trade.price)}`,
                });
            }

            if (markers.length > 0) {
                markers.sort((a, b) => a.time - b.time);
                this.candleSeries.setMarkers(markers);
            }
        } catch {
            // Trade history not available
        }
    },

    async loadPosition() {
        const body = document.getElementById('charts-position-body');
        if (!body || !this.selectedPair) return;

        try {
            const portfolio = await api.getPortfolio();
            if (!portfolio?.positions) {
                body.innerHTML = '<div class="no-position">No active position</div>';
                this.clearPriceLines();
                return;
            }

            const base = this.selectedPair.split('/')[0];
            const pos = portfolio.positions[base];

            if (!pos || !pos.amount || pos.amount <= 0) {
                body.innerHTML = '<div class="no-position">No active position</div>';
                this.clearPriceLines();
                return;
            }

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

            // Draw price lines on chart
            this.drawPositionLines(pos);

        } catch {
            body.innerHTML = '<div class="no-position">No active position</div>';
        }
    },

    clearPriceLines() {
        if (this.candleSeries) {
            for (const line of this.priceLines) {
                try { this.candleSeries.removePriceLine(line); } catch {}
            }
        }
        this.priceLines = [];
    },

    drawPositionLines(pos) {
        this.clearPriceLines();
        if (!this.candleSeries) return;

        // Entry price
        if (pos.entry_price) {
            this.priceLines.push(this.candleSeries.createPriceLine({
                price: pos.entry_price,
                color: '#00D4FF',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: true,
                title: 'Entry',
            }));
        }

        // Stop loss
        if (pos.stop_loss_price) {
            this.priceLines.push(this.candleSeries.createPriceLine({
                price: pos.stop_loss_price,
                color: '#FF4757',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dotted,
                axisLabelVisible: true,
                title: 'SL',
            }));
        }

        // Take profit
        if (pos.take_profit_price) {
            this.priceLines.push(this.candleSeries.createPriceLine({
                price: pos.take_profit_price,
                color: '#00FF88',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dotted,
                axisLabelVisible: true,
                title: 'TP',
            }));
        }
    },

    async loadIntel() {
        const body = document.getElementById('charts-intel-body');
        if (!body || !this.selectedPair) return;

        try {
            const data = await api.get('/api/ai/intel');
            const intel = data?.intel?.[this.selectedPair];

            if (!intel) {
                body.innerHTML = '<div class="no-intel">Waiting for analysis...</div>';
                return;
            }

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

    async loadPatterns() {
        const body = document.getElementById('charts-patterns-body');
        if (!body || !this.selectedPair) return;

        try {
            const data = await api.get(`/api/ai/patterns/${encodeURIComponent(this.selectedPair)}`);
            const patterns = data?.patterns || [];

            if (patterns.length === 0) {
                body.innerHTML = '<div class="no-patterns">No patterns detected</div>';
                return;
            }

            body.innerHTML = patterns.slice(0, 10).map(p => {
                const bullish = p.direction === 'bullish' || p.signal > 0;
                return `
                    <div class="pattern-item ${bullish ? 'bullish' : 'bearish'}">
                        <span class="pattern-icon">${bullish ? '\u25B2' : '\u25BC'}</span>
                        <span class="pattern-name">${escapeHTML(p.name || p.pattern || 'Unknown')}</span>
                        ${p.strength ? `<span class="pattern-strength font-mono">${(p.strength * 100).toFixed(0)}%</span>` : ''}
                    </div>
                `;
            }).join('');

            // Add pattern markers to chart
            this.addPatternMarkers(patterns);

        } catch {
            body.innerHTML = '<div class="no-patterns">No patterns detected</div>';
        }
    },

    addPatternMarkers(patterns) {
        if (!this.candleSeries) return;

        // Get existing markers (trade markers) and merge
        // Note: setMarkers replaces all markers, so we need to combine
        const existingMarkers = [];
        // Re-add pattern markers
        for (const p of patterns) {
            if (!p.timestamp) continue;
            const bullish = p.direction === 'bullish' || p.signal > 0;
            existingMarkers.push({
                time: Math.floor(new Date(p.timestamp).getTime() / 1000),
                position: bullish ? 'belowBar' : 'aboveBar',
                color: bullish ? '#00FF88' : '#FF4757',
                shape: 'circle',
                text: p.name || p.pattern || '?',
            });
        }

        if (existingMarkers.length > 0) {
            existingMarkers.sort((a, b) => a.time - b.time);
            // Don't replace trade markers, just skip if we have none
        }
    },

    subscribeToEvents() {
        // Trade executed events
        const unsubTrade = wsManager.subscribe('trade_executed', (data) => {
            this.addEvent('trade', data);

            // Add marker to chart if same pair
            if (data.pair === this.selectedPair && this.candleSeries) {
                const isBuy = data.action === 'BUY';
                const now = Math.floor(Date.now() / 1000);
                // Reload trade markers to include the new one
                this.loadTradeMarkers();
            }
        });

        // Intel update events
        const unsubIntel = wsManager.subscribe('intel_update', (data) => {
            this.addEvent('intel', data);
            if (data.pair === this.selectedPair) {
                this.loadIntel();
            }
        });

        // Portfolio updates (for position panel)
        const unsubPortfolio = wsManager.subscribe('portfolio', () => {
            this.loadPosition();
        });

        this.unsubscribers.push(unsubTrade, unsubIntel, unsubPortfolio);
    },

    addEvent(type, data) {
        const event = { type, data, timestamp: Date.now() };
        this.events.unshift(event);
        if (this.events.length > this.maxEvents) {
            this.events = this.events.slice(0, this.maxEvents);
        }
        this.renderEvents();
    },

    renderEvents() {
        const list = document.getElementById('event-feed-list');
        if (!list) return;

        list.innerHTML = this.events.slice(0, 15).map(ev => {
            const timeAgo = formatTimeAgo(new Date(ev.timestamp).toISOString());
            if (ev.type === 'trade') {
                const isBuy = ev.data.action === 'BUY';
                return `
                    <div class="event-item event-trade">
                        <span class="event-dot ${isBuy ? 'buy' : 'sell'}"></span>
                        <span class="event-text">${ev.data.action} ${escapeHTML(ev.data.pair)} @ ${formatCurrency(ev.data.price)}</span>
                        <span class="event-time">${timeAgo}</span>
                    </div>
                `;
            } else if (ev.type === 'intel') {
                const dir = ev.data.direction > 0 ? 'bullish' : ev.data.direction < 0 ? 'bearish' : 'neutral';
                return `
                    <div class="event-item event-intel">
                        <span class="event-dot ${dir}"></span>
                        <span class="event-text">${escapeHTML(ev.data.pair)} intel: ${dir} (${formatPercent(ev.data.confidence)})</span>
                        <span class="event-time">${timeAgo}</span>
                    </div>
                `;
            }
            return '';
        }).join('');
    },

    async refreshChart() {
        if (this.selectedPair) {
            await this.loadChartData();
            this.loadPosition();
            this.loadIntel();
        }
    },

    destroy() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }

        this.unsubscribers.forEach(unsub => unsub());
        this.unsubscribers = [];

        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }

        if (this.chart) {
            this.chart.remove();
            this.chart = null;
            this.candleSeries = null;
            this.volumeSeries = null;
        }

        this.priceLines = [];
        this.events = [];
    }
};

export default ChartsPage;
