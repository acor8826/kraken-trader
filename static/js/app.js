/**
 * Kraken Trading Dashboard - Main Application Entry Point
 * Initializes router, connects WebSocket, loads pages
 */

import router from './router.js';
import store from './store.js';
import api from './api.js';
import wsManager from './websocket.js';
import { formatCurrency, formatPercent, formatCountdown, showToast, splitPositionValues } from './utils.js';

// ========================================
// Page Imports (lazy loaded)
// ========================================

// Page modules will be imported dynamically
const pageModules = {};

// ========================================
// Header Component
// ========================================

class Header {
    constructor() {
        this.element = document.getElementById('app-header');
        this.countdownInterval = null;
    }

    init() {
        if (!this.element) return;

        // Subscribe to store updates
        store.subscribe('totalValue', (value) => this.updateTile('portfolio', formatCurrency(value)));
        store.subscribe('availableQuote', (value) => this.updateTile('cash', formatCurrency(value)));
        store.subscribe('holdingsValue', (value) => this.updateTile('holdings', formatCurrency(value)));
        store.subscribe('memeValue', (value) => this.updateTile('meme', formatCurrency(value)));
        store.subscribe('totalPnL', (value) => this.updatePnLTile(value, store.get('pnlPercent')));
        store.subscribe('pnlPercent', (pct) => this.updatePnLTile(store.get('totalPnL'), pct));
        store.subscribe('isPaused', () => this.updateAIStatus());
        store.subscribe('schedulerRunning', () => this.updateAIStatus());
        store.subscribe('secondsUntilNext', (secs) => this.updateCountdown(secs));
        store.subscribe('wsConnected', (connected) => this.updateConnectionStatus(connected));

        // Start countdown interval
        this.startCountdownInterval();

        // Initialize hamburger menu toggle
        this.initMenuToggle();
    }

    updateTile(tileId, value) {
        const el = document.getElementById(`tile-${tileId}`);
        if (el) el.textContent = value;
    }

    updatePnLTile(pnl, pnlPct) {
        const valueEl = document.getElementById('tile-pnl');
        const pctEl = document.getElementById('tile-pnl-pct');

        if (valueEl) {
            valueEl.textContent = formatCurrency(pnl);
            valueEl.className = `tile-value ${pnl >= 0 ? 'profit' : 'loss'}`;
        }
        if (pctEl) {
            pctEl.textContent = formatPercent(pnlPct);
        }
    }

    updateTargetTile(progress) {
        const valueEl = document.getElementById('tile-target');
        const barEl = document.getElementById('tile-target-bar');

        if (valueEl) valueEl.textContent = `${Math.round(progress)}%`;
        if (barEl) barEl.style.width = `${Math.min(100, progress)}%`;
    }

    updateAIStatus() {
        const el = document.getElementById('tile-ai-status');
        if (!el) return;

        const isPaused = store.get('isPaused');
        const isRunning = store.get('schedulerRunning');

        if (isPaused) {
            el.textContent = 'PAUSED';
            el.className = 'tile-value status-paused';
        } else if (isRunning) {
            el.textContent = 'ACTIVE';
            el.className = 'tile-value status-active';
        } else {
            el.textContent = 'STOPPED';
            el.className = 'tile-value status-stopped';
        }
    }

    updateCountdown(seconds) {
        const el = document.getElementById('tile-countdown');
        if (el) el.textContent = formatCountdown(seconds);
    }

    updateConnectionStatus(connected) {
        const indicator = document.getElementById('connection-indicator');
        if (indicator) {
            indicator.className = `connection-indicator ${connected ? 'connected' : 'disconnected'}`;
            indicator.title = connected ? 'Connected (Live)' : 'Disconnected';
        }
    }

    startCountdownInterval() {
        // Update countdown every second
        this.countdownInterval = setInterval(async () => {
            try {
                const data = await api.getCurrentCycle();
                if (data) {
                    store.update({
                        secondsUntilNext: data.seconds_until_next,
                        cycleCount: data.cycle_count,
                        isPaused: data.is_paused,
                        schedulerRunning: data.scheduler_running
                    });
                }
            } catch (e) {
                // Silently fail countdown updates
            }
        }, 10000); // Every 10 seconds
    }

