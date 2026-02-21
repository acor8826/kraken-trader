/**
 * Cost Optimization Page - Kraken Trading Dashboard
 * Configure cost-saving options and view projected savings
 */

import store from '../store.js';
import api from '../api.js';
import { formatCurrency, formatPercent, formatNumber, setHTML, escapeHTML, showToast } from '../utils.js';

// ========================================
// Cost Optimization Page Module
// ========================================

const CostsPage = {
    name: 'costs',
    refreshInterval: null,
    config: {},

    /**
     * Cost optimization options
     */
    optimizationOptions: [
        {
            id: 'batch_analysis',
            name: 'Batch Analysis',
            description: 'Analyze multiple trading pairs in a single LLM call instead of individual calls. Reduces API costs by ~40%.',
            icon: 'layers',
            default: false,
            savings: 0.40,
            tradeoff: 'Slightly less granular analysis per pair'
        },
        {
            id: 'hybrid_mode',
            name: 'Hybrid Mode',
            description: 'Use rule-based decisions for clear signals, reserving LLM for ambiguous situations. Saves ~30% on API costs.',
            icon: 'git-branch',
            default: false,
            savings: 0.30,
            tradeoff: 'May miss nuanced opportunities'
        },
        {
            id: 'adaptive_scheduling',
            name: 'Adaptive Scheduling',
            description: 'Adjust analysis frequency based on market volatility. More frequent during high volatility, less during calm periods.',
            icon: 'clock',
            default: true,
            savings: 0.20,
            tradeoff: 'May react slower in sudden volatility'
        },
        {
            id: 'model_tiering',
            name: 'Model Tiering',
            description: 'Use smaller, faster models for initial screening and larger models only for final decisions.',
            icon: 'layers-3',
            default: false,
            savings: 0.50,
            tradeoff: 'Initial analysis may be less sophisticated'
        },
        {
            id: 'cache_analysis',
            name: 'Cache Analysis',
            description: 'Cache and reuse recent analysis for similar market conditions. Reduces redundant API calls.',
            icon: 'database',
            default: true,
            savings: 0.15,
            tradeoff: 'Cached analysis may become stale'
        },
        {
            id: 'smart_triggers',
            name: 'Smart Triggers',
            description: 'Only trigger full analysis when price moves exceed threshold, instead of fixed intervals.',
            icon: 'zap',
            default: false,
            savings: 0.25,
            tradeoff: 'May miss gradual trend changes'
        }
    ],

    /**
     * Render the costs page
     */
    async render(container) {
        const html = `
            <div class="page costs-page">
                <header class="page-header">
                    <div class="page-title-group">
                        <h1 class="page-title font-display">
                            <i data-lucide="piggy-bank"></i>
                            COST OPTIMIZATION
                        </h1>
                        <p class="page-subtitle">Configure cost-saving options and view projected savings</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-primary" id="save-config">
                            <i data-lucide="save"></i>
                            Save Changes
                        </button>
                    </div>
                </header>

                <!-- Cost Summary Cards -->
                <section class="cost-summary">
                    <div class="cost-card current">
                        <div class="cost-icon">
                            <i data-lucide="receipt"></i>
                        </div>
                        <div class="cost-info">
                            <span class="cost-label font-display">CURRENT MONTHLY</span>
                            <span class="cost-value font-mono" id="cost-current">$0.00</span>
                        </div>
                    </div>

                    <div class="cost-card projected">
                        <div class="cost-icon">
                            <i data-lucide="trending-down"></i>
                        </div>
                        <div class="cost-info">
                            <span class="cost-label font-display">PROJECTED MONTHLY</span>
                            <span class="cost-value font-mono" id="cost-projected">$0.00</span>
                        </div>
                    </div>

                    <div class="cost-card savings">
                        <div class="cost-icon">
                            <i data-lucide="badge-dollar-sign"></i>
                        </div>
                        <div class="cost-info">
                            <span class="cost-label font-display">MONTHLY SAVINGS</span>
                            <span class="cost-value font-mono profit" id="cost-savings">$0.00</span>
                        </div>
                    </div>

                    <div class="cost-card percent">
                        <div class="cost-icon">
                            <i data-lucide="percent"></i>
                        </div>
                        <div class="cost-info">
                            <span class="cost-label font-display">REDUCTION</span>
                            <span class="cost-value font-mono" id="cost-reduction">0%</span>
                        </div>
                    </div>
                </section>

                <!-- Optimization Options -->
                <section class="optimization-section">
                    <h2 class="section-title font-display">
                        <i data-lucide="sliders"></i>
                        OPTIMIZATION OPTIONS
                    </h2>
                    <div class="optimization-grid" id="optimization-grid">
                        ${this.renderOptimizationOptions()}
                    </div>
                </section>

                <!-- Cost Comparison Chart -->
                <section class="comparison-section">
                    <h2 class="section-title font-display">
                        <i data-lucide="bar-chart-3"></i>
                        COST COMPARISON
                    </h2>
                    <div class="comparison-container">
                        <div class="comparison-chart" id="comparison-chart">
                            <div class="chart-bar baseline">
                                <div class="bar-fill" id="bar-baseline" style="height: 100%"></div>
                                <span class="bar-label">Baseline</span>
                                <span class="bar-value font-mono" id="val-baseline">$0</span>
                            </div>
                            <div class="chart-bar optimized">
                                <div class="bar-fill" id="bar-optimized" style="height: 50%"></div>
                                <span class="bar-label">Optimized</span>
                                <span class="bar-value font-mono" id="val-optimized">$0</span>
                            </div>
                        </div>
                        <div class="comparison-breakdown">
                            <h3>Cost Breakdown</h3>
                            <div class="breakdown-list" id="cost-breakdown">
                                <div class="breakdown-item">
                                    <span class="breakdown-label">Input Tokens</span>
                                    <span class="breakdown-value font-mono" id="bd-input">$0.00</span>
                                </div>
                                <div class="breakdown-item">
                                    <span class="breakdown-label">Output Tokens</span>
                                    <span class="breakdown-value font-mono" id="bd-output">$0.00</span>
                                </div>
                                <div class="breakdown-item">
                                    <span class="breakdown-label">API Calls</span>
                                    <span class="breakdown-value font-mono" id="bd-calls">0</span>
                                </div>
                                <div class="breakdown-item total">
                                    <span class="breakdown-label">Total</span>
                                    <span class="breakdown-value font-mono" id="bd-total">$0.00</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </section>

                <!-- Usage Allocation (Future Billing) -->
                <section class="allocation-section">
                    <h2 class="section-title font-display">
                        <i data-lucide="users"></i>
                        USAGE ALLOCATION
                    </h2>
                    <div class="allocation-info">
                        <div class="allocation-card">
                            <div class="allocation-header">
                                <i data-lucide="info"></i>
                                <h3>Token Usage Tracking</h3>
                            </div>
                            <p>Token usage is being tracked for future per-user billing. Each API call's token consumption is logged and can be allocated to individual user accounts.</p>
                            <div class="allocation-stats">
                                <div class="stat">
                                    <span class="stat-label">Total Tokens Used</span>
                                    <span class="stat-value font-mono" id="alloc-total-tokens">0</span>
                                </div>
                                <div class="stat">
                                    <span class="stat-label">Sessions Tracked</span>
                                    <span class="stat-value font-mono" id="alloc-sessions">0</span>
                                </div>
                                <div class="stat">
                                    <span class="stat-label">Avg Per Session</span>
                                    <span class="stat-value font-mono" id="alloc-avg">0</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </section>
            </div>
        `;

        setHTML(container, html);

        // Setup event listeners
        this.initToggles();
        document.getElementById('save-config')?.addEventListener('click', () => this.saveConfig());

        // Load data
        await this.loadData();

        return this;
    },

    /**
     * Render optimization options
     */
    renderOptimizationOptions() {
        return this.optimizationOptions.map(opt => `
            <div class="optimization-card" data-option="${opt.id}">
                <div class="opt-header">
                    <div class="opt-icon">
                        <i data-lucide="${opt.icon}"></i>
                    </div>
                    <label class="opt-toggle">
                        <input type="checkbox" id="opt-${opt.id}" ${opt.default ? 'checked' : ''}>
                        <span class="toggle-slider"></span>
                    </label>
                </div>
                <div class="opt-content">
                    <h3 class="opt-name">${escapeHTML(opt.name)}</h3>
                    <p class="opt-description">${escapeHTML(opt.description)}</p>
                    <div class="opt-meta">
                        <span class="opt-savings profit">
                            <i data-lucide="arrow-down"></i>
                            ~${(opt.savings * 100).toFixed(0)}% savings
                        </span>
                        <span class="opt-tradeoff">
                            <i data-lucide="alert-circle"></i>
                            ${escapeHTML(opt.tradeoff)}
                        </span>
                    </div>
                </div>
            </div>
        `).join('');
    },

    /**
     * Initialize toggle switches
     */
    initToggles() {
        this.optimizationOptions.forEach(opt => {
            const toggle = document.getElementById(`opt-${opt.id}`);
            if (toggle) {
                toggle.addEventListener('change', () => {
                    this.config[opt.id] = toggle.checked;
                    this.calculateProjectedCosts();
                });
                // Initialize config
                this.config[opt.id] = toggle.checked;
            }
        });
    },

    /**
     * Load cost data
     */
    async loadData() {
        try {
            const [costs, usage, config] = await Promise.all([
                api.getCostStats(),
                api.getCostsUsage(),
                api.getCostConfig().catch(() => null)
            ]);

            // Apply saved config if available
            if (config?.optimizations) {
                Object.entries(config.optimizations).forEach(([key, value]) => {
                    this.config[key] = value;
                    const toggle = document.getElementById(`opt-${key}`);
                    if (toggle) toggle.checked = value;
                });
            }

            this.updateCostDisplay(costs, usage);
        } catch (error) {
            console.error('Failed to load cost data:', error);
        }
    },

    /**
     * Update cost display
     */
    updateCostDisplay(costs, usage) {
        const currentMonthly = costs?.monthly_cost || usage?.monthly_total || 50; // Default estimate
        const breakdown = usage?.breakdown || {};

        // Update current costs
        document.getElementById('cost-current').textContent = formatCurrency(currentMonthly);
        document.getElementById('val-baseline').textContent = formatCurrency(currentMonthly);
        document.getElementById('bar-baseline').style.height = '100%';

        // Update breakdown
        document.getElementById('bd-input').textContent = formatCurrency(breakdown.input_cost || currentMonthly * 0.6);
        document.getElementById('bd-output').textContent = formatCurrency(breakdown.output_cost || currentMonthly * 0.4);
        document.getElementById('bd-calls').textContent = formatNumber(breakdown.api_calls || 1000, 0);
        document.getElementById('bd-total').textContent = formatCurrency(currentMonthly);

        // Update allocation stats
        const totalTokens = (usage?.total_tokens || 0);
        const sessions = usage?.sessions || 0;
        document.getElementById('alloc-total-tokens').textContent = formatNumber(totalTokens, 0);
        document.getElementById('alloc-sessions').textContent = formatNumber(sessions, 0);
        document.getElementById('alloc-avg').textContent = sessions > 0 ? formatNumber(totalTokens / sessions, 0) : '0';

        // Calculate projected
        this.calculateProjectedCosts(currentMonthly);
    },

    /**
     * Calculate projected costs based on enabled optimizations
     */
    calculateProjectedCosts(currentMonthly = null) {
        if (!currentMonthly) {
            const currentEl = document.getElementById('cost-current');
            currentMonthly = parseFloat(currentEl?.textContent?.replace(/[^0-9.-]/g, '')) || 50;
        }

        // Calculate total savings from enabled options
        let totalSavings = 0;
        this.optimizationOptions.forEach(opt => {
            if (this.config[opt.id]) {
                totalSavings += opt.savings;
            }
        });

        // Cap at 70% max savings (can't eliminate all costs)
        totalSavings = Math.min(totalSavings, 0.70);

        const projected = currentMonthly * (1 - totalSavings);
        const savings = currentMonthly - projected;

        // Update UI
        document.getElementById('cost-projected').textContent = formatCurrency(projected);
        document.getElementById('cost-savings').textContent = formatCurrency(savings);
        document.getElementById('cost-reduction').textContent = formatPercent(totalSavings);

        // Update chart
        document.getElementById('val-optimized').textContent = formatCurrency(projected);
        document.getElementById('bar-optimized').style.height = `${(projected / currentMonthly) * 100}%`;
    },

    /**
     * Save configuration
     */
    async saveConfig() {
        try {
            await api.updateSettings('cost_optimization', this.config);
            showToast('Cost optimization settings saved', 'success');
        } catch (error) {
            console.error('Failed to save config:', error);
            showToast('Failed to save settings', 'error');
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
    }
};

export default CostsPage;
