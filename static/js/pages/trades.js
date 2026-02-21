/**
 * Trade History Page - Kraken Trading Dashboard
 * Executed trades with expandable AI reasoning + Rejected trades table
 */

import store from '../store.js';
import api from '../api.js';
import { formatCurrency, formatPercent, formatDateTime, formatTimeAgo, setHTML, escapeHTML, getPnLClass, getActionClass } from '../utils.js';

// ========================================
// Trade History Page Module
// ========================================

const TradesPage = {
    name: 'trades',
    refreshInterval: null,
    unsubscribers: [],

    /**
     * Render the trades page
     */
    async render(container) {
        const html = `
            <div class="page trades-page">
                <header class="page-header">
                    <div class="page-title-group">
                        <h1 class="page-title font-display">
                            <i data-lucide="history"></i>
                            TRADE HISTORY
                        </h1>
                        <p class="page-subtitle">Executed trades and rejected signals with AI reasoning</p>
                    </div>
                    <div class="page-actions">
                        <div class="filter-group">
                            <select id="filter-pair" class="filter-select">
                                <option value="">All Pairs</option>
                            </select>
                            <select id="filter-action" class="filter-select">
                                <option value="">All Actions</option>
                                <option value="BUY">Buy</option>
                                <option value="SELL">Sell</option>
                            </select>
                        </div>
                        <button class="btn btn-secondary" id="refresh-trades">
                            <i data-lucide="refresh-cw"></i>
                            Refresh
                        </button>
                    </div>
                </header>

                <!-- Tab Navigation -->
                <div class="trades-tabs" role="tablist">
                    <button class="tab-btn active" data-tab="executed" role="tab" aria-selected="true">
                        <i data-lucide="check-circle"></i>
                        Executed Trades
                        <span class="tab-count" id="executed-count">0</span>
                    </button>
                    <button class="tab-btn" data-tab="rejected" role="tab" aria-selected="false">
                        <i data-lucide="x-circle"></i>
                        Rejected Signals
                        <span class="tab-count" id="rejected-count">0</span>
                    </button>
                </div>

                <!-- Tab Content -->
                <div class="trades-content">
                    <!-- Executed Trades Tab -->
                    <div class="tab-panel active" id="tab-executed" role="tabpanel">
                        <div class="trades-table-wrapper">
                            <table class="trades-table" id="executed-table">
                                <thead>
                                    <tr>
                                        <th class="col-expand"></th>
                                        <th class="col-time">Time</th>
                                        <th class="col-pair">Pair</th>
                                        <th class="col-action">Action</th>
                                        <th class="col-amount">Amount</th>
                                        <th class="col-price">Price</th>
                                        <th class="col-pnl">P&L</th>
                                        <th class="col-status">Status</th>
                                    </tr>
                                </thead>
                                <tbody id="executed-body">
                                    <tr class="loading-row">
                                        <td colspan="8">
                                            <div class="table-loading">
                                                <div class="pulse-loader"></div>
                                                <span>Loading trades...</span>
                                            </div>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- Rejected Signals Tab -->
                    <div class="tab-panel" id="tab-rejected" role="tabpanel">
                        <div class="trades-table-wrapper">
                            <table class="trades-table" id="rejected-table">
                                <thead>
                                    <tr>
                                        <th class="col-expand"></th>
                                        <th class="col-time">Time</th>
                                        <th class="col-pair">Pair</th>
                                        <th class="col-action">Proposed</th>
                                        <th class="col-reason">Rejection Reason</th>
                                        <th class="col-agent">Agent</th>
                                    </tr>
                                </thead>
                                <tbody id="rejected-body">
                                    <tr class="loading-row">
                                        <td colspan="6">
                                            <div class="table-loading">
                                                <div class="pulse-loader"></div>
                                                <span>Loading rejected signals...</span>
                                            </div>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        `;

        setHTML(container, html);

        // Setup event listeners
        this.initTabs();
        this.initFilters();
        document.getElementById('refresh-trades')?.addEventListener('click', () => this.loadAllData());

        // Load data
        await this.loadAllData();

        // Refresh every 30 seconds
        this.refreshInterval = setInterval(() => this.loadAllData(), 30000);

        return this;
    },

    /**
     * Initialize tab switching
     */
    initTabs() {
        const tabBtns = document.querySelectorAll('.tab-btn');
        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                // Update buttons
                tabBtns.forEach(b => {
                    b.classList.remove('active');
                    b.setAttribute('aria-selected', 'false');
                });
                btn.classList.add('active');
                btn.setAttribute('aria-selected', 'true');

                // Update panels
                document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
                const tabId = btn.dataset.tab;
                document.getElementById(`tab-${tabId}`)?.classList.add('active');
            });
        });
    },

    /**
     * Initialize filters
     */
    initFilters() {
        const filterPair = document.getElementById('filter-pair');
        const filterAction = document.getElementById('filter-action');

        filterPair?.addEventListener('change', () => this.applyFilters());
        filterAction?.addEventListener('change', () => this.applyFilters());
    },

    /**
     * Apply filters to tables
     */
    applyFilters() {
        const pairFilter = document.getElementById('filter-pair')?.value || '';
        const actionFilter = document.getElementById('filter-action')?.value || '';

        // Filter executed trades
        document.querySelectorAll('#executed-body tr.trade-row').forEach(row => {
            const pair = row.dataset.pair || '';
            const action = row.dataset.action || '';
            const pairMatch = !pairFilter || pair.includes(pairFilter);
            const actionMatch = !actionFilter || action === actionFilter;
            row.style.display = pairMatch && actionMatch ? '' : 'none';
        });

        // Filter rejected signals
        document.querySelectorAll('#rejected-body tr.trade-row').forEach(row => {
            const pair = row.dataset.pair || '';
            const action = row.dataset.action || '';
            const pairMatch = !pairFilter || pair.includes(pairFilter);
            const actionMatch = !actionFilter || action === actionFilter;
            row.style.display = pairMatch && actionMatch ? '' : 'none';
        });
    },

    /**
     * Load all trades data
     */
    async loadAllData() {
        await Promise.all([
            this.loadExecutedTrades(),
            this.loadRejectedTrades()
        ]);
    },

    /**
     * Load executed trades
     */
    async loadExecutedTrades() {
        try {
            const data = await api.getHistory(100);
            const trades = data?.trades || [];
            this.renderExecutedTrades(trades);
            this.updatePairFilter(trades);
            document.getElementById('executed-count').textContent = trades.length;
        } catch (error) {
            console.error('Failed to load executed trades:', error);
            this.renderTableError('executed-body', 8);
        }
    },

    /**
     * Load rejected trades
     */
    async loadRejectedTrades() {
        try {
            const data = await api.getRejectedTrades(100);
            const rejected = data?.trades || data || [];
            this.renderRejectedTrades(rejected);
            document.getElementById('rejected-count').textContent = rejected.length;
        } catch (error) {
            console.error('Failed to load rejected trades:', error);
            // Show empty state for rejected trades (endpoint may not exist yet)
            this.renderRejectedTrades([]);
        }
    },

    /**
     * Update pair filter with available pairs
     */
    updatePairFilter(trades) {
        const filter = document.getElementById('filter-pair');
        if (!filter) return;

        const pairs = [...new Set(trades.map(t => t.pair || t.symbol).filter(Boolean))];

        // Keep current selection
        const current = filter.value;

        // Clear and rebuild
        filter.innerHTML = '<option value="">All Pairs</option>';
        pairs.forEach(pair => {
            const option = document.createElement('option');
            option.value = pair;
            option.textContent = pair;
            if (pair === current) option.selected = true;
            filter.appendChild(option);
        });
    },

    /**
     * Render executed trades table
     */
    renderExecutedTrades(trades) {
        const tbody = document.getElementById('executed-body');
        if (!tbody) return;

        if (!trades || trades.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="8">
                        <div class="table-empty">
                            <i data-lucide="inbox"></i>
                            <span>No executed trades yet</span>
                        </div>
                    </td>
                </tr>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        const rows = trades.map((trade, idx) => {
            const tradeId = trade.id || trade.trade_id || idx;
            const pair = trade.pair || trade.symbol || 'UNKNOWN';
            const action = trade.action || 'HOLD';
            const amount = trade.amount || trade.quantity || 0;
            const price = trade.price || trade.executed_price || 0;
            const pnl = trade.pnl || trade.realized_pnl || 0;
            const pnlClass = getPnLClass(pnl);
            const actionClass = getActionClass(action);
            const status = trade.status || 'FILLED';
            const time = trade.timestamp || trade.created_at;
            const reasoning = trade.reasoning || trade.signal_reason || 'No reasoning recorded';

            return `
                <tr class="trade-row" data-trade-id="${escapeHTML(String(tradeId))}" data-pair="${escapeHTML(pair)}" data-action="${escapeHTML(action)}">
                    <td class="col-expand">
                        <button class="expand-btn" aria-label="Expand details">
                            <i data-lucide="chevron-down"></i>
                        </button>
                    </td>
                    <td class="col-time">
                        <span class="time-relative">${formatTimeAgo(time)}</span>
                        <span class="time-full">${formatDateTime(time)}</span>
                    </td>
                    <td class="col-pair font-mono">${escapeHTML(pair)}</td>
                    <td class="col-action">
                        <span class="action-badge ${actionClass}">${escapeHTML(action)}</span>
                    </td>
                    <td class="col-amount font-mono">${formatCryptoAmount(amount)}</td>
                    <td class="col-price font-mono">${formatCurrency(price)}</td>
                    <td class="col-pnl font-mono ${pnlClass}">${formatCurrency(pnl)}</td>
                    <td class="col-status">
                        <span class="status-badge ${status.toLowerCase()}">${escapeHTML(status)}</span>
                    </td>
                </tr>
                <tr class="detail-row" data-detail-for="${escapeHTML(String(tradeId))}">
                    <td colspan="8">
                        <div class="trade-detail">
                            <div class="detail-section">
                                <h4 class="detail-title font-display">
                                    <i data-lucide="brain"></i>
                                    AI REASONING
                                </h4>
                                <p class="detail-reasoning">${escapeHTML(reasoning)}</p>
                            </div>
                            ${trade.confidence ? `
                                <div class="detail-meta">
                                    <span class="meta-item">
                                        <strong>Confidence:</strong> ${formatPercent(trade.confidence)}
                                    </span>
                                    ${trade.agent ? `<span class="meta-item"><strong>Agent:</strong> ${escapeHTML(trade.agent)}</span>` : ''}
                                </div>
                            ` : ''}
                        </div>
                    </td>
                </tr>
            `;
        }).join('');

        tbody.innerHTML = rows;
        if (window.lucide) lucide.createIcons();

        // Setup expand/collapse
        this.initExpandButtons('#executed-body');
    },

    /**
     * Render rejected trades table
     */
    renderRejectedTrades(rejected) {
        const tbody = document.getElementById('rejected-body');
        if (!tbody) return;

        if (!rejected || rejected.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="6">
                        <div class="table-empty">
                            <i data-lucide="check-circle"></i>
                            <span>No rejected signals</span>
                        </div>
                    </td>
                </tr>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        const rows = rejected.map((trade, idx) => {
            const tradeId = trade.id || idx;
            const pair = trade.pair || trade.symbol || 'UNKNOWN';
            const action = trade.proposed_action || trade.action || 'UNKNOWN';
            const actionClass = getActionClass(action);
            const reason = trade.rejection_reason || trade.reason || 'Unknown reason';
            const agent = trade.rejected_by || trade.agent || 'Sentinel';
            const time = trade.timestamp || trade.created_at;
            const fullReasoning = trade.full_reasoning || trade.reasoning || reason;

            return `
                <tr class="trade-row" data-trade-id="${escapeHTML(String(tradeId))}" data-pair="${escapeHTML(pair)}" data-action="${escapeHTML(action)}">
                    <td class="col-expand">
                        <button class="expand-btn" aria-label="Expand details">
                            <i data-lucide="chevron-down"></i>
                        </button>
                    </td>
                    <td class="col-time">
                        <span class="time-relative">${formatTimeAgo(time)}</span>
                        <span class="time-full">${formatDateTime(time)}</span>
                    </td>
                    <td class="col-pair font-mono">${escapeHTML(pair)}</td>
                    <td class="col-action">
                        <span class="action-badge ${actionClass}">${escapeHTML(action)}</span>
                    </td>
                    <td class="col-reason">${escapeHTML(reason)}</td>
                    <td class="col-agent">
                        <span class="agent-badge">${escapeHTML(agent)}</span>
                    </td>
                </tr>
                <tr class="detail-row" data-detail-for="${escapeHTML(String(tradeId))}">
                    <td colspan="6">
                        <div class="trade-detail rejection-detail">
                            <div class="detail-section">
                                <h4 class="detail-title font-display">
                                    <i data-lucide="x-circle"></i>
                                    REJECTION DETAILS
                                </h4>
                                <p class="detail-reasoning">${escapeHTML(fullReasoning)}</p>
                            </div>
                            ${trade.original_signal ? `
                                <div class="detail-meta">
                                    <span class="meta-item">
                                        <strong>Original Signal:</strong> ${escapeHTML(JSON.stringify(trade.original_signal))}
                                    </span>
                                </div>
                            ` : ''}
                        </div>
                    </td>
                </tr>
            `;
        }).join('');

        tbody.innerHTML = rows;
        if (window.lucide) lucide.createIcons();

        // Setup expand/collapse
        this.initExpandButtons('#rejected-body');
    },

    /**
     * Initialize expand buttons for a table
     */
    initExpandButtons(tbodySelector) {
        const tbody = document.querySelector(tbodySelector);
        if (!tbody) return;

        tbody.querySelectorAll('.expand-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const row = btn.closest('.trade-row');
                const tradeId = row?.dataset.tradeId;
                const detailRow = tbody.querySelector(`[data-detail-for="${tradeId}"]`);

                if (row && detailRow) {
                    row.classList.toggle('expanded');
                    detailRow.classList.toggle('expanded');
                    btn.classList.toggle('expanded');
                }
            });
        });
    },

    /**
     * Render table error
     */
    renderTableError(tbodyId, colspan) {
        const tbody = document.getElementById(tbodyId);
        if (tbody) {
            tbody.innerHTML = `
                <tr class="error-row">
                    <td colspan="${colspan}">
                        <div class="table-error">
                            <i data-lucide="alert-triangle"></i>
                            <span>Failed to load data</span>
                        </div>
                    </td>
                </tr>
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
    }
};

export default TradesPage;
