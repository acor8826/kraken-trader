/**
 * P&L Breakdown Page - Kraken Trading Dashboard
 * Xero-style financial breakdown with cost efficiency metrics
 */

import store from '../store.js';
import api from '../api.js';
import { formatCurrency, formatPercent, formatNumber, setHTML, escapeHTML, getPnLClass } from '../utils.js';

// ========================================
// P&L Breakdown Page Module
// ========================================

const PnLPage = {
    name: 'pnl',
    refreshInterval: null,
    unsubscribers: [],

    /**
     * Render the P&L page
     */
    async render(container) {
        const html = `
            <div class="page pnl-page">
                <header class="page-header">
                    <div class="page-title-group">
                        <h1 class="page-title font-display">
                            <i data-lucide="trending-up"></i>
                            P&L BREAKDOWN
                        </h1>
                        <p class="page-subtitle">Detailed profit and loss analysis with cost efficiency</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-secondary" id="refresh-pnl">
                            <i data-lucide="refresh-cw"></i>
                            Refresh
                        </button>
                        <button class="btn btn-primary" id="export-pnl">
                            <i data-lucide="download"></i>
                            Export
                        </button>
                    </div>
                </header>

                <!-- Hero Net Profit Card -->
                <section class="pnl-hero">
                    <div class="hero-card net-profit-card">
                        <div class="hero-glow"></div>
                        <div class="hero-label font-display">NET PROFIT</div>
                        <div class="hero-value font-mono" id="hero-net-profit">$0.00</div>
                        <div class="hero-subtext" id="hero-pnl-change">
                            <span class="change-value">+$0.00</span>
                            <span class="change-period">from starting capital</span>
                        </div>
                    </div>
                </section>

                <!-- P&L Summary Cards -->
                <section class="pnl-summary">
                    <div class="summary-card realized">
                        <div class="card-icon">
                            <i data-lucide="check-circle-2"></i>
                        </div>
                        <div class="card-content">
                            <span class="card-label font-display">REALIZED P&L</span>
                            <span class="card-value font-mono" id="pnl-realized">$0.00</span>
                            <span class="card-meta">Closed positions</span>
                        </div>
                    </div>

                    <div class="summary-card unrealized">
                        <div class="card-icon">
                            <i data-lucide="clock"></i>
                        </div>
                        <div class="card-content">
                            <span class="card-label font-display">UNREALIZED P&L</span>
                            <span class="card-value font-mono" id="pnl-unrealized">$0.00</span>
                            <span class="card-meta">Open positions</span>
                        </div>
                    </div>

                    <div class="summary-card costs">
                        <div class="card-icon warning">
                            <i data-lucide="receipt"></i>
                        </div>
                        <div class="card-content">
                            <span class="card-label font-display">API COSTS</span>
                            <span class="card-value font-mono" id="pnl-costs">$0.00</span>
                            <span class="card-meta">Token usage costs</span>
                        </div>
                    </div>

                    <div class="summary-card roi">
                        <div class="card-icon success">
                            <i data-lucide="percent"></i>
                        </div>
                        <div class="card-content">
                            <span class="card-label font-display">ROI ON API</span>
                            <span class="card-value font-mono" id="pnl-roi">0x</span>
                            <span class="card-meta">Profit / API cost</span>
                        </div>
                    </div>
                </section>

                <!-- Token Usage Breakdown -->
                <section class="pnl-section">
                    <h2 class="section-title font-display">
                        <i data-lucide="coins"></i>
                        TOKEN USAGE
                    </h2>
                    <div class="token-usage-grid">
                        <div class="usage-card">
                            <div class="usage-header">
                                <span class="usage-label">Input Tokens</span>
                                <span class="usage-value font-mono" id="tokens-input">0</span>
                            </div>
                            <div class="usage-bar">
                                <div class="usage-fill input" id="tokens-input-bar" style="width: 0%"></div>
                            </div>
                            <span class="usage-cost font-mono" id="tokens-input-cost">$0.00</span>
                        </div>

                        <div class="usage-card">
                            <div class="usage-header">
                                <span class="usage-label">Output Tokens</span>
                                <span class="usage-value font-mono" id="tokens-output">0</span>
                            </div>
                            <div class="usage-bar">
                                <div class="usage-fill output" id="tokens-output-bar" style="width: 0%"></div>
                            </div>
                            <span class="usage-cost font-mono" id="tokens-output-cost">$0.00</span>
                        </div>

                        <div class="usage-card">
                            <div class="usage-header">
                                <span class="usage-label">Total Tokens</span>
                                <span class="usage-value font-mono" id="tokens-total">0</span>
                            </div>
                            <div class="usage-bar">
                                <div class="usage-fill total" id="tokens-total-bar" style="width: 0%"></div>
                            </div>
                            <span class="usage-cost font-mono" id="tokens-total-cost">$0.00</span>
                        </div>

                        <div class="usage-card highlight">
                            <div class="usage-header">
                                <span class="usage-label">Cost / Trade</span>
                                <span class="usage-value font-mono" id="cost-per-trade">$0.00</span>
                            </div>
                            <div class="usage-meta">
                                <span id="total-trades-count">0 trades</span>
                            </div>
                        </div>
                    </div>
                </section>

                <!-- Cost Efficiency Metrics -->
                <section class="pnl-section">
                    <h2 class="section-title font-display">
                        <i data-lucide="gauge"></i>
                        COST EFFICIENCY
                    </h2>
                    <div class="efficiency-grid">
                        <div class="efficiency-card">
                            <div class="efficiency-metric">
                                <span class="metric-name">Profit Factor</span>
                                <span class="metric-value font-mono" id="eff-profit-factor">0.00</span>
                            </div>
                            <div class="metric-bar">
                                <div class="metric-fill" id="eff-profit-factor-bar" style="width: 0%"></div>
                            </div>
                            <span class="metric-desc">Gross profit / gross loss</span>
                        </div>

                        <div class="efficiency-card">
                            <div class="efficiency-metric">
                                <span class="metric-name">Win Rate</span>
                                <span class="metric-value font-mono" id="eff-win-rate">0%</span>
                            </div>
                            <div class="metric-bar">
                                <div class="metric-fill" id="eff-win-rate-bar" style="width: 0%"></div>
                            </div>
                            <span class="metric-desc">Profitable trades / total</span>
                        </div>

                        <div class="efficiency-card">
                            <div class="efficiency-metric">
                                <span class="metric-name">Avg Win</span>
                                <span class="metric-value font-mono profit" id="eff-avg-win">$0.00</span>
                            </div>
                            <span class="metric-desc">Average profitable trade</span>
                        </div>

                        <div class="efficiency-card">
                            <div class="efficiency-metric">
                                <span class="metric-name">Avg Loss</span>
                                <span class="metric-value font-mono loss" id="eff-avg-loss">$0.00</span>
                            </div>
                            <span class="metric-desc">Average losing trade</span>
                        </div>

                        <div class="efficiency-card">
                            <div class="efficiency-metric">
                                <span class="metric-name">Expectancy</span>
                                <span class="metric-value font-mono" id="eff-expectancy">$0.00</span>
                            </div>
                            <span class="metric-desc">Expected profit per trade</span>
                        </div>

                        <div class="efficiency-card">
                            <div class="efficiency-metric">
                                <span class="metric-name">Net ROI</span>
                                <span class="metric-value font-mono" id="eff-net-roi">0%</span>
                            </div>
                            <span class="metric-desc">Net profit / starting capital</span>
                        </div>
                    </div>
                </section>

                <!-- P&L by Pair -->
                <section class="pnl-section">
                    <h2 class="section-title font-display">
                        <i data-lucide="bar-chart-3"></i>
                        P&L BY PAIR
                    </h2>
                    <div class="pnl-table-wrapper">
                        <table class="pnl-table">
                            <thead>
                                <tr>
                                    <th>Pair</th>
                                    <th>Trades</th>
                                    <th>Win Rate</th>
                                    <th>Realized P&L</th>
                                    <th>Unrealized P&L</th>
                                    <th>Total P&L</th>
                                </tr>
                            </thead>
                            <tbody id="pnl-by-pair">
                                <tr class="loading-row">
                                    <td colspan="6">
                                        <div class="table-loading">
                                            <div class="pulse-loader"></div>
                                            <span>Loading breakdown...</span>
                                        </div>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </section>
            </div>
        `;

        setHTML(container, html);

        // Setup event listeners
        document.getElementById('refresh-pnl')?.addEventListener('click', () => this.loadData());
        document.getElementById('export-pnl')?.addEventListener('click', () => this.exportPnL());

        // Load data
        await this.loadData();

        // Refresh every 60 seconds
        this.refreshInterval = setInterval(() => this.loadData(), 60000);

        return this;
    },

    /**
     * Load all P&L data
     */
    async loadData() {
        try {
            const data = await api.loadPnLData();
            this.updateSummary(data.summary);
            this.updateTokenUsage(data.usage);
            this.updateEfficiency(data.summary);
            this.renderPnLByPair(data.byPair);
        } catch (error) {
            console.error('Failed to load P&L data:', error);
        }
    },

    /**
     * Update summary cards
     */
    updateSummary(summary) {
        if (!summary) return;

        const netProfit = summary.net_profit || summary.total_pnl || 0;
        const realized = summary.realized_pnl || 0;
        const unrealized = summary.unrealized_pnl || 0;
        const apiCosts = summary.api_costs || summary.total_costs || 0;
        const roi = apiCosts > 0 ? (netProfit / apiCosts) : 0;

        // Hero card
        const heroEl = document.getElementById('hero-net-profit');
        if (heroEl) {
            heroEl.textContent = formatCurrency(netProfit);
            heroEl.className = `hero-value font-mono ${getPnLClass(netProfit)}`;
        }

        const changeEl = document.querySelector('#hero-pnl-change .change-value');
        if (changeEl) {
            changeEl.textContent = formatCurrency(netProfit);
            changeEl.className = `change-value ${getPnLClass(netProfit)}`;
        }

        // Summary cards
        this.updateElement('pnl-realized', formatCurrency(realized), getPnLClass(realized));
        this.updateElement('pnl-unrealized', formatCurrency(unrealized), getPnLClass(unrealized));
        this.updateElement('pnl-costs', formatCurrency(apiCosts));
        this.updateElement('pnl-roi', `${roi.toFixed(1)}x`, roi >= 1 ? 'profit' : 'loss');
    },

    /**
     * Update token usage section
     */
    updateTokenUsage(usage) {
        if (!usage) return;

        const inputTokens = usage.input_tokens || 0;
        const outputTokens = usage.output_tokens || 0;
        const totalTokens = inputTokens + outputTokens;
        const inputCost = usage.input_cost || 0;
        const outputCost = usage.output_cost || 0;
        const totalCost = usage.total_cost || (inputCost + outputCost);
        const totalTrades = usage.total_trades || 1;
        const costPerTrade = totalCost / Math.max(1, totalTrades);

        // Token counts
        this.updateElement('tokens-input', formatNumber(inputTokens, 0));
        this.updateElement('tokens-output', formatNumber(outputTokens, 0));
        this.updateElement('tokens-total', formatNumber(totalTokens, 0));

        // Token costs
        this.updateElement('tokens-input-cost', formatCurrency(inputCost));
        this.updateElement('tokens-output-cost', formatCurrency(outputCost));
        this.updateElement('tokens-total-cost', formatCurrency(totalCost));

        // Cost per trade
        this.updateElement('cost-per-trade', formatCurrency(costPerTrade));
        this.updateElement('total-trades-count', `${totalTrades} trades`);

        // Progress bars (relative to total)
        const maxTokens = totalTokens || 1;
        this.updateBar('tokens-input-bar', (inputTokens / maxTokens) * 100);
        this.updateBar('tokens-output-bar', (outputTokens / maxTokens) * 100);
        this.updateBar('tokens-total-bar', 100);
    },

    /**
     * Update efficiency metrics
     */
    updateEfficiency(summary) {
        if (!summary) return;

        const profitFactor = summary.profit_factor || 0;
        const winRate = summary.win_rate || 0;
        const avgWin = summary.avg_win || 0;
        const avgLoss = summary.avg_loss || 0;
        const expectancy = summary.expectancy || 0;
        const netRoi = summary.roi_percent || summary.pnl_percent || 0;

        this.updateElement('eff-profit-factor', profitFactor.toFixed(2));
        this.updateElement('eff-win-rate', `${(winRate * 100).toFixed(1)}%`);
        this.updateElement('eff-avg-win', formatCurrency(avgWin));
        this.updateElement('eff-avg-loss', formatCurrency(Math.abs(avgLoss)));
        this.updateElement('eff-expectancy', formatCurrency(expectancy), getPnLClass(expectancy));
        this.updateElement('eff-net-roi', formatPercent(netRoi), getPnLClass(netRoi));

        // Progress bars
        this.updateBar('eff-profit-factor-bar', Math.min(100, profitFactor * 25));
        this.updateBar('eff-win-rate-bar', winRate * 100);
    },

    /**
     * Render P&L by pair table
     */
    renderPnLByPair(byPair) {
        const tbody = document.getElementById('pnl-by-pair');
        if (!tbody) return;

        const data = byPair?.pairs || byPair || [];

        if (!data || data.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="6">
                        <div class="table-empty">
                            <i data-lucide="inbox"></i>
                            <span>No P&L data available</span>
                        </div>
                    </td>
                </tr>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        const rows = data.map(item => {
            const pair = item.pair || item.symbol || 'UNKNOWN';
            const trades = item.trades || item.trade_count || 0;
            const winRate = item.win_rate || 0;
            const realized = item.realized_pnl || 0;
            const unrealized = item.unrealized_pnl || 0;
            const total = item.total_pnl || (realized + unrealized);

            return `
                <tr>
                    <td class="font-mono">${escapeHTML(pair)}</td>
                    <td>${trades}</td>
                    <td>${formatPercent(winRate)}</td>
                    <td class="font-mono ${getPnLClass(realized)}">${formatCurrency(realized)}</td>
                    <td class="font-mono ${getPnLClass(unrealized)}">${formatCurrency(unrealized)}</td>
                    <td class="font-mono ${getPnLClass(total)}"><strong>${formatCurrency(total)}</strong></td>
                </tr>
            `;
        }).join('');

        tbody.innerHTML = rows;
    },

    /**
     * Export P&L data
     */
    async exportPnL() {
        try {
            const data = await api.exportAnalytics();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `pnl-export-${new Date().toISOString().split('T')[0]}.json`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error('Failed to export P&L:', error);
        }
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
     * Cleanup on page destroy
     */
    destroy() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
        this.unsubscribers.forEach(unsub => unsub());
        this.unsubscribers = [];
    }
};

export default PnLPage;
