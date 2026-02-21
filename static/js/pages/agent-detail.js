/**
 * Agent Detail Page - Kraken Trading Dashboard
 * Individual agent view with description, prompt, and performance
 */

import store from '../store.js';
import api from '../api.js';
import router from '../router.js';
import { formatPercent, formatNumber, formatTimeAgo, setHTML, escapeHTML } from '../utils.js';

// ========================================
// Agent Detail Page Module
// ========================================

const AgentDetailPage = {
    name: 'agent-detail',
    agentName: null,
    refreshInterval: null,

    /**
     * Render the agent detail page
     */
    async render(container, params) {
        this.agentName = params?.name || 'unknown';

        const html = `
            <div class="page agent-detail-page">
                <!-- Back Navigation -->
                <nav class="page-breadcrumb">
                    <a href="#/agents" class="breadcrumb-link">
                        <i data-lucide="chevron-left"></i>
                        Agents
                    </a>
                    <span class="breadcrumb-separator">/</span>
                    <span class="breadcrumb-current font-display" id="agent-breadcrumb">${escapeHTML(this.agentName)}</span>
                </nav>

                <!-- Loading State -->
                <div class="agent-detail-loading" id="agent-loading">
                    <div class="pulse-loader"></div>
                    <span>Loading agent details...</span>
                </div>

                <!-- Agent Content (hidden initially) -->
                <div class="agent-detail-content" id="agent-content" style="display: none;">
                    <!-- Header -->
                    <header class="agent-detail-header">
                        <div class="agent-detail-icon" id="agent-icon">
                            <i data-lucide="cpu"></i>
                        </div>
                        <div class="agent-detail-info">
                            <h1 class="agent-detail-name font-display" id="agent-name">Agent</h1>
                            <div class="agent-detail-meta">
                                <span class="agent-type-badge" id="agent-type">Analyst</span>
                                <span class="agent-stage-badge" id="agent-stage">Stage 1</span>
                                <span class="agent-status-badge" id="agent-status">Active</span>
                            </div>
                        </div>
                        <div class="agent-detail-actions">
                            <button class="btn btn-secondary" id="refresh-agent">
                                <i data-lucide="refresh-cw"></i>
                                Refresh
                            </button>
                        </div>
                    </header>

                    <!-- Description -->
                    <section class="agent-section">
                        <h2 class="section-title font-display">
                            <i data-lucide="info"></i>
                            DESCRIPTION
                        </h2>
                        <div class="agent-description-box">
                            <p id="agent-description">Loading description...</p>
                        </div>
                    </section>

                    <!-- Performance Metrics -->
                    <section class="agent-section">
                        <h2 class="section-title font-display">
                            <i data-lucide="bar-chart-2"></i>
                            PERFORMANCE
                        </h2>
                        <div class="agent-stats-grid">
                            <div class="stat-card">
                                <span class="stat-label">Accuracy</span>
                                <span class="stat-value font-mono" id="stat-accuracy">0%</span>
                                <div class="stat-bar">
                                    <div class="stat-fill" id="bar-accuracy" style="width: 0%"></div>
                                </div>
                            </div>
                            <div class="stat-card">
                                <span class="stat-label">Weight</span>
                                <span class="stat-value font-mono" id="stat-weight">0%</span>
                                <div class="stat-bar">
                                    <div class="stat-fill" id="bar-weight" style="width: 0%"></div>
                                </div>
                            </div>
                            <div class="stat-card">
                                <span class="stat-label">Signals</span>
                                <span class="stat-value font-mono" id="stat-signals">0</span>
                            </div>
                            <div class="stat-card">
                                <span class="stat-label">Avg Confidence</span>
                                <span class="stat-value font-mono" id="stat-confidence">0%</span>
                            </div>
                        </div>
                    </section>

                    <!-- Prompt (for LLM agents) -->
                    <section class="agent-section" id="prompt-section" style="display: none;">
                        <h2 class="section-title font-display">
                            <i data-lucide="file-text"></i>
                            SYSTEM PROMPT
                        </h2>
                        <div class="agent-prompt-box">
                            <div class="prompt-header">
                                <span class="prompt-label">LLM System Prompt</span>
                                <button class="btn btn-sm btn-ghost" id="copy-prompt">
                                    <i data-lucide="copy"></i>
                                    Copy
                                </button>
                            </div>
                            <pre class="prompt-content font-mono" id="agent-prompt"></pre>
                        </div>
                    </section>

                    <!-- Configuration -->
                    <section class="agent-section">
                        <h2 class="section-title font-display">
                            <i data-lucide="settings"></i>
                            CONFIGURATION
                        </h2>
                        <div class="agent-config-box">
                            <pre class="config-content font-mono" id="agent-config">{}</pre>
                        </div>
                    </section>

                    <!-- Recent Signals -->
                    <section class="agent-section">
                        <h2 class="section-title font-display">
                            <i data-lucide="activity"></i>
                            RECENT SIGNALS
                        </h2>
                        <div class="signals-list" id="agent-signals">
                            <div class="signals-empty">
                                <i data-lucide="inbox"></i>
                                <span>No recent signals</span>
                            </div>
                        </div>
                    </section>
                </div>
            </div>
        `;

        setHTML(container, html);

        // Setup event listeners
        document.getElementById('refresh-agent')?.addEventListener('click', () => this.loadAgent());
        document.getElementById('copy-prompt')?.addEventListener('click', () => this.copyPrompt());

        // Load data
        await this.loadAgent();

        return this;
    },

    /**
     * Load agent details
     */
    async loadAgent() {
        try {
            const data = await api.getAgent(this.agentName);
            const agent = data?.agent || data || this.getDefaultAgent(this.agentName);
            this.renderAgent(agent);
        } catch (error) {
            console.error('Failed to load agent:', error);
            this.renderAgent(this.getDefaultAgent(this.agentName));
        }
    },

    /**
     * Get default agent data
     */
    getDefaultAgent(name) {
        const defaults = {
            technical: {
                name: 'technical',
                display_name: 'Technical Analyst',
                type: 'analyst',
                description: 'The Technical Analyst evaluates price action and chart patterns using quantitative indicators. It uses Simple Moving Average (SMA) crossovers to identify trend direction and Relative Strength Index (RSI) to gauge momentum and overbought/oversold conditions.',
                weight: 0.45,
                accuracy: 0.72,
                stage: 1,
                active: true,
                icon: 'candlestick-chart',
                signals_count: 156,
                avg_confidence: 0.75,
                config: {
                    sma_short: 20,
                    sma_long: 50,
                    rsi_period: 14,
                    rsi_overbought: 70,
                    rsi_oversold: 30
                }
            },
            sentiment: {
                name: 'sentiment',
                display_name: 'Sentiment Analyst',
                type: 'analyst',
                description: 'The Sentiment Analyst monitors market psychology through the Fear & Greed Index and crypto news headlines. It employs contrarian logic: extreme fear signals potential buying opportunities while extreme greed suggests caution.',
                weight: 0.35,
                accuracy: 0.68,
                stage: 2,
                active: true,
                icon: 'heart-pulse',
                signals_count: 89,
                avg_confidence: 0.70,
                config: {
                    fear_greed_weight: 0.5,
                    news_weight: 0.4,
                    social_weight: 0.1,
                    extreme_fear_threshold: 25,
                    extreme_greed_threshold: 75
                }
            },
            strategist: {
                name: 'strategist',
                display_name: 'Claude Strategist',
                type: 'strategist',
                description: 'The Claude Strategist is the LLM-powered decision engine that synthesizes all analyst signals into actionable trading plans. It considers market conditions, portfolio state, risk parameters, and analyst agreement to generate trade recommendations.',
                weight: 1.0,
                accuracy: 0.70,
                stage: 1,
                active: true,
                icon: 'sparkles',
                signals_count: 200,
                avg_confidence: 0.72,
                has_prompt: true,
                prompt: `You are a cryptocurrency trading strategist for an autonomous trading agent.

OBJECTIVE: Analyze the provided market intelligence and generate a trading plan.

INPUT:
- Market Intel: Fused signals from multiple analysts with direction (-1 to +1), confidence, and reasoning
- Portfolio State: Current holdings, available capital, exposure
- Risk Parameters: Position limits, stop-loss levels, confidence thresholds

DECISION FRAMEWORK:
1. Evaluate signal strength and analyst agreement
2. Consider portfolio exposure and position sizing
3. Apply risk management rules
4. Generate BUY, SELL, or HOLD decisions with reasoning

OUTPUT FORMAT:
{
  "action": "BUY|SELL|HOLD",
  "pair": "BTC/AUD",
  "confidence": 0.75,
  "reasoning": "Clear explanation of the decision"
}

Be conservative. Only recommend trades when signals are clear and risk is acceptable.`,
                config: {
                    model: 'claude-3-sonnet',
                    temperature: 0.1,
                    min_confidence: 0.70
                }
            },
            sentinel: {
                name: 'sentinel',
                display_name: 'Risk Sentinel',
                type: 'sentinel',
                description: 'The Risk Sentinel is the guardian of portfolio safety. It validates all trading decisions against predefined risk parameters, enforces position limits, manages stop-losses, and triggers circuit breakers when necessary.',
                weight: 1.0,
                accuracy: 0.95,
                stage: 1,
                active: true,
                icon: 'shield',
                signals_count: 250,
                avg_confidence: 0.90,
                config: {
                    max_position_pct: 0.20,
                    max_exposure_pct: 0.80,
                    stop_loss_pct: 0.05,
                    min_confidence: 0.70,
                    max_daily_trades: 10,
                    daily_loss_limit: 0.10
                }
            },
            fusion: {
                name: 'fusion',
                display_name: 'Intelligence Fusion',
                type: 'analyst',
                description: 'The Intelligence Fusion engine combines signals from multiple analysts using weighted averaging. It detects disagreement between analysts, adjusts confidence accordingly, and identifies the current market regime.',
                weight: 1.0,
                accuracy: 0.73,
                stage: 2,
                active: true,
                icon: 'merge',
                signals_count: 150,
                avg_confidence: 0.72,
                config: {
                    analyst_weights: {
                        technical: 0.45,
                        sentiment: 0.35,
                        onchain: 0.20
                    },
                    disagreement_threshold: 0.5,
                    min_analysts: 2
                }
            }
        };

        return defaults[name] || {
            name,
            display_name: name.charAt(0).toUpperCase() + name.slice(1),
            type: 'unknown',
            description: 'Agent details not available.',
            weight: 0,
            accuracy: 0,
            stage: 0,
            active: false,
            icon: 'cpu'
        };
    },

    /**
     * Render agent details
     */
    renderAgent(agent) {
        // Hide loading, show content
        document.getElementById('agent-loading').style.display = 'none';
        document.getElementById('agent-content').style.display = 'block';

        // Update breadcrumb
        document.getElementById('agent-breadcrumb').textContent = agent.display_name || agent.name;

        // Update icon
        const iconEl = document.getElementById('agent-icon');
        if (iconEl) {
            iconEl.innerHTML = `<i data-lucide="${agent.icon || 'cpu'}"></i>`;
        }

        // Update header info
        document.getElementById('agent-name').textContent = agent.display_name || agent.name;
        document.getElementById('agent-type').textContent = agent.type?.charAt(0).toUpperCase() + agent.type?.slice(1);
        document.getElementById('agent-stage').textContent = `Stage ${agent.stage || 1}`;

        const statusEl = document.getElementById('agent-status');
        statusEl.textContent = agent.active ? 'Active' : 'Inactive';
        statusEl.className = `agent-status-badge ${agent.active ? 'active' : 'inactive'}`;

        // Update description
        document.getElementById('agent-description').textContent = agent.description || 'No description available.';

        // Update stats
        const accuracy = agent.accuracy || 0;
        const weight = agent.weight || 0;
        document.getElementById('stat-accuracy').textContent = `${(accuracy * 100).toFixed(0)}%`;
        document.getElementById('stat-weight').textContent = `${(weight * 100).toFixed(0)}%`;
        document.getElementById('stat-signals').textContent = formatNumber(agent.signals_count || 0, 0);
        document.getElementById('stat-confidence').textContent = `${((agent.avg_confidence || 0) * 100).toFixed(0)}%`;
        document.getElementById('bar-accuracy').style.width = `${accuracy * 100}%`;
        document.getElementById('bar-weight').style.width = `${weight * 100}%`;

        // Update prompt section
        const promptSection = document.getElementById('prompt-section');
        if (agent.has_prompt && agent.prompt) {
            promptSection.style.display = 'block';
            document.getElementById('agent-prompt').textContent = agent.prompt;
        } else {
            promptSection.style.display = 'none';
        }

        // Update config
        document.getElementById('agent-config').textContent = JSON.stringify(agent.config || {}, null, 2);

        // Update signals
        this.renderRecentSignals(agent.recent_signals || []);

        // Re-init icons
        if (window.lucide) lucide.createIcons();
    },

    /**
     * Render recent signals
     */
    renderRecentSignals(signals) {
        const container = document.getElementById('agent-signals');
        if (!container) return;

        if (!signals || signals.length === 0) {
            container.innerHTML = `
                <div class="signals-empty">
                    <i data-lucide="inbox"></i>
                    <span>No recent signals</span>
                </div>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        const html = signals.map(signal => `
            <div class="signal-item ${signal.direction >= 0 ? 'bullish' : 'bearish'}">
                <div class="signal-direction">
                    <i data-lucide="${signal.direction >= 0 ? 'trending-up' : 'trending-down'}"></i>
                    <span class="font-mono">${signal.direction?.toFixed(2)}</span>
                </div>
                <div class="signal-info">
                    <span class="signal-pair font-mono">${escapeHTML(signal.pair || 'N/A')}</span>
                    <span class="signal-time">${formatTimeAgo(signal.timestamp)}</span>
                </div>
                <div class="signal-confidence">
                    <span class="confidence-label">Conf:</span>
                    <span class="confidence-value font-mono">${((signal.confidence || 0) * 100).toFixed(0)}%</span>
                </div>
            </div>
        `).join('');

        container.innerHTML = html;
        if (window.lucide) lucide.createIcons();
    },

    /**
     * Copy prompt to clipboard
     */
    async copyPrompt() {
        const prompt = document.getElementById('agent-prompt')?.textContent;
        if (prompt) {
            try {
                await navigator.clipboard.writeText(prompt);
                // Show feedback
                const btn = document.getElementById('copy-prompt');
                const original = btn.innerHTML;
                btn.innerHTML = '<i data-lucide="check"></i> Copied';
                if (window.lucide) lucide.createIcons();
                setTimeout(() => {
                    btn.innerHTML = original;
                    if (window.lucide) lucide.createIcons();
                }, 2000);
            } catch (e) {
                console.error('Failed to copy:', e);
            }
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

export default AgentDetailPage;
