/**
 * Daily Profit Page - Kraken Trading Dashboard
 * Shows daily portfolio start/end values, P&L, streak tracking,
 * and improvement actions taken after loss days.
 */

import api from '../api.js';
import { formatCurrency, formatPercent, formatNumber, setHTML, escapeHTML, getPnLClass } from '../utils.js';

const DailyProfitPage = {
    name: 'daily-profit',
    refreshInterval: null,
    chart: null,

    async render(container) {
        const html = `
            <div class="page daily-profit-page">
                <header class="page-header">
                    <div class="page-title-group">
                        <h1 class="page-title font-display">
                            <i data-lucide="calendar-check"></i>
                            DAILY PROFIT
                        </h1>
                        <p class="page-subtitle">Daily portfolio performance tracking — objective: positive daily P&L</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-secondary" id="refresh-daily-profit">
                            <i data-lucide="refresh-cw"></i>
                            Refresh
                        </button>
                        <button class="btn btn-primary" id="trigger-snapshot">
                            <i data-lucide="camera"></i>
                            Take Snapshot
                        </button>
                    </div>
                </header>

                <!-- Today's Live Status -->
                <section class="daily-hero">
                    <div class="hero-card today-card" id="today-hero">
                        <div class="hero-glow"></div>
                        <div class="hero-label font-display">TODAY</div>
                        <div class="today-status-row">
                            <div class="today-metric">
                                <span class="today-metric-label">Start</span>
                                <span class="today-metric-value font-mono" id="today-start">--</span>
                            </div>
                            <div class="today-arrow">
                                <i data-lucide="arrow-right"></i>
                            </div>
                            <div class="today-metric">
                                <span class="today-metric-label">Current</span>
                                <span class="today-metric-value font-mono" id="today-current">--</span>
                            </div>
                            <div class="today-arrow">
                                <i data-lucide="equal"></i>
                            </div>
                            <div class="today-metric today-pnl-metric">
                                <span class="today-metric-label">P&L</span>
                                <span class="today-metric-value font-mono" id="today-pnl">--</span>
                                <span class="today-metric-pct font-mono" id="today-pnl-pct"></span>
                            </div>
                        </div>
                        <div class="today-status-badge" id="today-badge">
                            <span id="today-status-text">Waiting for data...</span>
                        </div>
                    </div>
                </section>

                <!-- Streak & Summary Cards -->
                <section class="daily-summary-cards">
                    <div class="summary-card streak-card">
                        <div class="card-icon">
                            <i data-lucide="flame"></i>
                        </div>
                        <div class="card-content">
                            <span class="card-label font-display">CURRENT STREAK</span>
                            <span class="card-value font-mono" id="streak-value">--</span>
                            <span class="card-meta" id="streak-type">--</span>
                        </div>
                    </div>

                    <div class="summary-card profit-days-card">
                        <div class="card-icon success">
                            <i data-lucide="trending-up"></i>
                        </div>
                        <div class="card-content">
                            <span class="card-label font-display">PROFIT DAYS</span>
                            <span class="card-value font-mono" id="profit-days">0</span>
                            <span class="card-meta" id="profit-days-meta">of 0 days</span>
                        </div>
                    </div>

                    <div class="summary-card loss-days-card">
                        <div class="card-icon warning">
                            <i data-lucide="trending-down"></i>
                        </div>
                        <div class="card-content">
                            <span class="card-label font-display">LOSS DAYS</span>
                            <span class="card-value font-mono" id="loss-days">0</span>
                            <span class="card-meta" id="loss-days-meta">of 0 days</span>
                        </div>
                    </div>

                    <div class="summary-card cumulative-card">
                        <div class="card-icon">
                            <i data-lucide="sigma"></i>
                        </div>
                        <div class="card-content">
                            <span class="card-label font-display">CUMULATIVE P&L</span>
                            <span class="card-value font-mono" id="cumulative-pnl">$0.00</span>
                            <span class="card-meta">All tracked days</span>
                        </div>
                    </div>
                </section>

                <!-- Daily P&L Chart -->
                <section class="pnl-section">
                    <h2 class="section-title font-display">
                        <i data-lucide="bar-chart-3"></i>
                        DAILY P&L CHART
                    </h2>
                    <div class="chart-container" style="height: 280px; position: relative;">
                        <canvas id="daily-pnl-chart"></canvas>
                    </div>
                </section>

                <!-- Daily Ledger Table -->
                <section class="pnl-section">
                    <h2 class="section-title font-display">
                        <i data-lucide="table"></i>
                        DAILY LEDGER
                    </h2>
                    <div class="pnl-table-wrapper">
                        <table class="pnl-table daily-ledger-table">
                            <thead>
                                <tr>
                                    <th>Date</th>
                                    <th>Start Value</th>
                                    <th>End Value</th>
                                    <th>Daily P&L</th>
                                    <th>Daily %</th>
                                    <th>Trades</th>
                                    <th>W/L</th>
                                    <th>Main</th>
                                    <th>Meme</th>
                                    <th>Status</th>
                                    <th>Improvement</th>
                                </tr>
                            </thead>
                            <tbody id="daily-ledger-body">
                                <tr class="loading-row">
                                    <td colspan="11">
                                        <div class="table-loading">
                                            <div class="pulse-loader"></div>
                                            <span>Loading daily profit data...</span>
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

        // Event listeners
        document.getElementById('refresh-daily-profit')?.addEventListener('click', () => this.loadData());
        document.getElementById('trigger-snapshot')?.addEventListener('click', () => this.triggerSnapshot());

        // Load data
        await this.loadData();

        // Auto-refresh every 60s
        this.refreshInterval = setInterval(() => this.loadData(), 60000);

        return this;
    },

    async loadData() {
        try {
            const [ledger, today] = await Promise.all([
                api.getDailyProfit(30),
                api.getDailyProfitToday(),
            ]);
            this.updateToday(today);
            this.updateSummary(ledger);
            this.renderLedgerTable(ledger?.entries || []);
            this.renderChart(ledger?.entries || []);
        } catch (error) {
            console.error('Failed to load daily profit data:', error);
        }
    },

    updateToday(data) {
        if (!data) return;

        const startEl = document.getElementById('today-start');
        const currentEl = document.getElementById('today-current');
        const pnlEl = document.getElementById('today-pnl');
        const pctEl = document.getElementById('today-pnl-pct');
        const badgeEl = document.getElementById('today-badge');
        const statusEl = document.getElementById('today-status-text');
        const heroCard = document.getElementById('today-hero');

        if (data.snapshot_taken) {
            // Use live values if available (snapshot may be stale from pre-fix deploys)
            const currentValue = data.current_value || data.end_value;
            const pnl = data.live_pnl != null ? data.live_pnl : data.daily_pnl;
            const pnlPct = data.live_pnl_pct != null ? data.live_pnl_pct : data.daily_pnl_pct;

            if (startEl) startEl.textContent = formatCurrency(data.start_value);
            if (currentEl) currentEl.textContent = formatCurrency(currentValue);
            if (pnlEl) {
                pnlEl.textContent = formatCurrency(pnl);
                pnlEl.className = `today-metric-value font-mono ${getPnLClass(pnl)}`;
            }
            if (pctEl) pctEl.textContent = `(${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%)`;
            if (statusEl) statusEl.textContent = `${this.statusIcon(data.status)} LIVE (snapshot at 5:30 PM)`;
            if (heroCard) heroCard.setAttribute('data-status', pnl >= 0 ? 'profit' : 'loss');
        } else {
            if (startEl) startEl.textContent = formatCurrency(data.start_value);
            if (currentEl) currentEl.textContent = formatCurrency(data.current_value);
            const pnl = data.live_pnl || 0;
            const pnlPct = data.live_pnl_pct || 0;
            if (pnlEl) {
                pnlEl.textContent = formatCurrency(pnl);
                pnlEl.className = `today-metric-value font-mono ${getPnLClass(pnl)}`;
            }
            if (pctEl) pctEl.textContent = `(${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%)`;
            if (statusEl) statusEl.textContent = 'LIVE — Snapshot at 5:30 PM AEST';
            if (heroCard) heroCard.setAttribute('data-status', 'live');
        }
    },

    updateSummary(data) {
        if (!data) return;

        const streakVal = document.getElementById('streak-value');
        const streakType = document.getElementById('streak-type');
        const profitDays = document.getElementById('profit-days');
        const profitMeta = document.getElementById('profit-days-meta');
        const lossDays = document.getElementById('loss-days');
        const lossMeta = document.getElementById('loss-days-meta');
        const cumPnl = document.getElementById('cumulative-pnl');

        const streak = data.streak || {};
        if (streakVal) streakVal.textContent = `${streak.streak_days || 0} days`;
        if (streakType) {
            const st = streak.streak_type || 'none';
            streakType.textContent = st === 'PROFIT' ? 'Winning streak' : st === 'LOSS' ? 'Losing streak' : st;
        }

        if (profitDays) profitDays.textContent = data.profit_days || 0;
        if (profitMeta) profitMeta.textContent = `of ${data.total_days || 0} days`;
        if (lossDays) lossDays.textContent = data.loss_days || 0;
        if (lossMeta) lossMeta.textContent = `of ${data.total_days || 0} days`;

        if (cumPnl) {
            cumPnl.textContent = formatCurrency(data.cumulative_pnl || 0);
            cumPnl.className = `card-value font-mono ${getPnLClass(data.cumulative_pnl || 0)}`;
        }
    },

    renderLedgerTable(entries) {
        const tbody = document.getElementById('daily-ledger-body');
        if (!tbody) return;

        if (!entries || entries.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="11">
                        <div class="table-empty">
                            <i data-lucide="inbox"></i>
                            <span>No daily profit data yet. First snapshot at 5:30 PM AEST.</span>
                        </div>
                    </td>
                </tr>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        const rows = entries.map(e => {
            const statusClass = e.status === 'PROFIT' ? 'profit' : e.status === 'LOSS' ? 'loss' : 'neutral';
            const statusIcon = this.statusIcon(e.status);
            const winLoss = `${e.wins || 0}/${e.losses || 0}`;
            const improvement = e.improvement_action
                ? `<span class="improvement-tag" title="${escapeHTML(e.improvement_result || '')}">${escapeHTML(e.improvement_action.substring(0, 30))}</span>`
                : '<span class="no-action">—</span>';

            return `
                <tr class="ledger-row ${statusClass}">
                    <td class="font-mono">${escapeHTML(e.date)}</td>
                    <td class="font-mono">${formatCurrency(e.start_value)}</td>
                    <td class="font-mono">${formatCurrency(e.end_value)}</td>
                    <td class="font-mono ${getPnLClass(e.daily_pnl)}">${formatCurrency(e.daily_pnl)}</td>
                    <td class="font-mono ${getPnLClass(e.daily_pnl_pct)}">${e.daily_pnl_pct >= 0 ? '+' : ''}${e.daily_pnl_pct.toFixed(2)}%</td>
                    <td>${e.total_trades}</td>
                    <td class="font-mono">${winLoss}</td>
                    <td class="font-mono ${getPnLClass(e.main_pnl)}">${formatCurrency(e.main_pnl)}</td>
                    <td class="font-mono ${getPnLClass(e.meme_pnl)}">${formatCurrency(e.meme_pnl)}</td>
                    <td><span class="status-badge ${statusClass}">${statusIcon} ${e.status}</span></td>
                    <td class="improvement-cell">${improvement}</td>
                </tr>
            `;
        }).join('');

        tbody.innerHTML = rows;
        if (window.lucide) lucide.createIcons();
    },

    renderChart(entries) {
        const canvas = document.getElementById('daily-pnl-chart');
        if (!canvas) return;

        // Destroy existing chart
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }

        if (!entries || entries.length === 0) return;

        // Reverse to chronological order
        const sorted = [...entries].reverse();
        const labels = sorted.map(e => e.date);
        const pnlData = sorted.map(e => e.daily_pnl);
        const colors = pnlData.map(v => v >= 0 ? 'rgba(0, 230, 118, 0.8)' : 'rgba(255, 82, 82, 0.8)');
        const borderColors = pnlData.map(v => v >= 0 ? 'rgba(0, 230, 118, 1)' : 'rgba(255, 82, 82, 1)');

        // Cumulative line
        let cumulative = 0;
        const cumData = sorted.map(e => {
            cumulative += e.daily_pnl;
            return cumulative;
        });

        if (typeof Chart === 'undefined') return;

        this.chart = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Daily P&L',
                        data: pnlData,
                        backgroundColor: colors,
                        borderColor: borderColors,
                        borderWidth: 1,
                        borderRadius: 3,
                        order: 2,
                    },
                    {
                        label: 'Cumulative P&L',
                        data: cumData,
                        type: 'line',
                        borderColor: 'rgba(100, 181, 246, 1)',
                        backgroundColor: 'rgba(100, 181, 246, 0.1)',
                        borderWidth: 2,
                        pointRadius: 2,
                        fill: true,
                        tension: 0.3,
                        yAxisID: 'y1',
                        order: 1,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    intersect: false,
                    mode: 'index',
                },
                plugins: {
                    legend: {
                        labels: { color: 'rgba(255,255,255,0.7)', font: { family: 'JetBrains Mono', size: 11 } },
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.dataset.label}: $${ctx.raw.toFixed(4)}`,
                        },
                    },
                },
                scales: {
                    x: {
                        ticks: { color: 'rgba(255,255,255,0.5)', font: { family: 'JetBrains Mono', size: 10 } },
                        grid: { color: 'rgba(255,255,255,0.05)' },
                    },
                    y: {
                        position: 'left',
                        ticks: {
                            color: 'rgba(255,255,255,0.5)',
                            font: { family: 'JetBrains Mono', size: 10 },
                            callback: (v) => '$' + v.toFixed(2),
                        },
                        grid: { color: 'rgba(255,255,255,0.05)' },
                    },
                    y1: {
                        position: 'right',
                        ticks: {
                            color: 'rgba(100, 181, 246, 0.6)',
                            font: { family: 'JetBrains Mono', size: 10 },
                            callback: (v) => '$' + v.toFixed(2),
                        },
                        grid: { display: false },
                    },
                },
            },
        });
    },

    async triggerSnapshot() {
        try {
            const btn = document.getElementById('trigger-snapshot');
            if (btn) btn.disabled = true;
            await api.post('/api/profit-tracker/snapshot');
            await this.loadData();
            if (btn) btn.disabled = false;
        } catch (error) {
            console.error('Failed to trigger snapshot:', error);
            const btn = document.getElementById('trigger-snapshot');
            if (btn) btn.disabled = false;
        }
    },

    statusIcon(status) {
        switch (status) {
            case 'PROFIT': return '\u2705';
            case 'LOSS': return '\uD83D\uDD34';
            case 'STAGNANT': return '\uD83D\uDFE1';
            default: return '\u2B55';
        }
    },

    destroy() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    },
};

export default DailyProfitPage;