    initMenuToggle() {
        const menuBtn = document.getElementById('menu-toggle');
        const sidebar = document.getElementById('nav-sidebar');
        const overlay = document.getElementById('nav-overlay');

        const closeSidebar = () => {
            sidebar.classList.remove('open');
            if (overlay) overlay.classList.remove('visible');
            store.set('sidebarOpen', false);
        };

        if (menuBtn && sidebar) {
            menuBtn.addEventListener('click', () => {
                const isOpen = sidebar.classList.toggle('open');
                if (overlay) overlay.classList.toggle('visible', isOpen);
                store.set('sidebarOpen', isOpen);
            });

            // Close on overlay click
            if (overlay) {
                overlay.addEventListener('click', closeSidebar);
            }

            // Close on outside click
            document.addEventListener('click', (e) => {
                if (!sidebar.contains(e.target) && !menuBtn.contains(e.target)) {
                    closeSidebar();
                }
            });
        }
    }

    destroy() {
        if (this.countdownInterval) {
            clearInterval(this.countdownInterval);
        }
    }
}

// ========================================
// Navigation Component
// ========================================

class Navigation {
    constructor() {
        this.element = document.getElementById('nav-sidebar');
    }

    init() {
        if (!this.element) return;

        // Add click handlers to nav items
        this.element.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const path = item.dataset.path;
                if (path) {
                    router.navigate(path);
                    // Close sidebar
                    this.element.classList.remove('open');
                    const overlay = document.getElementById('nav-overlay');
                    if (overlay) overlay.classList.remove('visible');
                    store.set('sidebarOpen', false);
                }
            });
        });
    }
}

// ========================================
// Page Registration
// ========================================

async function registerPages() {
    // Import page modules
    const [
        HomePage,
        PairsPage,
        TradesPage,
        PnLPage,
        DailyProfitPage,
        AgentsPage,
        AgentDetailPage,
        MetricsPage,
        ImproverPage,
        MemePage,
        CostsPage,
        SettingsPage,
        ChartsPage
    ] = await Promise.all([
        import('./pages/home.js').then(m => m.default).catch(() => createPlaceholderPage('Home')),
        import('./pages/pairs.js').then(m => m.default).catch(() => createPlaceholderPage('Trading Pairs')),
        import('./pages/trades.js').then(m => m.default).catch(() => createPlaceholderPage('Trade History')),
        import('./pages/pnl.js').then(m => m.default).catch(() => createPlaceholderPage('P&L Breakdown')),
        import('./pages/daily-profit.js').then(m => m.default).catch(() => createPlaceholderPage('Daily Profit')),
        import('./pages/agents.js').then(m => m.default).catch(() => createPlaceholderPage('Agents')),
        import('./pages/agent-detail.js').then(m => m.default).catch(() => createPlaceholderPage('Agent Detail')),
        import('./pages/metrics.js').then(m => m.default).catch(() => createPlaceholderPage('Metrics')),
        import('./pages/improver.js').then(m => m.default).catch(() => createPlaceholderPage('Improvement Cycles')),
        import('./pages/meme.js').then(m => m.default).catch(() => createPlaceholderPage('Meme Trading')),
        import('./pages/costs.js').then(m => m.default).catch(() => createPlaceholderPage('Cost Optimization')),
        import('./pages/settings.js').then(m => m.default).catch(() => createPlaceholderPage('Settings')),
        import('./pages/charts.js').then(m => m.default).catch(() => createPlaceholderPage('Charts'))
    ]);

    // Register routes
    router.register('/', HomePage);
    router.register('/pairs', PairsPage);
    router.register('/trades', TradesPage);
    router.register('/pnl', PnLPage);
    router.register('/daily-profit', DailyProfitPage);
    router.register('/agents', AgentsPage);
    router.register('/agents/:name', AgentDetailPage);
    router.register('/metrics', MetricsPage);
    router.register('/improver', ImproverPage);
    router.register('/meme', MemePage);
    router.register('/costs', CostsPage);
    router.register('/settings', SettingsPage);
    router.register('/charts', ChartsPage);
}

