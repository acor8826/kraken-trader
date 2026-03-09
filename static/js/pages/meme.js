/**
 * Meme Coin Trading Page - Kraken Trading Dashboard
 * Twitter sentiment + volume momentum meme coin trading module overview
 */

import api from '../api.js';
import { formatCurrency, formatPercent, setHTML, escapeHTML, showToast } from '../utils.js';

const MemePage = {
    name: 'meme',
    refreshInterval: null,

    async render(container) {
        const html = `
            <div class="page meme-page">
                <header class="page-header">
                    <div class="page-title-group">
                        <h1 class="page-title font-display">
                            <i data-lucide="flame"></i>
                            MEME COIN TRADING
                        </h1>
                        <p class="page-subtitle">Twitter sentiment + volume momentum trading module</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-secondary" id="meme-trigger-btn">
                            <i data-lucide="zap"></i>
                            Trigger Cycle
                        </button>
                        <button class="btn btn-secondary" id="meme-pause-btn">
                            <i data-lucide="pause"></i>
                            Pause
                        </button>
                        <button class="btn btn-primary" id="meme-resume-btn" style="display:none;">
                            <i data-lucide="play"></i>
                            Resume
                        </button>
                        <button class="btn btn-secondary" id="meme-refresh-btn">
                            <i data-lucide="refresh-cw"></i>
                        </button>
                    </div>
                </header>

                <!-- Metric Cards -->
                <div class="meme-metrics-grid" id="meme-metrics">
                    <div class="meme-metric-card">
                        <div class="meme-card-header">
                            <i data-lucide="activity"></i>
                            <span class="font-display">MODULE STATUS</span>
                        </div>
                        <div class="meme-card-body">
                            <div class="meme-status-line">
                                <span class="meme-status-badge" id="meme-module-status">LOADING</span>
                            </div>
                            <div class="meme-stat-row">
                                <span class="meme-stat-label">Positions</span>
                                <span class="meme-stat-value font-mono" id="meme-positions-count">--</span>
                            </div>
                            <div class="meme-stat-row">
                                <span class="meme-stat-label">Exposure</span>
                                <span class="meme-stat-value font-mono" id="meme-exposure">--</span>
                            </div>
                            <div class="meme-stat-row">
                                <span class="meme-stat-label">Tracked Pairs</span>
                                <span class="meme-stat-value font-mono" id="meme-pairs-count">--</span>
                            </div>
                        </div>
                    </div>

                    <div class="meme-metric-card">
                        <div class="meme-card-header">
                            <i data-lucide="message-circle"></i>
                            <span class="font-display">TWITTER BUDGET</span>
                        </div>
                        <div class="meme-card-body">
                            <div class="meme-stat-row">
                                <span class="meme-stat-label">Daily</span>
                                <span class="meme-stat-value font-mono" id="meme-daily-reads">--</span>
                            </div>
                            <div class="budget-bar-wrap">
                                <div class="budget-bar">
                                    <div class="budget-bar-fill" id="meme-daily-bar" style="width:0%"></div>
                                </div>
                            </div>
                            <div class="meme-stat-row">
                                <span class="meme-stat-label">Monthly</span>
                                <span class="meme-stat-value font-mono" id="meme-monthly-reads">--</span>
                            </div>
                            <div class="budget-bar-wrap">
                                <div class="budget-bar">
                                    <div class="budget-bar-fill" id="meme-monthly-bar" style="width:0%"></div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="meme-metric-card">
                        <div class="meme-card-header">
                            <i data-lucide="shield"></i>
                            <span class="font-display">SENTINEL</span>
                        </div>
                        <div class="meme-card-body">
                            <div class="meme-status-line">
                                <span class="meme-status-badge" id="meme-sentinel-status">--</span>
                            </div>
                            <div class="meme-stat-row">
                                <span class="meme-stat-label">Consecutive Losses</span>
                                <span class="meme-stat-value font-mono" id="meme-consec-losses">--</span>
                            </div>
                            <div class="meme-stat-row">
                                <span class="meme-stat-label">Daily Meme P&L</span>
                                <span class="meme-stat-value font-mono" id="meme-daily-pnl">--</span>
                            </div>
                            <div class="meme-stat-row">
                                <span class="meme-stat-label">Rejections</span>
                                <span class="meme-stat-value font-mono" id="meme-rejections">--</span>
                            </div>
                        </div>
                    </div>

                    <div class="meme-metric-card">
                        <div class="meme-card-header">
                            <i data-lucide="repeat"></i>
                            <span class="font-display">CYCLE INFO</span>
                        </div>
                        <div class="meme-card-body">
                            <div class="meme-stat-row">
                                <span class="meme-stat-label">Cycle Count</span>
                                <span class="meme-stat-value font-mono" id="meme-cycle-count">--</span>
                            </div>
                            <div class="meme-stat-row">
                                <span class="meme-stat-label">Coins Analyzed</span>
                                <span class="meme-stat-value font-mono" id="meme-coins-analyzed">--</span>
                            </div>
                            <div class="meme-stat-row">
                                <span class="meme-stat-label">Trades Executed</span>
                                <span class="meme-stat-value font-mono" id="meme-trades-executed">--</span>
                            </div>
                            <div class="meme-stat-row">
                                <span class="meme-stat-label">Interval</span>
                                <span class="meme-stat-value font-mono">3 min</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Analysis Feed -->
                <section class="meme-section" id="meme-analysis-section">
                    <h2 class="meme-section-title font-display">
                        <i data-lucide="scan-search"></i>
                        LATEST ANALYSIS FEED
                        <span class="meme-cycle-tag font-mono" id="analysis-cycle-tag">Cycle --</span>
                    </h2>
                    <div class="meme-analysis-grid" id="meme-analysis-feed">
                        <div class="table-empty">
                            <i data-lucide="radio"></i>
                            <span>Waiting for first analysis cycle...</span>
                        </div>
                    </div>
                </section>

                <!-- Trade Evidence Log -->
                <section class="meme-section" id="meme-evidence-section" style="display:none;">
                    <h2 class="meme-section-title font-display">
                        <i data-lucide="file-check"></i>
                        TRADE EVIDENCE LOG
                    </h2>
                    <div class="meme-evidence-grid" id="meme-trade-evidence"></div>
                </section>

                <!-- Active Positions -->
                <section class="meme-section" id="meme-positions-section">
                    <h2 class="meme-section-title font-display">
                        <i data-lucide="target"></i>
                        ACTIVE POSITIONS
                    </h2>
                    <div class="trades-table-wrapper">
                        <table class="trades-table" id="meme-positions-table">
                            <thead>
                                <tr>
                                    <th>Symbol</th>
                                    <th>Pair</th>
                                    <th>Entry Price</th>
                                    <th>Current Price</th>
                                    <th>Amount</th>
                                    <th>P&L %</th>
                                    <th>Peak Price</th>
                                </tr>
                            </thead>
                            <tbody id="meme-positions-body">
                                <tr class="empty-row">
                                    <td colspan="7">
                                        <div class="table-empty">
                                            <i data-lucide="inbox"></i>
                                            <span>No active meme positions</span>
                                        </div>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </section>

                <!-- Coin Tiers -->
                <section class="meme-section">
                    <h2 class="meme-section-title font-display">
                        <i data-lucide="layers"></i>
                        COIN TIERS
                    </h2>
                    <div class="meme-tiers-grid" id="meme-tiers">
                        <div class="tier-group tier-hot">
                            <div class="tier-header">
                                <i data-lucide="flame"></i>
                                <span class="font-display">HOT</span>
                                <span class="tier-desc">Every cycle (3 min)</span>
                            </div>
                            <div class="tier-coins" id="tier-hot-coins">
                                <span class="coin-chip empty">None</span>
                            </div>
                        </div>
                        <div class="tier-group tier-warm">
                            <div class="tier-header">
                                <i data-lucide="sun"></i>
                                <span class="font-display">WARM</span>
                                <span class="tier-desc">Every 3rd cycle (9 min)</span>
                            </div>
                            <div class="tier-coins" id="tier-warm-coins">
                                <span class="coin-chip empty">None</span>
                            </div>
                        </div>
                        <div class="tier-group tier-cold">
                            <div class="tier-header">
                                <i data-lucide="snowflake"></i>
                                <span class="font-display">COLD</span>
                                <span class="tier-desc">Every 10th cycle (30 min)</span>
                            </div>
                            <div class="tier-coins" id="tier-cold-coins">
                                <span class="coin-chip empty">None</span>
                            </div>
                        </div>
                    </div>
                </section>

                <!-- Errors -->
                <section class="meme-section meme-errors-section" id="meme-errors-section" style="display:none;">
                    <h2 class="meme-section-title font-display">
                        <i data-lucide="alert-triangle"></i>
                        LAST CYCLE ERRORS
                    </h2>
                    <div class="meme-errors-list" id="meme-errors-list"></div>
                </section>
            </div>
        `;

        setHTML(container, html);

        // Init buttons
        document.getElementById('meme-trigger-btn')?.addEventListener('click', () => this.triggerCycle());
        document.getElementById('meme-pause-btn')?.addEventListener('click', () => this.pauseMeme());
        document.getElementById('meme-resume-btn')?.addEventListener('click', () => this.resumeMeme());
        document.getElementById('meme-refresh-btn')?.addEventListener('click', () => this.loadData());

        // Load data
        await this.loadData();

        // Auto-refresh every 30 seconds
        this.refreshInterval = setInterval(() => this.loadData(), 30000);

        return this;
    },

    async loadData() {
        try {
            const data = await api.getMemeStatus();
            if (data && data.status) {
                this.updateMetrics(data.status);
                this.updateAnalysisFeed(data.status.latest_analyses || []);
                this.updateTradeEvidence(data.status.latest_analyses || []);
                this.updatePositions(data.status.positions || {});
                this.updateTiers(data.status.coin_tiers || {});
                this.updateErrors(data.status.last_errors || []);
                this.updateBudget(data.status.twitter_budget || {});
                this.updateSentinel(data.status.sentinel_status || {});
                this.updateButtons(data.status.sentinel_status || {});
            }
        } catch (error) {
            console.error('[MEME PAGE] Failed to load meme status:', error);
            // Module may not be enabled
            const statusEl = document.getElementById('meme-module-status');
            if (statusEl) {
                statusEl.textContent = 'OFFLINE';
                statusEl.className = 'meme-status-badge status-stopped';
            }
        }
    },

    updateMetrics(status) {
        // Module status
        const statusEl = document.getElementById('meme-module-status');
        const sentinel = status.sentinel_status || {};
        if (statusEl) {
            if (sentinel.emergency_stopped) {
                statusEl.textContent = 'STOPPED';
                statusEl.className = 'meme-status-badge status-stopped';
            } else if (sentinel.paused_until) {
                statusEl.textContent = 'PAUSED';
                statusEl.className = 'meme-status-badge status-paused';
            } else if (sentinel.healthy) {
                statusEl.textContent = 'ACTIVE';
                statusEl.className = 'meme-status-badge status-active';
            } else {
                statusEl.textContent = 'UNHEALTHY';
                statusEl.className = 'meme-status-badge status-paused';
            }
        }

        // Position count
        const positions = status.positions || {};
        const posCount = Object.keys(positions).length;
        this._setText('meme-positions-count', posCount);

        // Exposure
        const exposure = sentinel.meme_exposure || 0;
        this._setText('meme-exposure', formatCurrency(exposure));

        // Tracked pairs
        this._setText('meme-pairs-count', status.active_pairs_count || 0);

        // Cycle count
        this._setText('meme-cycle-count', status.cycle_count || 0);

        // Strategist stats (coins analyzed / trades from last result)
        const stats = status.strategist_stats || {};
        this._setText('meme-coins-analyzed', stats.total_analyses || '--');
        this._setText('meme-trades-executed', stats.total_trades || '--');
    },

    updateBudget(budget) {
        const dailyUsed = budget.daily_used || 0;
        const dailyLimit = budget.daily_limit || 330;
        const monthlyUsed = budget.monthly_used || 0;
        const monthlyLimit = budget.monthly_limit || 10000;

        const dailyPct = dailyLimit > 0 ? (dailyUsed / dailyLimit) * 100 : 0;
        const monthlyPct = monthlyLimit > 0 ? (monthlyUsed / monthlyLimit) * 100 : 0;

        this._setText('meme-daily-reads', `${dailyUsed} / ${dailyLimit}`);
        this._setText('meme-monthly-reads', `${monthlyUsed} / ${monthlyLimit}`);

        const dailyBar = document.getElementById('meme-daily-bar');
        if (dailyBar) {
            dailyBar.style.width = `${Math.min(100, dailyPct)}%`;
            dailyBar.className = `budget-bar-fill ${this._budgetColor(dailyPct)}`;
        }

        const monthlyBar = document.getElementById('meme-monthly-bar');
        if (monthlyBar) {
            monthlyBar.style.width = `${Math.min(100, monthlyPct)}%`;
            monthlyBar.className = `budget-bar-fill ${this._budgetColor(monthlyPct)}`;
        }
    },

    updateSentinel(sentinel) {
        const statusEl = document.getElementById('meme-sentinel-status');
        if (statusEl) {
            if (sentinel.healthy) {
                statusEl.textContent = 'HEALTHY';
                statusEl.className = 'meme-status-badge status-active';
            } else {
                statusEl.textContent = 'UNHEALTHY';
                statusEl.className = 'meme-status-badge status-stopped';
            }
        }

        this._setText('meme-consec-losses', sentinel.consecutive_losses ?? '--');

        const pnl = sentinel.daily_meme_pnl || 0;
        const pnlEl = document.getElementById('meme-daily-pnl');
        if (pnlEl) {
            pnlEl.textContent = formatCurrency(pnl);
            pnlEl.className = `meme-stat-value font-mono ${pnl >= 0 ? 'profit' : 'loss'}`;
        }

        const stats = sentinel.stats || {};
        this._setText('meme-rejections', stats.rejections ?? '--');
    },

    updatePositions(positions) {
        const tbody = document.getElementById('meme-positions-body');
        if (!tbody) return;

        const entries = Object.entries(positions);

        if (entries.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="7">
                        <div class="table-empty">
                            <i data-lucide="inbox"></i>
                            <span>No active meme positions</span>
                        </div>
                    </td>
                </tr>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        const rows = entries.map(([symbol, pos]) => {
            const entry = pos.entry_price || 0;
            const current = pos.current_price || pos.entry_price || 0;
            const pnlPct = entry > 0 ? ((current - entry) / entry) : 0;
            const pnlClass = pnlPct >= 0 ? 'profit' : 'loss';
            const peak = pos.peak_price || current;

            return `
                <tr class="trade-row">
                    <td class="font-mono"><strong>${escapeHTML(symbol)}</strong></td>
                    <td class="font-mono">${escapeHTML(pos.pair || '')}</td>
                    <td class="font-mono">${this._formatPrice(entry)}</td>
                    <td class="font-mono">${this._formatPrice(current)}</td>
                    <td class="font-mono">${pos.amount ? pos.amount.toFixed(4) : '--'}</td>
                    <td class="font-mono ${pnlClass}">${formatPercent(pnlPct)}</td>
                    <td class="font-mono">${this._formatPrice(peak)}</td>
                </tr>
            `;
        }).join('');

        tbody.innerHTML = rows;
        if (window.lucide) lucide.createIcons();
    },

    updateTiers(coinTiers) {
        const hot = [];
        const warm = [];
        const cold = [];

        for (const [symbol, tier] of Object.entries(coinTiers)) {
            if (tier === 'hot') hot.push(symbol);
            else if (tier === 'warm') warm.push(symbol);
            else cold.push(symbol);
        }

        this._renderTierCoins('tier-hot-coins', hot, 'hot');
        this._renderTierCoins('tier-warm-coins', warm, 'warm');
        this._renderTierCoins('tier-cold-coins', cold, 'cold');
    },

    _renderTierCoins(containerId, coins, tierClass) {
        const el = document.getElementById(containerId);
        if (!el) return;

        if (coins.length === 0) {
            el.innerHTML = '<span class="coin-chip empty">None</span>';
            return;
        }

        el.innerHTML = coins.map(c =>
            `<span class="coin-chip coin-${tierClass}">${escapeHTML(c)}</span>`
        ).join('');
    },

    updateErrors(errors) {
        const section = document.getElementById('meme-errors-section');
        const list = document.getElementById('meme-errors-list');
        if (!section || !list) return;

        if (errors.length === 0) {
            section.style.display = 'none';
            return;
        }

        section.style.display = '';
        list.innerHTML = errors.map(err =>
            `<div class="meme-error-item"><i data-lucide="alert-circle"></i><span>${escapeHTML(err)}</span></div>`
        ).join('');
        if (window.lucide) lucide.createIcons();
    },

    updateButtons(sentinel) {
        const pauseBtn = document.getElementById('meme-pause-btn');
        const resumeBtn = document.getElementById('meme-resume-btn');

        if (pauseBtn && resumeBtn) {
            if (sentinel.healthy) {
                pauseBtn.style.display = '';
                resumeBtn.style.display = 'none';
            } else {
                pauseBtn.style.display = 'none';
                resumeBtn.style.display = '';
            }
        }
    },

    async triggerCycle() {
        const btn = document.getElementById('meme-trigger-btn');
        if (btn) btn.disabled = true;
        try {
            await api.triggerMemeCycle();
            showToast('Meme cycle triggered', 'success', 2000);
            await this.loadData();
        } catch (e) {
            showToast('Failed to trigger meme cycle', 'error');
        }
        if (btn) btn.disabled = false;
    },

    async pauseMeme() {
        try {
            await api.pauseMeme();
            showToast('Meme trading paused', 'warning', 2000);
            await this.loadData();
        } catch (e) {
            showToast('Failed to pause meme trading', 'error');
        }
    },

    async resumeMeme() {
        try {
            await api.resumeMeme();
            showToast('Meme trading resumed', 'success', 2000);
            await this.loadData();
        } catch (e) {
            showToast('Failed to resume meme trading', 'error');
        }
    },

    updateAnalysisFeed(analyses) {
        const container = document.getElementById('meme-analysis-feed');
        const cycleTag = document.getElementById('analysis-cycle-tag');
        if (!container) return;

        if (!analyses || analyses.length === 0) {
            container.innerHTML = `
                <div class="table-empty">
                    <i data-lucide="radio"></i>
                    <span>No analysis data yet. Waiting for cycle...</span>
                </div>`;
            if (window.lucide) lucide.createIcons();
            return;
        }

        if (cycleTag) cycleTag.textContent = `Cycle ${analyses[0].cycle}`;
        container.innerHTML = analyses.map(a => this._renderAnalysisCard(a)).join('');
        if (window.lucide) lucide.createIcons();
    },

    updateTradeEvidence(analyses) {
        const section = document.getElementById('meme-evidence-section');
        const container = document.getElementById('meme-trade-evidence');
        if (!section || !container) return;

        const executed = (analyses || []).filter(a => a.execution && a.execution.executed);
        if (executed.length === 0) {
            section.style.display = 'none';
            return;
        }

        section.style.display = '';
        container.innerHTML = executed.map(a => this._renderEvidenceCard(a)).join('');
        if (window.lucide) lucide.createIcons();
    },

    _renderAnalysisCard(a) {
        const tw = a.twitter || {};
        const vol = a.volume || {};
        const fusion = a.fusion || {};
        const dec = a.decision || {};
        const sen = a.sentinel || {};
        const action = dec.action || 'HOLD';
        const actionClass = action === 'BUY' ? 'action-buy' : action === 'SELL' ? 'action-sell' : 'action-hold';
        const sentimentClass = (tw.sentiment_score || 0) > 0 ? 'profit' : (tw.sentiment_score || 0) < 0 ? 'loss' : '';
        const sentinelClass = sen.approved ? 'sentinel-ok' : sen.rejection_reason ? 'sentinel-reject' : 'sentinel-pending';
        const sentinelText = sen.approved ? (sen.size_modified ? 'MODIFIED' : 'APPROVED') : (sen.rejection_reason || 'PENDING');
        const cms = fusion.cms || 0;
        const threshold = (dec.thresholds_used || {}).entry_cms || 0.65;
        const time = a.timestamp ? new Date(a.timestamp).toLocaleTimeString() : '--';

        return `
            <div class="meme-analysis-card ${actionClass}">
                <div class="analysis-card-header">
                    <span class="coin-chip coin-${a.tier || 'cold'}">${escapeHTML(a.symbol || '??')}</span>
                    <span class="analysis-action-badge ${actionClass}">${action}</span>
                    <span class="analysis-method-tag">${escapeHTML(dec.method || 'rule')}</span>
                    ${dec.confidence ? `<span class="analysis-conf font-mono">${(dec.confidence * 100).toFixed(0)}%</span>` : ''}
                    <span class="analysis-sentinel-badge ${sentinelClass}">${escapeHTML(sentinelText)}</span>
                    <span class="analysis-timestamp font-mono">${time}</span>
                </div>

                <div class="analysis-evidence-row">
                    <div class="evidence-label">
                        <i data-lucide="at-sign" class="evidence-icon"></i>
                        X / Twitter
                    </div>
                    <div class="evidence-metrics">
                        <span class="evidence-metric">
                            <span class="metric-label">mentions</span>
                            <span class="metric-value font-mono">${tw.mention_count ?? '--'}</span>
                        </span>
                        <span class="evidence-metric">
                            <span class="metric-label">sentiment</span>
                            <span class="metric-value font-mono ${sentimentClass}">${this._fmtSigned(tw.sentiment_score)}</span>
                        </span>
                        <span class="evidence-metric">
                            <span class="metric-label">velocity</span>
                            <span class="metric-value font-mono">${this._fmtFloat(tw.mention_velocity)}/m</span>
                        </span>
                        <span class="evidence-metric">
                            <span class="metric-label">influencers</span>
                            <span class="metric-value font-mono">${tw.influencer_mentions ?? 0}</span>
                        </span>
                        <span class="evidence-metric">
                            <span class="metric-label">signal</span>
                            <span class="metric-value font-mono">${this._fmtSigned(tw.signal_direction)} (${this._pct(tw.signal_confidence)})</span>
                        </span>
                    </div>
                </div>

                <div class="analysis-evidence-row">
                    <div class="evidence-label">
                        <i data-lucide="bar-chart-3" class="evidence-icon"></i>
                        Volume
                    </div>
                    <div class="evidence-metrics">
                        <span class="evidence-metric">
                            <span class="metric-label">vol_z</span>
                            <span class="metric-value font-mono">${this._fmtSigned(vol.volume_z_score)}</span>
                        </span>
                        <span class="evidence-metric">
                            <span class="metric-label">mom 5m</span>
                            <span class="metric-value font-mono">${this._fmtSigned(vol.price_momentum_5m)}%</span>
                        </span>
                        <span class="evidence-metric">
                            <span class="metric-label">B/S</span>
                            <span class="metric-value font-mono">${this._fmtFloat(vol.buy_sell_ratio)}</span>
                        </span>
                        <span class="evidence-metric">
                            <span class="metric-label">spread</span>
                            <span class="metric-value font-mono">${this._fmtFloat(vol.spread_pct)}%</span>
                        </span>
                        <span class="evidence-metric">
                            <span class="metric-label">signal</span>
                            <span class="metric-value font-mono">${this._fmtSigned(vol.signal_direction)} (${this._pct(vol.signal_confidence)})</span>
                        </span>
                    </div>
                </div>

                <div class="analysis-decision-row">
                    <div class="decision-cms-wrap">
                        <span class="metric-label">CMS</span>
                        <span class="metric-value font-mono cms-value">${this._fmtSigned(cms)}</span>
                    </div>
                    ${this._renderCmsBar(cms, threshold)}
                    <div class="decision-reasoning font-mono">${escapeHTML(dec.reasoning || '')}</div>
                </div>
            </div>`;
    },

    _renderEvidenceCard(a) {
        const dec = a.decision || {};
        const exec = a.execution || {};
        const tw = a.twitter || {};
        const vol = a.volume || {};
        const fusion = a.fusion || {};
        const sen = a.sentinel || {};
        const action = dec.action || 'HOLD';
        const actionClass = action === 'BUY' ? 'action-buy' : action === 'SELL' ? 'action-sell' : 'action-hold';
        const thresholds = dec.thresholds_used || {};

        return `
            <div class="meme-evidence-card ${actionClass}">
                <div class="evidence-card-header">
                    <span class="coin-chip coin-${a.tier || 'cold'}">${escapeHTML(a.symbol || '??')}</span>
                    <span class="analysis-action-badge ${actionClass}">${action} EXECUTED</span>
                    <span class="analysis-method-tag">${escapeHTML(dec.method || 'rule')}</span>
                </div>
                <div class="evidence-detail-grid">
                    <div class="evidence-detail-col">
                        <h4>X/Twitter Intelligence</h4>
                        <div class="evidence-kv"><span>Searched</span><span class="font-mono profit">YES</span></div>
                        <div class="evidence-kv"><span>Mentions (15m)</span><span class="font-mono">${tw.mention_count ?? 0}</span></div>
                        <div class="evidence-kv"><span>Sentiment</span><span class="font-mono">${this._fmtSigned(tw.sentiment_score)}</span></div>
                        <div class="evidence-kv"><span>Bullish Ratio</span><span class="font-mono">${this._pct(tw.bullish_ratio)}</span></div>
                        <div class="evidence-kv"><span>Velocity</span><span class="font-mono">${this._fmtFloat(tw.mention_velocity)}/min</span></div>
                        <div class="evidence-kv"><span>Influencers</span><span class="font-mono">${tw.influencer_mentions ?? 0}</span></div>
                        <div class="evidence-kv"><span>Engagement</span><span class="font-mono">${this._fmtFloat(tw.engagement_rate)}</span></div>
                        <div class="evidence-kv"><span>Signal</span><span class="font-mono">${this._fmtSigned(tw.signal_direction)} @ ${this._pct(tw.signal_confidence)}</span></div>
                    </div>
                    <div class="evidence-detail-col">
                        <h4>Volume Momentum</h4>
                        <div class="evidence-kv"><span>Volume Z-Score</span><span class="font-mono">${this._fmtSigned(vol.volume_z_score)}</span></div>
                        <div class="evidence-kv"><span>5m Momentum</span><span class="font-mono">${this._fmtSigned(vol.price_momentum_5m)}%</span></div>
                        <div class="evidence-kv"><span>15m Momentum</span><span class="font-mono">${this._fmtSigned(vol.price_momentum_15m)}%</span></div>
                        <div class="evidence-kv"><span>Buy/Sell Ratio</span><span class="font-mono">${this._fmtFloat(vol.buy_sell_ratio)}</span></div>
                        <div class="evidence-kv"><span>Spread</span><span class="font-mono">${this._fmtFloat(vol.spread_pct)}%</span></div>
                        <div class="evidence-kv"><span>Signal</span><span class="font-mono">${this._fmtSigned(vol.signal_direction)} @ ${this._pct(vol.signal_confidence)}</span></div>
                    </div>
                    <div class="evidence-detail-col">
                        <h4>Decision</h4>
                        <div class="evidence-kv"><span>CMS</span><span class="font-mono">${this._fmtSigned(fusion.cms)}</span></div>
                        <div class="evidence-kv"><span>Confidence</span><span class="font-mono">${this._pct(fusion.fused_confidence)}</span></div>
                        <div class="evidence-kv"><span>Method</span><span class="font-mono">${dec.method || 'rule'}</span></div>
                        <div class="evidence-kv"><span>Mode</span><span class="font-mono">${thresholds.mode || '--'}</span></div>
                        <div class="evidence-kv"><span>Entry Threshold</span><span class="font-mono">${thresholds.entry_cms ?? '--'}</span></div>
                        <div class="evidence-kv"><span>Min Vol Z</span><span class="font-mono">${thresholds.min_vol_z ?? '--'}</span></div>
                        <div class="evidence-kv"><span>Sentinel</span><span class="font-mono">${sen.approved ? 'APPROVED' : sen.rejection_reason || '--'}</span></div>
                        ${sen.size_modified ? `<div class="evidence-kv"><span>Size Modified</span><span class="font-mono">${this._pct(sen.original_size_pct)} -> ${this._pct(dec.size_pct)}</span></div>` : ''}
                    </div>
                    <div class="evidence-detail-col">
                        <h4>Execution</h4>
                        <div class="evidence-kv"><span>Fill Price</span><span class="font-mono">${this._formatPrice(exec.fill_price)}</span></div>
                        <div class="evidence-kv"><span>Fill Amount</span><span class="font-mono">${exec.fill_amount ? exec.fill_amount.toFixed(4) : '--'}</span></div>
                        <div class="evidence-kv"><span>Fill Value</span><span class="font-mono">${exec.fill_value ? formatCurrency(exec.fill_value) : '--'}</span></div>
                    </div>
                </div>
                <div class="evidence-reasoning">
                    <span class="metric-label">Reasoning:</span>
                    <span class="font-mono">${escapeHTML(dec.reasoning || '')}</span>
                </div>
            </div>`;
    },

    _renderCmsBar(cms, threshold) {
        // CMS ranges from -1 to +1, map to 0-100%
        const cmsPct = ((cms + 1) / 2) * 100;
        const thresholdPct = ((threshold + 1) / 2) * 100;
        const barColor = cms >= threshold ? 'var(--accent)' : cms > 0 ? 'var(--warning, #f59e0b)' : 'var(--danger, #ef4444)';

        return `
            <div class="cms-bar-wrap">
                <div class="cms-bar">
                    <div class="cms-bar-center"></div>
                    <div class="cms-bar-fill" style="left:50%;width:${Math.abs(cms) * 50}%;${cms < 0 ? `transform:translateX(-100%);` : ''}background:${barColor};"></div>
                    <div class="cms-threshold-marker" style="left:${thresholdPct}%;" title="Entry threshold: ${threshold}"></div>
                </div>
                <div class="cms-bar-labels font-mono">
                    <span>-1</span><span>0</span><span>+1</span>
                </div>
            </div>`;
    },

    _fmtSigned(val) {
        if (val == null) return '--';
        const n = parseFloat(val);
        if (isNaN(n)) return '--';
        return n >= 0 ? `+${n.toFixed(2)}` : n.toFixed(2);
    },

    _fmtFloat(val) {
        if (val == null) return '--';
        const n = parseFloat(val);
        if (isNaN(n)) return '--';
        return n.toFixed(2);
    },

    _pct(val) {
        if (val == null) return '--';
        const n = parseFloat(val);
        if (isNaN(n)) return '--';
        return `${(n * 100).toFixed(0)}%`;
    },

    _setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    },

    _formatPrice(price) {
        if (!price || price === 0) return '--';
        if (price < 0.001) return `$${price.toFixed(8)}`;
        if (price < 1) return `$${price.toFixed(6)}`;
        return formatCurrency(price);
    },

    _budgetColor(pct) {
        if (pct >= 80) return 'budget-danger';
        if (pct >= 50) return 'budget-warning';
        return 'budget-ok';
    },

    destroy() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }
};

export default MemePage;
