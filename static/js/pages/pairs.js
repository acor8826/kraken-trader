/**
 * Trading Pairs Page - Kraken Trading Dashboard
 * Card grid showing all trading pairs with mini charts
 */

import store from '../store.js';
import api from '../api.js';
import { formatCurrency, formatPercent, formatCryptoAmount, setHTML, escapeHTML, getPnLClass } from '../utils.js';

// ========================================
// Trading Pairs Page Module
// ========================================

const PairsPage = {
    name: 'pairs',
    charts: new Map(),
    refreshInterval: null,
    unsubscribers: [],

    /**
     * Render the pairs page
     */
    async render(container) {
        const html = `
            <div class="page pairs-page">
                <header class="page-header">
                    <div class="page-title-group">
                        <h1 class="page-title font-display">
                            <i data-lucide="candlestick-chart"></i>
                            TRADING PAIRS
                        </h1>
                        <p class="page-subtitle">Active trading pairs with real-time price data</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-secondary" id="refresh-pairs">
                            <i data-lucide="refresh-cw"></i>
                            Refresh
                        </button>
                    </div>
                </header>

                <div class="pairs-grid" id="pairs-grid">
                    <div class="pairs-loading">
                        <div class="pulse-loader"></div>
                        <span>Loading trading pairs...</span>
                    </div>
                </div>
            </div>
        `;

        setHTML(container, html);

        // Setup event listeners
        document.getElementById('refresh-pairs')?.addEventListener('click', () => this.loadPairs());

        // Load data
        await this.loadPairs();

        // Refresh every 30 seconds
        this.refreshInterval = setInterval(() => this.loadPairs(), 30000);

        return this;
    },

    /**
     * Load trading pairs data
     */
    async loadPairs() {
        try {
            const [positions, portfolio] = await Promise.all([
                api.getDetailedPositions().catch(() => null),
                api.getPortfolio()
            ]);

            // Use positions if available, otherwise fall back to portfolio positions
            const pairs = positions?.positions || portfolio?.positions || [];
            this.renderPairs(pairs);

        } catch (error) {
            console.error('Failed to load pairs:', error);
            this.renderError();
        }
    },

    /**
     * Render pairs grid
     */
    renderPairs(pairs) {
        const grid = document.getElementById('pairs-grid');
        if (!grid) return;

        if (!pairs || pairs.length === 0) {
            grid.innerHTML = `
                <div class="pairs-empty">
                    <i data-lucide="inbox"></i>
                    <h3>No Active Positions</h3>
                    <p>Start trading to see your positions here</p>
                </div>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        const cardsHtml = pairs.map((pair, index) => this.renderPairCard(pair, index)).join('');
        grid.innerHTML = cardsHtml;
        if (window.lucide) lucide.createIcons();

        // Initialize mini charts for each pair
        pairs.forEach(pair => {
            this.initMiniChart(pair);
        });
    },

    /**
     * Render individual pair card
     */
    renderPairCard(pair, index) {
        const symbol = pair.symbol || pair.pair || 'UNKNOWN';
        const base = symbol.split('/')[0] || symbol;
        const quote = symbol.split('/')[1] || 'USDT';
        const amount = pair.amount || pair.quantity || 0;
        const currentPrice = pair.current_price || pair.price || 0;
        const entryPrice = pair.entry_price || pair.avg_price || currentPrice;
        const value = pair.current_value || pair.value || (amount * currentPrice);
        const pnl = pair.pnl || pair.unrealized_pnl || 0;
        const pnlPct = pair.pnl_percent || (entryPrice > 0 ? ((currentPrice - entryPrice) / entryPrice) : 0);
        const pnlClass = getPnLClass(pnl);
        const direction = pair.direction || (pnl >= 0 ? 'long' : 'short');

        return `
            <div class="pair-card" data-pair="${escapeHTML(symbol)}" style="animation-delay: ${index * 50}ms">
                <div class="pair-card-glow"></div>

                <!-- Header -->
                <div class="pair-card-header">
                    <div class="pair-symbol">
                        <span class="symbol-base font-display">${escapeHTML(base)}</span>
                        <span class="symbol-quote">/${escapeHTML(quote)}</span>
                    </div>
                    <span class="pair-direction ${direction}">${direction.toUpperCase()}</span>
                </div>

                <!-- Mini Chart -->
                <div class="pair-chart" id="chart-${escapeHTML(symbol.replace('/', '-'))}">
                    <div class="chart-placeholder">
                        <div class="mini-chart-skeleton"></div>
                    </div>
                </div>

                <!-- Price Info -->
                <div class="pair-price-row">
                    <div class="current-price">
                        <span class="price-label">Current</span>
                        <span class="price-value font-mono">${formatCurrency(currentPrice)}</span>
                    </div>
                    <div class="price-change ${pnlClass}">
                        <i data-lucide="${pnl >= 0 ? 'trending-up' : 'trending-down'}"></i>
                        <span class="font-mono">${formatPercent(pnlPct)}</span>
                    </div>
                </div>

                <!-- Position Details -->
                <div class="pair-details">
                    <div class="detail-row">
                        <span class="detail-label">Amount</span>
                        <span class="detail-value font-mono">${formatCryptoAmount(amount, base)}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Entry</span>
                        <span class="detail-value font-mono">${formatCurrency(entryPrice)}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Value</span>
                        <span class="detail-value font-mono">${formatCurrency(value)}</span>
                    </div>
                    <div class="detail-row pnl-row">
                        <span class="detail-label">P&L</span>
                        <span class="detail-value font-mono ${pnlClass}">${formatCurrency(pnl)}</span>
                    </div>
                </div>

                <!-- Stop Loss Indicator -->
                ${pair.stop_loss ? `
                    <div class="pair-stop-loss">
                        <i data-lucide="shield-alert"></i>
                        <span>Stop Loss: ${formatCurrency(pair.stop_loss)}</span>
                    </div>
                ` : ''}

                <!-- Action Button -->
                <div class="pair-actions">
                    <button class="btn btn-sm btn-outline" onclick="window.location.hash='/trades?pair=${encodeURIComponent(symbol)}'">
                        View Trades
                    </button>
                </div>
            </div>
        `;
    },

    /**
     * Initialize mini chart for a pair
     */
    async initMiniChart(pair) {
        const symbol = pair.symbol || pair.pair;
        if (!symbol || !window.LightweightCharts) return;

        const containerId = `chart-${symbol.replace('/', '-')}`;
        const container = document.getElementById(containerId);
        if (!container) return;

        // Clear placeholder
        container.innerHTML = '';

        try {
            // Fetch OHLCV data
            const ohlcv = await api.getOHLCV(symbol, 60, 24);

            if (!ohlcv?.candles || ohlcv.candles.length === 0) {
                container.innerHTML = '<div class="chart-no-data">No data</div>';
                return;
            }

            // Create mini chart
            const chart = LightweightCharts.createChart(container, {
                width: container.clientWidth,
                height: 80,
                layout: {
                    background: { type: 'solid', color: 'transparent' },
                    textColor: 'transparent'
                },
                grid: {
                    vertLines: { visible: false },
                    horzLines: { visible: false }
                },
                rightPriceScale: { visible: false },
                timeScale: { visible: false },
                crosshair: { mode: LightweightCharts.CrosshairMode.Hidden },
                handleScroll: false,
                handleScale: false
            });

            const pnl = pair.pnl || 0;
            const lineColor = pnl >= 0 ? '#00FF88' : '#FF4757';

            const areaSeries = chart.addAreaSeries({
                lineColor: lineColor,
                lineWidth: 2,
                topColor: pnl >= 0 ? 'rgba(0, 255, 136, 0.3)' : 'rgba(255, 71, 87, 0.3)',
                bottomColor: 'transparent',
                crosshairMarkerVisible: false
            });

            // Transform data
            const data = ohlcv.candles.map(c => ({
                time: Math.floor(new Date(c.timestamp || c.time).getTime() / 1000),
                value: c.close
            })).sort((a, b) => a.time - b.time);

            areaSeries.setData(data);
            chart.timeScale().fitContent();

            this.charts.set(symbol, chart);

        } catch (error) {
            console.error(`Failed to load chart for ${symbol}:`, error);
            container.innerHTML = '<div class="chart-no-data">Chart unavailable</div>';
        }
    },

    /**
     * Render error state
     */
    renderError() {
        const grid = document.getElementById('pairs-grid');
        if (grid) {
            grid.innerHTML = `
                <div class="pairs-error">
                    <i data-lucide="alert-triangle"></i>
                    <h3>Failed to Load Pairs</h3>
                    <p>Please try refreshing the page</p>
                </div>
            `;
            if (window.lucide) lucide.createIcons();
        }
    },

    /**
     * Cleanup on page destroy
     */
    destroy() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }

        this.unsubscribers.forEach(unsub => unsub());
        this.unsubscribers = [];

        // Cleanup charts
        this.charts.forEach(chart => chart.remove());
        this.charts.clear();
    }
};

export default PairsPage;