/**
 * Create placeholder page for pages not yet implemented
 */
function createPlaceholderPage(name) {
    return {
        name: name.toLowerCase().replace(/\s+/g, '-'),
        render(container) {
            container.innerHTML = `
                <div class="page placeholder-page">
                    <div class="placeholder-content">
                        <i data-lucide="construction" class="placeholder-icon"></i>
                        <h1>${name}</h1>
                        <p>This page is coming soon.</p>
                        <button class="btn btn-primary" onclick="window.location.hash='/'">
                            <i data-lucide="home"></i>
                            Go Home
                        </button>
                    </div>
                </div>
            `;
            if (window.lucide) window.lucide.createIcons();
            return { destroy: () => {} };
        }
    };
}

// ========================================
// Initial Data Load
// ========================================

async function loadInitialData() {
    store.set('loading', true);

    try {
        const data = await api.loadDashboardData();

        if (data.portfolio) {
            const { holdingsValue, memeValue } = splitPositionValues(data.portfolio.positions);
            store.update({
                portfolio: data.portfolio,
                totalValue: data.portfolio.total_value || 0,
                availableQuote: data.portfolio.available_quote || 0,
                holdingsValue,
                memeValue,
                totalPnL: data.portfolio.total_pnl || 0,
                pnlPercent: (data.portfolio.total_pnl_pct || 0) / 100,
                progressToTarget: data.portfolio.progress_to_target || 0,
                positions: data.portfolio.positions || []
            });
        }

        if (data.trades?.trades) {
            store.set('trades', data.trades.trades);
        }

        if (data.performance) {
            store.update({
                performance: data.performance,
                winRate: data.performance.win_rate || 0,
                totalTrades: data.performance.total_trades || 0,
                profitFactor: data.performance.profit_factor || 0
            });
        }

        if (data.status) {
            store.update({
                aiStatus: data.status,
                cycleCount: data.status.cycle_count || 0,
                isPaused: data.status.sentinel_paused || false,
                schedulerRunning: data.status.scheduler_running || true,
                secondsUntilNext: data.status.seconds_until_next
            });
        }

        if (data.phase2) {
            store.set('phase2Info', data.phase2);
        }

    } catch (error) {
        console.error('Failed to load initial data:', error);
        showToast('Failed to load dashboard data', 'error');
    } finally {
        store.set('loading', false);
    }
}

// ========================================
// Application Initialization
// ========================================

let appInitialized = false;

// ========================================
// Header Action Buttons
// ========================================

