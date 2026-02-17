/**
 * Homepage - Kraken Trading Dashboard
 * Command center layout: AI Activity (1/3) | Portfolio Chart (2/3) | Metrics Grid
 */

import store from '../store.js';
import api from '../api.js';
import { formatCurrency, formatPercent, formatTimeAgo, formatNumber, setHTML, escapeHTML } from '../utils.js';

// ========================================
// Homepage Module
// ========================================

const HomePage = {
    name: 'home',
    chart: null,
    areaSeries: null,
    refreshInterval: null,
    unsubscribers: [],

    /**
     * Render the homepage
     */
    async render(container) {
        const html = `
            <div class="page home-page">
                <!-- Command Grid: Activity + Chart -->
                <div class="command-grid">
                    <!-- AI Activity Feed (Left 1/3) -->
                    <section class="activity-panel" aria-label="AI Activity Feed">
                        <div class="panel-header">
                            <div class="panel-title">
                                <i data-lucide="activity"></i>
                                <span class="font-display">AI ACTIVITY</span>
                            </div>
                            <div class="panel-badge live-badge">
                                <span class="live-dot"></span>
                                <span>LIVE</span>
                            </div>
                        </div>
                        <div class="activity-feed" id="activity-feed">
                            <div class="activity-loading">
                                <div class="pulse-loader"></div>
                                <span>Initializing feed...</span>
                            </div>
                        </div>
                        <div class="activity-footer">
                            <span class="activity-count" id="activity-count">0 events</span>
                        </div>
                    </section>

                    <!-- Portfolio Chart (Right 2/3) -->
                    <section class="chart-panel" aria-label="Portfolio Performance">
                        <div class="panel-header">
                            <div class="panel-title">
                                <i data-lucide="trending-up"></i>
                                <span class="font-display">PORTFOLIO PERFORMANCE</span>
                            </div>
                            <div class="chart-controls">
                                <div class="time-selector" role="tablist">
                                    <button class="time-btn" data-range="1H" role="tab">1H</button>
                                    <button class="time-btn" data-range="24H" role="tab">24H</button>
                                    <button class="time-btn active" data-range="7D" role="tab">7D</button>
                                    <button class="time-btn" data-range="30D" role="tab">30D</button>
                                </div>
                            </div>
                        </div>
                        <div class="chart-container" id="portfolio-chart">
                            <div class="chart-loading">
                                <div class="chart-skeleton"></div>
                            </div>
                        </div>
                        <div class="chart-footer">
                            <div class="chart-stat">
                                <span class="stat-label">Current</span>
                                <span class="stat-value font-mono" id="chart-current">$0.00</span>
                            </div>
                            <div class="chart-stat">
                                <span class="stat-label">Change</span>
                                <span class="stat-value font-mono profit" id="chart-change">+$0.00</span>
                            </div>
                            <div class="chart-stat">
                                <span class="stat-label">High</span>
                                <span class="stat-value font-mono" id="chart-high">$0.00</span>
                            </div>
                            <div class="chart-stat">
                                <span class="stat-label">Low</span>
                                <span class="stat-value font-mono" id="chart-low">$0.00</span>
                            </div>
                        </div>
                    </section>
                </div>

                <!-- Metrics Grid -->
                <section class="metrics-section" aria-label="Performance Metrics">
                    <div class="metrics-grid">
                        <!-- Win Rate -->
                        <div class="metric-card" data-metric="winrate">
                            <div class="metric-glow"></div>
                            <div class="metric-icon">
                                <i data-lucide="target"></i>
                            </div>
                            <div class="metric-content">
                                <span class="metric-label font-display">WIN RATE</span>
                                <span class="metric-value font-mono" id="metric-winrate">0%</span>
                                <div class="metric-trend up" id="trend-winrate">
                                    <i data-lucide="trending-up"></i>
                                    <span>--</span>
                                </div>
                            </div>
                            <div class="metric-bar">
                                <div class="metric-bar-fill" id="bar-winrate" style="width: 0%"></div>
                            </div>
                        </div>

                        <!-- Total Trades -->
                        <div class="metric-card" data-metric="trades">
                            <div class="metric-glow"></div>
                            <div class="metric-icon">
                                <i data-lucide="repeat"></i>
                            </div>
                            <div class="metric-content">
                                <span class="metric-label font-display">TOTAL TRADES</span>
                                <span class="metric-value font-mono" id="metric-trades">0</span>
                                <div class="metric-trend neutral" id="trend-trades">
                                    <i data-lucide="minus"></i>
                                    <span>--</span>
                                </div>
                            </div>
                            <div class="metric-bar">
                                <div class="metric-bar-fill" id="bar-trades" style="width: 0%"></div>
                            </div>
                        </div>

                        <!-- Profit Factor -->
                        <div class="metric-card" data-metric="profitfactor">
                            <div class="metric-glow"></div>
                            <div class="metric-icon">
                                <i data-lucide="divide"></i>
                            </div>
                            <div class="metric-content">
                                <span class="metric-label font-display">PROFIT FACTOR</span>
                                <span class="metric-value font-mono" id="metric-profitfactor">0.00</span>
                                <div class="metric-trend up" id="trend-profitfactor">
                                    <i data-lucide="trending-up"></i>
                                    <span>--</span>
                                </div>
                            </div>
                            <div class="metric-bar">
                                <div class="metric-bar-fill" id="bar-profitfactor" style="width: 0%"></div>
                            </div>
                        </div>

                        <!-- Max Drawdown -->
                        <div class="metric-card" data-metric="drawdown">
                            <div class="metric-glow"></div>
                            <div class="metric-icon warning">
                                <i data-lucide="trending-down"></i>
                            </div>
                            <div class="metric-content">
                                <span class="metric-label font-display">MAX DRAWDOWN</span>
                                <span class="metric-value font-mono" id="metric-drawdown">0%</span>
                                <div class="metric-trend down" id="trend-drawdown">
                                    <i data-lucide="trending-down"></i>
                                    <span>--</span>
                                </div>
                            </div>
                            <div class="metric-bar warning">
                                <div class="metric-bar-fill" id="bar-drawdown" style="width: 0%"></div>
                            </div>
                        </div>

                        <!-- Total Exposure -->
                        <div class="metric-card" data-metric="exposure">
                            <div class="metric-glow"></div>
                            <div class="metric-icon">
                                <i data-lucide="pie-chart"></i>
                            </div>
                            <div class="metric-content">
                                <span class="metric-label font-display">EXPOSURE</span>
                                <span class="metric-value font-mono" id="metric-exposure">0%</span>
                                <div class="metric-trend neutral" id="trend-exposure">
                                    <i data-lucide="minus"></i>
                                    <span>--</span>
                                </div>
                            </div>
                            <div class="metric-bar">
                                <div class="metric-bar-fill" id="bar-exposure" style="width: 0%"></div>
                            </div>
                        </div>

                        <!-- Sharpe Ratio -->
                        <div class="metric-card" data-metric="sharpe">
                            <div class="metric-glow"></div>
                            <div class="metric-icon">
                                <i data-lucide="gauge"></i>
                            </div>
                            <div class="metric-content">
                                <span class="metric-label font-display">SHARPE RATIO</span>
                                <span class="metric-value font-mono" id="metric-sharpe">0.00</span>
                                <div class="metric-trend up" id="trend-sharpe">
                                    <i data-lucide="trending-up"></i>
                                    <span>--</span>
                                </div>
                            </div>
                            <div class="metric-bar">
                                <div class="metric-bar-fill" id="bar-sharpe" style="width: 0%"></div>
                            </div>
                        </div>
                    </div>
                </section>
            </div>
        `;

        setHTML(container, html);

        // Initialize components
        await this.initChart();
        this.initTimeSelector();
        this.initActivityFeed();
        this.loadData();
        this.subscribeToUpdates();

        // Start refresh interval
        this.refreshInterval = setInterval(() => this.loadData(), 30000);

        return this;
    },

    /**
     * Initialize TradingView Lightweight Chart
     */
    async initChart() {
        const chartContainer = document.getElementById('portfolio-chart');
        if (!chartContainer || !window.LightweightCharts) return;

        // Clear loading state
        chartContainer.innerHTML = '';

        // Create chart with cyberpunk theme
        this.chart = LightweightCharts.createChart(chartContainer, {
            width: chartContainer.clientWidth,
            height: 320,
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: 'rgba(0, 212, 255, 0.7)',
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11
            },
            grid: {
                vertLines: { color: 'rgba(0, 212, 255, 0.06)' },
                horzLines: { color: 'rgba(0, 212, 255, 0.06)' }
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {
                    color: 'rgba(0, 212, 255, 0.5)',
                    width: 1,
                    style: LightweightCharts.LineStyle.Dashed,
                    labelBackgroundColor: '#0a0d14'
                },
                horzLine: {
                    color: 'rgba(0, 212, 255, 0.5)',
                    width: 1,
                    style: LightweightCharts.LineStyle.Dashed,
                    labelBackgroundColor: '#0a0d14'
                }
            },
            rightPriceScale: {
                borderColor: 'rgba(0, 212, 255, 0.2)',
                scaleMargins: { top: 0.1, bottom: 0.1 }
            },
            timeScale: {
                borderColor: 'rgba(0, 212, 255, 0.2)',
                timeVisible: true,
                secondsVisible: false
            },
            handleScroll: { mouseWheel: true, pressedMouseMove: true },
            handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true }
        });

        // Add area series with gradient
        this.areaSeries = this.chart.addAreaSeries({
            lineColor: '#00D4FF',
            lineWidth: 2,
            topColor: 'rgba(0, 212, 255, 0.4)',
            bottomColor: 'rgba(0, 212, 255, 0.0)',
            crosshairMarkerVisible: true,
            crosshairMarkerRadius: 6,
            crosshairMarkerBorderColor: '#00D4FF',
            crosshairMarkerBackgroundColor: '#0a0d14'
        });

        // Handle resize
        const resizeObserver = new ResizeObserver(entries => {
            if (this.chart) {
                const { width } = entries[0].contentRect;
                this.chart.applyOptions({ width });
            }
        });
        resizeObserver.observe(chartContainer);

        // Store for cleanup
        this._resizeObserver = resizeObserver;
    },

    /**
     * Initialize time range selector
     */
    initTimeSelector() {
        const buttons = document.querySelectorAll('.time-btn');
        buttons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                buttons.forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this.loadChartData(e.target.dataset.range);
            });
        });
    },

    /**
     * Initialize activity feed with mock data
     */
    initActivityFeed() {
        // Subscribe to trade events
        const unsubTrades = store.subscribe('trades', (trades) => {
            this.renderActivityFeed(trades);
        });
        this.unsubscribers.push(unsubTrades);
    },

    /**
     * Subscribe to store updates
     */
    subscribeToUpdates() {
        // Portfolio updates
        const unsubPortfolio = store.subscribe('portfolio', (portfolio) => {
            if (portfolio) {
                this.updateChartFooter(portfolio);
                this.updateMetrics(portfolio);
            }
        });

        // Performance updates
        const unsubPerf = store.subscribe('performance', (perf) => {
            if (perf) {
                this.updateMetrics(perf);
            }
        });

        this.unsubscribers.push(unsubPortfolio, unsubPerf);
    },

    /**
     * Load all homepage data
     */
    async loadData() {
        try {
            const [portfolio, performance, trades, history] = await Promise.all([
                api.getPortfolio(),
                api.getPerformance(),
                api.getTrades(20),
                api.getPortfolioHistory('7D')
            ]);

            // Update store
            if (portfolio) {
                store.update({
                    portfolio,
                    totalValue: portfolio.total_value,
                    totalPnL: portfolio.total_pnl,
                    pnlPercent: portfolio.pnl_percent
                });
            }

            if (performance) {
                store.set('performance', performance);
                this.updateMetrics(performance);
            }

            if (trades?.trades) {
                store.set('trades', trades.trades);
                this.renderActivityFeed(trades.trades);
            }

            if (history) {
                this.renderChartData(history);
            }

        } catch (error) {
            console.error('Failed to load homepage data:', error);
        }
    },

    /**
     * Load chart data for specific time range
     */
    async loadChartData(range) {
        try {
            const history = await api.getPortfolioHistory(range);
            if (history) {
                this.renderChartData(history);
            }
        } catch (error) {
            console.error('Failed to load chart data:', error);
        }
    },

    /**
     * Render chart with data
     */
    renderChartData(history) {
        if (!this.areaSeries || !history?.snapshots) return;

        // Transform to chart format
        const data = history.snapshots.map(snap => ({
            time: Math.floor(new Date(snap.timestamp).getTime() / 1000),
            value: snap.total_value || 0
        })).sort((a, b) => a.time - b.time);

        if (data.length > 0) {
            this.areaSeries.setData(data);
            this.chart.timeScale().fitContent();

            // Update stats
            const latest = data[data.length - 1]?.value || 0;
            const first = data[0]?.value || 0;
            const change = latest - first;
            const high = Math.max(...data.map(d => d.value));
            const low = Math.min(...data.map(d => d.value));

            this.updateElement('chart-current', formatCurrency(latest));
            this.updateElement('chart-change', formatCurrency(change), change >= 0 ? 'profit' : 'loss');
            this.updateElement('chart-high', formatCurrency(high));
            this.updateElement('chart-low', formatCurrency(low));
        }
    },

    /**
     * Render activity feed
     */
    renderActivityFeed(trades) {
        const feed = document.getElementById('activity-feed');
        const countEl = document.getElementById('activity-count');
        if (!feed) return;

        if (!trades || trades.length === 0) {
            feed.innerHTML = `
                <div class="activity-empty">
                    <i data-lucide="inbox"></i>
                    <span>No recent activity</span>
                </div>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        const items = trades.slice(0, 50).map((trade, index) => {
            const actionClass = this.getActionClass(trade.action);
            const time = formatTimeAgo(trade.timestamp || trade.created_at);
            const pair = trade.pair || trade.symbol || 'UNKNOWN';
            const reasoning = trade.reasoning || trade.signal_reason || 'No reasoning provided';

            return `
                <div class="activity-item ${actionClass}" style="animation-delay: ${index * 50}ms">
                    <div class="activity-marker"></div>
                    <div class="activity-content">
                        <div class="activity-header">
                            <span class="activity-action font-display">${escapeHTML(trade.action || 'HOLD')}</span>
                            <span class="activity-pair font-mono">${escapeHTML(pair)}</span>
                            <span class="activity-time">${time}</span>
                        </div>
                        <div class="activity-details">
                            <span class="activity-agent">${escapeHTML(trade.agent || 'Sentinel')}</span>
                            ${trade.price ? `<span class="activity-price font-mono">@ ${formatCurrency(trade.price)}</span>` : ''}
                            ${trade.pnl !== undefined ? `<span class="activity-pnl font-mono ${trade.pnl >= 0 ? 'profit' : 'loss'}">${formatCurrency(trade.pnl)}</span>` : ''}
                        </div>
                        <div class="activity-reasoning">${escapeHTML(reasoning.substring(0, 100))}${reasoning.length > 100 ? '...' : ''}</div>
                    </div>
                    <div class="activity-scanline"></div>
                </div>
            `;
        }).join('');

        feed.innerHTML = items;
        if (countEl) countEl.textContent = `${trades.length} events`;
        if (window.lucide) lucide.createIcons();
    },

    /**
     * Update metrics display
     */
    updateMetrics(data) {
        // Win Rate
        const winRate = data.win_rate ?? data.winRate ?? 0;
        this.updateElement('metric-winrate', `${(winRate * 100).toFixed(1)}%`);
        this.updateBar('bar-winrate', winRate * 100);

        // Total Trades
        const totalTrades = data.total_trades ?? data.totalTrades ?? 0;
        this.updateElement('metric-trades', totalTrades.toString());
        this.updateBar('bar-trades', Math.min(100, totalTrades / 2));

        // Profit Factor
        const profitFactor = data.profit_factor ?? data.profitFactor ?? 0;
        this.updateElement('metric-profitfactor', profitFactor.toFixed(2));
        this.updateBar('bar-profitfactor', Math.min(100, profitFactor * 25));

        // Max Drawdown
        const maxDrawdown = data.max_drawdown ?? data.maxDrawdown ?? 0;
        this.updateElement('metric-drawdown', `${(Math.abs(maxDrawdown) * 100).toFixed(1)}%`);
        this.updateBar('bar-drawdown', Math.abs(maxDrawdown) * 100);

        // Exposure
        const exposure = data.total_exposure ?? data.exposure ?? 0;
        this.updateElement('metric-exposure', `${(exposure * 100).toFixed(1)}%`);
        this.updateBar('bar-exposure', exposure * 100);

        // Sharpe Ratio
        const sharpe = data.sharpe_ratio ?? data.sharpeRatio ?? 0;
        this.updateElement('metric-sharpe', sharpe.toFixed(2));
        this.updateBar('bar-sharpe', Math.min(100, Math.max(0, (sharpe + 1) * 25)));
    },

    /**
     * Update chart footer stats
     */
    updateChartFooter(portfolio) {
        if (!portfolio) return;

        this.updateElement('chart-current', formatCurrency(portfolio.total_value));

        const pnl = portfolio.total_pnl || 0;
        this.updateElement('chart-change', formatCurrency(pnl), pnl >= 0 ? 'profit' : 'loss');
    },

    /**
     * Helper: Update element text
     */
    updateElement(id, value, addClass = null) {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = value;
            if (addClass) {
                el.className = el.className.replace(/profit|loss|neutral/g, '').trim();
                el.classList.add(addClass);
            }
        }
    },

    /**
     * Helper: Update progress bar
     */
    updateBar(id, percent) {
        const el = document.getElementById(id);
        if (el) {
            el.style.width = `${Math.min(100, Math.max(0, percent))}%`;
        }
    },

    /**
     * Helper: Get action CSS class
     */
    getActionClass(action) {
        switch (action?.toUpperCase()) {
            case 'BUY': return 'action-buy';
            case 'SELL': return 'action-sell';
            case 'HOLD': return 'action-hold';
            case 'REJECT':
            case 'REJECTED': return 'action-reject';
            default: return 'action-hold';
        }
    },

    /**
     * Cleanup on page destroy
     */
    destroy() {
        // Clear interval
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }

        // Unsubscribe from store
        this.unsubscribers.forEach(unsub => unsub());
        this.unsubscribers = [];

        // Cleanup chart
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
        }
        if (this.chart) {
            this.chart.remove();
            this.chart = null;
            this.areaSeries = null;
        }
    }
};

export default HomePage;
