/**
 * Agents Page - Kraken Trading Dashboard
 * Agent cards grid showing all trading agents
 */

import store from '../store.js';
import api from '../api.js';
import router from '../router.js';
import { formatPercent, setHTML, escapeHTML } from '../utils.js';

// ========================================
// Agents Page Module
// ========================================

const AgentsPage = {
    name: 'agents',
    refreshInterval: null,

    /**
     * Render the agents page
     */
    async render(container) {
        const html = `
            <div class="page agents-page">
                <header class="page-header">
                    <div class="page-title-group">
                        <h1 class="page-title font-display">
                            <i data-lucide="brain"></i>
                            AGENTS
                        </h1>
                        <p class="page-subtitle">AI agents powering trading decisions</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-secondary" id="refresh-agents">
                            <i data-lucide="refresh-cw"></i>
                            Refresh
                        </button>
                    </div>
                </header>

                <!-- Agent Categories -->
                <div class="agent-categories">
                    <button class="category-btn active" data-category="all">All Agents</button>
                    <button class="category-btn" data-category="analyst">Analysts</button>
                    <button class="category-btn" data-category="strategist">Strategists</button>
                    <button class="category-btn" data-category="sentinel">Risk</button>
                </div>

                <!-- Agents Grid -->
                <div class="agents-grid" id="agents-grid">
                    <div class="agents-loading">
                        <div class="pulse-loader"></div>
                        <span>Loading agents...</span>
                    </div>
                </div>
            </div>
        `;

        setHTML(container, html);

        // Setup event listeners
        this.initCategories();
        document.getElementById('refresh-agents')?.addEventListener('click', () => this.loadAgents());

        // Load data
        await this.loadAgents();

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
                this.filterAgents(btn.dataset.category);
            });
        });
    },

    /**
     * Filter agents by category
     */
    filterAgents(category) {
        const cards = document.querySelectorAll('.agent-card');
        cards.forEach(card => {
            if (category === 'all' || card.dataset.type === category) {
                card.style.display = '';
            } else {
                card.style.display = 'none';
            }
        });
    },

    /**
     * Load agents data
     */
    async loadAgents() {
        try {
            const data = await api.getAgents();
            const agents = data?.agents || data || this.getDefaultAgents();
            this.renderAgents(agents);
        } catch (error) {
            console.error('Failed to load agents:', error);
            // Render default agents if API fails
            this.renderAgents(this.getDefaultAgents());
        }
    },

    /**
     * Get default agents (fallback)
     */
    getDefaultAgents() {
        return [
            {
                name: 'technical',
                display_name: 'Technical Analyst',
                type: 'analyst',
                description: 'Analyzes price action using SMA crossovers and RSI indicators to identify trend direction and momentum.',
                weight: 0.45,
                accuracy: 0.72,
                stage: 1,
                active: true,
                icon: 'candlestick-chart'
            },
            {
                name: 'sentiment',
                display_name: 'Sentiment Analyst',
                type: 'analyst',
                description: 'Monitors Fear & Greed Index and crypto news headlines for market sentiment signals with contrarian logic.',
                weight: 0.35,
                accuracy: 0.68,
                stage: 2,
                active: true,
                icon: 'heart-pulse'
            },
            {
                name: 'onchain',
                display_name: 'On-Chain Analyst',
                type: 'analyst',
                description: 'Analyzes blockchain metrics including exchange flows, active addresses, and whale activity.',
                weight: 0.20,
                accuracy: 0.65,
                stage: 3,
                active: false,
                icon: 'link'
            },
            {
                name: 'macro',
                display_name: 'Macro Analyst',
                type: 'analyst',
                description: 'Evaluates macroeconomic factors like DXY, interest rates, and global M2 money supply.',
                weight: 0.15,
                accuracy: 0.60,
                stage: 3,
                active: false,
                icon: 'globe'
            },
            {
                name: 'orderbook',
                display_name: 'Order Book Analyst',
                type: 'analyst',
                description: 'Analyzes market microstructure including bid/ask imbalance and order book depth.',
                weight: 0.15,
                accuracy: 0.62,
                stage: 3,
                active: false,
                icon: 'book-open'
            },
            {
                name: 'strategist',
                display_name: 'Claude Strategist',
                type: 'strategist',
                description: 'LLM-powered decision engine that synthesizes all analyst signals into trading plans.',
                weight: 1.0,
                accuracy: 0.70,
                stage: 1,
                active: true,
                icon: 'sparkles'
            },
            {
                name: 'sentinel',
                display_name: 'Risk Sentinel',
                type: 'sentinel',
                description: 'Validates all trading decisions against risk parameters, position limits, and circuit breakers.',
                weight: 1.0,
                accuracy: 0.95,
                stage: 1,
                active: true,
                icon: 'shield'
            },
            {
                name: 'fusion',
                display_name: 'Intelligence Fusion',
                type: 'analyst',
                description: 'Combines signals from multiple analysts using weighted averaging and disagreement detection.',
                weight: 1.0,
                accuracy: 0.73,
                stage: 2,
                active: true,
                icon: 'merge'
            }
        ];
    },

    /**
     * Render agents grid
     */
    renderAgents(agents) {
        const grid = document.getElementById('agents-grid');
        if (!grid) return;

        if (!agents || agents.length === 0) {
            grid.innerHTML = `
                <div class="agents-empty">
                    <i data-lucide="inbox"></i>
                    <h3>No Agents Found</h3>
                    <p>Agent configuration not available</p>
                </div>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        const cardsHtml = agents.map((agent, index) => this.renderAgentCard(agent, index)).join('');
        grid.innerHTML = cardsHtml;
        if (window.lucide) lucide.createIcons();

        // Add click handlers
        grid.querySelectorAll('.agent-card').forEach(card => {
            card.addEventListener('click', () => {
                const name = card.dataset.agent;
                if (name) {
                    router.navigate(`/agents/${name}`);
                }
            });
        });
    },

    /**
     * Render individual agent card
     */
    renderAgentCard(agent, index) {
        const name = agent.name || 'unknown';
        const displayName = agent.display_name || agent.name || 'Unknown Agent';
        const type = agent.type || 'analyst';
        const description = agent.description || 'No description available';
        const weight = agent.weight || 0;
        const accuracy = agent.accuracy || 0;
        const stage = agent.stage || 1;
        const active = agent.active !== false;
        const icon = agent.icon || 'cpu';

        const typeClass = `type-${type}`;
        const activeClass = active ? 'active' : 'inactive';

        return `
            <div class="agent-card ${typeClass} ${activeClass}"
                 data-agent="${escapeHTML(name)}"
                 data-type="${escapeHTML(type)}"
                 style="animation-delay: ${index * 50}ms">
                <div class="agent-card-glow"></div>

                <!-- Header -->
                <div class="agent-header">
                    <div class="agent-icon">
                        <i data-lucide="${escapeHTML(icon)}"></i>
                    </div>
                    <div class="agent-badges">
                        <span class="stage-badge">Stage ${stage}</span>
                        <span class="status-badge ${activeClass}">${active ? 'ACTIVE' : 'INACTIVE'}</span>
                    </div>
                </div>

                <!-- Info -->
                <div class="agent-info">
                    <h3 class="agent-name font-display">${escapeHTML(displayName)}</h3>
                    <span class="agent-type">${escapeHTML(type.charAt(0).toUpperCase() + type.slice(1))}</span>
                    <p class="agent-description">${escapeHTML(description)}</p>
                </div>

                <!-- Metrics -->
                <div class="agent-metrics">
                    <div class="metric">
                        <span class="metric-label">Weight</span>
                        <div class="metric-bar-wrap">
                            <div class="metric-bar">
                                <div class="metric-fill" style="width: ${weight * 100}%"></div>
                            </div>
                            <span class="metric-value font-mono">${(weight * 100).toFixed(0)}%</span>
                        </div>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Accuracy</span>
                        <div class="metric-bar-wrap">
                            <div class="metric-bar accuracy">
                                <div class="metric-fill" style="width: ${accuracy * 100}%"></div>
                            </div>
                            <span class="metric-value font-mono">${(accuracy * 100).toFixed(0)}%</span>
                        </div>
                    </div>
                </div>

                <!-- Action -->
                <div class="agent-action">
                    <span class="view-details">View Details <i data-lucide="chevron-right"></i></span>
                </div>
            </div>
        `;
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

export default AgentsPage;