function initHeaderActions() {
    // --- Claude LLM Toggle ---
    const llmBtn = document.getElementById('llm-toggle');
    if (llmBtn) {
        // Fetch initial state
        api.get('/api/cost/hybrid/status').then(data => {
            updateLLMButton(llmBtn, !data.hybrid_enabled);
        }).catch(() => {
            updateLLMButton(llmBtn, true); // Default: LLM on
        });

        llmBtn.addEventListener('click', async () => {
            llmBtn.disabled = true;
            try {
                const current = await api.get('/api/cost/hybrid/status');
                const newHybrid = !current.hybrid_enabled;
                await api.post('/api/cost/hybrid/toggle', { enabled: newHybrid });
                const llmOn = !newHybrid;
                updateLLMButton(llmBtn, llmOn);
                showToast(llmOn ? 'Claude LLM enabled' : 'Claude LLM disabled (rule-based)', llmOn ? 'success' : 'warning', 3000);
            } catch (e) {
                showToast('Failed to toggle LLM mode', 'error');
            }
            llmBtn.disabled = false;
        });
    }

    // --- Trigger Cycle (fires both main + meme) ---
    const triggerBtn = document.getElementById('trigger-btn');
    if (triggerBtn) {
        triggerBtn.addEventListener('click', async () => {
            triggerBtn.disabled = true;
            triggerBtn.classList.add('triggering');
            showToast('Triggering all cycles...', 'info', 2000);

            const results = await Promise.allSettled([
                api.post('/trigger', {}),
                api.post('/api/meme/trigger', {})
            ]);

            const mainOk = results[0].status === 'fulfilled';
            const memeOk = results[1].status === 'fulfilled';
            const mainResult = mainOk ? results[0].value?.result : null;
            const memeResult = memeOk ? results[1].value?.result : null;

            const parts = [];
            if (mainOk && mainResult) {
                parts.push(`Main: ${mainResult.pairs_analyzed} pairs, ${mainResult.trades_executed} trades`);
            } else if (!mainOk) {
                parts.push('Main: failed');
            }
            if (memeOk && memeResult) {
                parts.push(`Meme: ${memeResult.coins_analyzed?.length || 0} coins, ${memeResult.trades_executed?.length || 0} trades`);
            } else if (!memeOk) {
                parts.push('Meme: skipped');
            }

            const allOk = mainOk || memeOk;
            showToast(parts.join(' | '), allOk ? 'success' : 'error', 4000);

            triggerBtn.classList.remove('triggering');
            triggerBtn.disabled = false;
        });
    }

    // --- Refresh ---
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            loadInitialData();
            showToast('Refreshing data...', 'info', 1500);
        });
    }

    // --- Theme Toggle ---
    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) {
        themeBtn.addEventListener('click', () => {
            const body = document.body;
            const current = body.getAttribute('data-theme') || 'dark';
            const next = current === 'dark' ? 'light' : 'dark';
            body.setAttribute('data-theme', next);
            localStorage.setItem('theme', next);
        });
    }
}

function updateLLMButton(btn, llmOn) {
    btn.title = llmOn ? 'Claude LLM: ON (click to switch to rules)' : 'Claude LLM: OFF (rule-based)';
    btn.classList.toggle('active', llmOn);
    btn.classList.toggle('dimmed', !llmOn);
}

async function initApp() {
    if (appInitialized) return;
    appInitialized = true;

    console.log('Initializing Kraken Trading Dashboard...');

    // Initialize components
    const header = new Header();
    const nav = new Navigation();

    header.init();
    nav.init();

    // Initialize header action buttons
    initHeaderActions();

    // Register pages
    await registerPages();

    // Load initial data
    await loadInitialData();

    // Connect WebSocket
    wsManager.connect();

    // Set up WebSocket event handlers
    wsManager.subscribe('portfolio', (data) => {
        if (data && data.total_value !== undefined) {
            const { holdingsValue, memeValue } = splitPositionValues(data.positions);
            store.update({
                portfolio: data,
                totalValue: data.total_value || 0,
                availableQuote: data.available_quote || 0,
                holdingsValue,
                memeValue,
                totalPnL: data.total_pnl || 0,
                pnlPercent: (data.total_pnl_pct || 0) / 100,
                progressToTarget: data.progress_to_target || 0
            });
        }
    });

    wsManager.subscribe('connected', () => {
        showToast('Connected to live updates', 'success', 2000);
    });

    wsManager.subscribe('disconnected', () => {
        showToast('Disconnected from live updates', 'warning', 3000);
    });

    // Handle initial route
    router.handleRoute();

    // Set up router callbacks
    router.onAfterNavigate((path) => {
        store.set('currentPage', path);
    });

    console.log('Dashboard initialized');
}

// ========================================
// Start Application
// ========================================

// Wait for DOM and auth
document.addEventListener('DOMContentLoaded', async () => {
    // Check if AuthManager exists and wait for auth
    if (window.AuthManager) {
        // Make initDashboard available for post-login callback
        window.initDashboard = initApp;

        // Check if already authenticated, if so init immediately
        const isAuthed = await window.AuthManager.checkAuth();
        if (isAuthed) {
            initApp();
        } else if (document.getElementById('authOverlay')) {
            // Auth modal exists in the HTML, show it and wait for login
            showAuthModal('signin');
        } else {
            // No auth modal in this HTML, proceed without auth
            initApp();
        }
    } else {
        // No auth, start immediately
        initApp();
    }
});

// Export for external access
window.KrakenApp = {
    router,
    store,
    api,
    wsManager,
    showToast
};
