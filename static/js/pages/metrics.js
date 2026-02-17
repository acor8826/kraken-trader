/**
 * Metrics Page - Kraken Trading Dashboard
 * Trading metrics with explanations to help users understand what they mean
 */

import store from '../store.js';
import api from '../api.js';
import { formatCurrency, formatPercent, formatNumber, setHTML, escapeHTML, getPnLClass } from '../utils.js';

// ========================================
// Metrics Page Module
// ========================================

const MetricsPage = {
    name: 'metrics',
    refreshInterval: null,

    /**
     * Metric definitions with explanations
     */
    metricDefinitions: [
        {
            id: 'win_rate',
            name: 'Win Rate',
            icon: 'target',
            category: 'performance',
            description: 'The percentage of trades that resulted in a profit. A win rate above 50% means more trades are profitable than not.',
            formula: 'Winning Trades / Total Trades',
            goodValue: '> 50%',
            interpretation: 'Higher is better, but must be considered alongside risk/reward ratio. A 40% win rate with high reward ratio can still be profitable.'
        },
        {
            id: 'profit_factor',
            name: 'Profit Factor',
            icon: 'divide',
            category: 'performance',
            description: 'The ratio of gross profits to gross losses. A value above 1.0 means the system is profitable overall.',
            formula: 'Gross Profit / Gross Loss',
            goodValue: '> 1.5',
            interpretation: 'Values above 2.0 indicate a strong edge. Below 1.0 means losses exceed profits.'
        },
        {
            id: 'sharpe_ratio',
            name: 'Sharpe Ratio',
            icon: 'gauge',
            category: 'risk',
            description: 'Measures risk-adjusted returns. It shows how much excess return you receive for the extra volatility you endure.',
            formula: '(Return - Risk-Free Rate) / Std Deviation',
            goodValue: '> 1.0',
            interpretation: '> 1.0 is acceptable, > 2.0 is very good, > 3.0 is excellent. Negative means returns are below risk-free rate.'
        },
        {
            id: 'sortino_ratio',
            name: 'Sortino Ratio',
            icon: 'shield',
            category: 'risk',
            description: 'Similar to Sharpe but only penalizes downside volatility. Better for strategies that have volatile upside but controlled downside.',
            formula: '(Return - Risk-Free Rate) / Downside Deviation',
            goodValue: '> 1.5',
            interpretation: 'Higher is better. More useful than Sharpe when returns are asymmetric.'
        },
        {
            id: 'max_drawdown',
            name: 'Max Drawdown',
            icon: 'trending-down',
            category: 'risk',
            description: 'The largest peak-to-trough decline in portfolio value. Represents the worst-case scenario during the trading period.',
            formula: '(Peak Value - Trough Value) / Peak Value',
            goodValue: '< 20%',
            interpretation: 'Lower is better. A 50% drawdown requires a 100% gain to recover. Critical for position sizing.'
        },
        {
            id: 'calmar_ratio',
            name: 'Calmar Ratio',
            icon: 'activity',
            category: 'risk',
            description: 'Annual return divided by maximum drawdown. Measures return per unit of drawdown risk.',
            formula: 'Annual Return / Max Drawdown',
            goodValue: '> 1.0',
            interpretation: 'Higher is better. Shows how well returns compensate for the worst decline experienced.'
        },
        {
            id: 'expectancy',
            name: 'Expectancy',
            icon: 'calculator',
            category: 'performance',
            description: 'The average amount you can expect to win (or lose) per trade. Combines win rate with average win/loss sizes.',
            formula: '(Win Rate × Avg Win) - (Loss Rate × Avg Loss)',
            goodValue: '> $0',
            interpretation: 'Positive expectancy means the system is profitable on average. Critical for long-term success.'
        },
        {
            id: 'avg_trade',
            name: 'Average Trade',
            icon: 'bar-chart-2',
            category: 'performance',
            description: 'The average profit or loss per trade. Simple but effective measure of trading performance.',
            formula: 'Total P&L / Total Trades',
            goodValue: '> $0',
            interpretation: 'Should be positive and large enough to cover transaction costs with margin.'
        },
        {
            id: 'payoff_ratio',
            name: 'Payoff Ratio',
            icon: 'scale',
            category: 'performance',
            description: 'The ratio of average winning trade to average losing trade. Also known as risk/reward ratio.',
            formula: 'Average Win / Average Loss',
            goodValue: '> 1.5',
            interpretation: 'Higher means wins are larger than losses. Even with 40% win rate, 2:1 payoff is profitable.'
        },
        {
            id: 'total_exposure',
            name: 'Total Exposure',
            icon: 'pie-chart',
            category: 'position',
            description: 'Percentage of portfolio currently invested in positions. Remaining is held as reserve/cash.',
            formula: 'Position Values / Portfolio Value',
            goodValue: '20-80%',
            interpretation: 'Balance between capital utilization and having reserves for opportunities.'
        },
        {
            id: 'var_95',
            name: 'Value at Risk (95%)',
            icon: 'alert-triangle',
            category: 'risk',
            description: 'The maximum expected loss over a day with 95% confidence. Only 5% of days should exceed this loss.',
            formula: 'Historical simulation at 95th percentile',
            goodValue: '< 5%',
            interpretation: 'Used for position sizing. If VaR is 3%, expect losses up to 3% on most bad days.'
        },
        {
            id: 'trade_frequency',
            name: 'Trade Frequency',
            icon: 'clock',
            category: 'activity',
            description: 'Average number of trades per day or period. Indicates how active the trading strategy is.',
            formula: 'Total Trades / Trading Days',
            goodValue: 'Depends on strategy',
            interpretation: 'Higher frequency means more transaction costs but potentially more opportunities.'
        }
    ],

    /**
     * Render the metrics page
     */
    async render(container) {
        const html = `
            <div class="page metrics-page">
                <header class="page-header">
                    <div class="page-title-group">
                        <h1 class="page-title font-display">
                            <i data-lucide="bar-chart-3"></i>
                            METRICS
                        </h1>
                        <p class="page-subtitle">Trading metrics explained - understand what each number means</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-secondary" id="refresh-metrics">
                            <i data-lucide="refresh-cw"></i>
                            Refresh
                        </button>
                    </div>
                </header>

                <!-- Category Filters -->
                <div class="metrics-categories">
                    <button class="category-btn active" data-category="all">All Metrics</button>
                    <button class="category-btn" data-category="performance">Performance</button>
                    <button class="category-btn" data-category="risk">Risk</button>
                    <button class="category-btn" data-category="position">Position</button>
                    <button class="category-btn" data-category="activity">Activity</button>
                </div>

                <!-- Metrics Grid -->
                <div class="metrics-explained-grid" id="metrics-grid">
                    ${this.renderMetricsGrid()}
                </div>
            </div>
        `;

        setHTML(container, html);

        // Setup event listeners
        this.initCategories();
        document.getElementById('refresh-metrics')?.addEventListener('click', () => this.loadMetrics());

        // Load actual values
        await this.loadMetrics();

        return this;
    },

    /**
     * Initialize category filters
     */
    initCategories() {
        const btns = document.querySelectorAll('.category-btn');
        btns.forEach(btn => {
            btn.addEventListener('click', () => {
                btns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.filterMetrics(btn.dataset.category);
            });
        });
    },

    /**
     * Filter metrics by category
     */
    filterMetrics(category) {
        const cards = document.querySelectorAll('.metric-explained-card');
        cards.forEach(card => {
            if (category === 'all' || card.dataset.category === category) {
                card.style.display = '';
            } else {
                card.style.display = 'none';
            }
        });
    },

    /**
     * Render metrics grid
     */
    renderMetricsGrid() {
        return this.metricDefinitions.map((metric, index) => `
            <div class="metric-explained-card" data-metric="${metric.id}" data-category="${metric.category}" style="animation-delay: ${index * 30}ms">
                <div class="metric-card-glow"></div>

                <!-- Header -->
                <div class="metric-card-header">
                    <div class="metric-icon ${metric.category}">
                        <i data-lucide="${metric.icon}"></i>
                    </div>
                    <span class="metric-category-badge">${metric.category}</span>
                </div>

                <!-- Value -->
                <div class="metric-value-section">
                    <h3 class="metric-name font-display">${escapeHTML(metric.name)}</h3>
                    <div class="metric-current-value">
                        <span class="value font-mono" id="value-${metric.id}">--</span>
                    </div>
                </div>

                <!-- Description -->
                <div class="metric-description">
                    <p>${escapeHTML(metric.description)}</p>
                </div>

                <!-- Details (collapsed by default) -->
                <div class="metric-details">
                    <div class="detail-item">
                        <span class="detail-label">Formula:</span>
                        <span class="detail-value font-mono">${escapeHTML(metric.formula)}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">Good Value:</span>
                        <span class="detail-value">${escapeHTML(metric.goodValue)}</span>
                    </div>
                    <div class="detail-item interpretation">
                        <span class="detail-label">Interpretation:</span>
                        <p class="detail-value">${escapeHTML(metric.interpretation)}</p>
                    </div>
                </div>

                <!-- Expand Button -->
                <button class="metric-expand-btn" aria-label="Show details">
                    <i data-lucide="chevron-down"></i>
                </button>
            </div>
        `).join('');
    },

    /**
     * Load actual metric values
     */
    async loadMetrics() {
        try {
            const [performance, analytics] = await Promise.all([
                api.getPerformance(),
                api.getAnalyticsMetrics()
            ]);

            const data = { ...performance, ...analytics };
            this.updateMetricValues(data);
        } catch (error) {
            console.error('Failed to load metrics:', error);
        }

        // Setup expand buttons
        this.initExpandButtons();
    },

    /**
     * Update metric values in the UI
     */
    updateMetricValues(data) {
        if (!data) return;

        // Map API data to metric IDs
        const values = {
            win_rate: data.win_rate,
            profit_factor: data.profit_factor,
            sharpe_ratio: data.sharpe_ratio,
            sortino_ratio: data.sortino_ratio,
            max_drawdown: data.max_drawdown,
            calmar_ratio: data.calmar_ratio,
            expectancy: data.expectancy,
            avg_trade: data.avg_trade || data.average_trade,
            payoff_ratio: data.payoff_ratio || data.risk_reward_ratio,
            total_exposure: data.total_exposure || data.exposure,
            var_95: data.var_95 || data.value_at_risk,
            trade_frequency: data.trade_frequency || data.trades_per_day
        };

        Object.entries(values).forEach(([id, value]) => {
            const el = document.getElementById(`value-${id}`);
            if (el && value !== undefined && value !== null) {
                // Format based on metric type
                if (id.includes('rate') || id.includes('exposure') || id.includes('drawdown')) {
                    el.textContent = formatPercent(value);
                    el.className = `value font-mono ${getPnLClass(id.includes('drawdown') ? -value : value)}`;
                } else if (id.includes('expectancy') || id.includes('avg')) {
                    el.textContent = formatCurrency(value);
                    el.className = `value font-mono ${getPnLClass(value)}`;
                } else if (id.includes('ratio') || id.includes('factor')) {
                    el.textContent = value.toFixed(2);
                    el.className = `value font-mono ${value >= 1 ? 'profit' : 'loss'}`;
                } else {
                    el.textContent = formatNumber(value, 2);
                }
            }
        });
    },

    /**
     * Initialize expand/collapse functionality
     */
    initExpandButtons() {
        document.querySelectorAll('.metric-expand-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const card = btn.closest('.metric-explained-card');
                if (card) {
                    card.classList.toggle('expanded');
                    btn.classList.toggle('expanded');
                }
            });
        });
    },

    /**
     * Cleanup on page destroy
     */
    destroy() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }
};

export default MetricsPage;
