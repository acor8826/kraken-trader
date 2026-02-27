/**
 * Improvement Cycles Page - Kraken Trading Dashboard
 * Shows Seed Improver runs with expandable details
 */

import api from '../api.js';
import { formatTimeAgo, formatDateTime, setHTML, escapeHTML, showToast } from '../utils.js';

const STATUS_BADGE = {
    completed: 'badge-success',
    started: 'badge-warning',
    failed: 'badge-danger',
};

const PRIORITY_COLORS = {
    critical: 'var(--danger)',
    strategy: 'var(--accent-primary)',
    observability: 'var(--warning)',
    quality: 'var(--text-secondary)',
};

const VERDICT_ICONS = {
    approve: '✅',
    reject: '❌',
    defer: '⏳',
};

const ImproverPage = {
    name: 'improver',
    refreshInterval: null,
    runs: [],
    total: 0,
    offset: 0,
    limit: 20,
    expandedRunId: null,
    detailCache: {},

    async render(container) {
        setHTML(container, `
            <div class="page improver-page">
                <header class="page-header">
                    <div class="page-title-group">
                        <h1 class="page-title font-display">
                            <i data-lucide="sparkles"></i>
                            IMPROVEMENT CYCLES
                        </h1>
                        <p class="page-subtitle">Seed Improver analysis runs, recommendations, and outcomes</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-secondary" id="improver-refresh">
                            <i data-lucide="refresh-cw"></i>
                            Refresh
                        </button>
                    </div>
                </header>

                <div class="improver-content" id="improver-content">
                    <div class="improver-loading">
                        <div class="pulse-loader"></div>
                        <span>Loading improvement cycles...</span>
                    </div>
                </div>

                <div class="improver-pagination" id="improver-pagination" style="display:none">
                    <button class="btn btn-secondary btn-sm" id="improver-prev" disabled>← Prev</button>
                    <span class="pagination-info" id="improver-page-info"></span>
                    <button class="btn btn-secondary btn-sm" id="improver-next">Next →</button>
                </div>
            </div>
        `);

        document.getElementById('improver-refresh')?.addEventListener('click', () => this.loadRuns());
        document.getElementById('improver-prev')?.addEventListener('click', () => this.prevPage());
        document.getElementById('improver-next')?.addEventListener('click', () => this.nextPage());

        await this.loadRuns();

        this.refreshInterval = setInterval(() => this.loadRuns(true), 60000);

        return this;
    },

    destroy() {
        if (this.refreshInterval) clearInterval(this.refreshInterval);
        this.detailCache = {};
    },

    async loadRuns(silent = false) {
        const content = document.getElementById('improver-content');
        if (!content) return;

        if (!silent) {
            setHTML(content, `<div class="improver-loading"><div class="pulse-loader"></div><span>Loading...</span></div>`);
        }

        try {
            const data = await api.getSeedImproverRuns(this.limit, this.offset);
            this.runs = data.runs || [];
            this.total = data.total || 0;
            this.renderTable(content);
            this.updatePagination();
        } catch (err) {
            console.error('Failed to load improver runs:', err);
            if (err.status === 503) {
                setHTML(content, `
                    <div class="improver-empty">
                        <i data-lucide="database"></i>
                        <h3>Database Not Available</h3>
                        <p>Seed Improver requires PostgreSQL. Connect a database to see improvement cycles.</p>
                    </div>
                `);
            } else {
                setHTML(content, `
                    <div class="improver-empty improver-error">
                        <i data-lucide="alert-triangle"></i>
                        <h3>Failed to Load</h3>
                        <p>${escapeHTML(err.message || 'Unknown error')}</p>
                        <button class="btn btn-secondary btn-sm" onclick="document.getElementById('improver-refresh').click()">Retry</button>
                    </div>
                `);
            }
        }
    },

    renderTable(content) {
        if (!this.runs.length) {
            setHTML(content, `
                <div class="improver-empty">
                    <i data-lucide="sparkles"></i>
                    <h3>No Improvement Cycles Yet</h3>
                    <p>The Seed Improver runs daily at 6 PM AEST, or after losing trades. Cycles will appear here.</p>
                </div>
            `);
            return;
        }

        const rows = this.runs.map(r => `
            <tr class="improver-row ${this.expandedRunId === r.id ? 'expanded' : ''}" data-run-id="${escapeHTML(r.id)}">
                <td>
                    <span class="time-relative" title="${escapeHTML(r.started_at || '')}">${r.started_at ? formatTimeAgo(r.started_at) : '—'}</span>
                </td>
                <td><span class="trigger-badge trigger-${escapeHTML(r.trigger_type)}">${escapeHTML(r.trigger_type)}</span></td>
                <td><span class="badge ${STATUS_BADGE[r.status] || 'badge-neutral'}">${escapeHTML(r.status)}</span></td>
                <td class="num">${r.recommendations_count}</td>
                <td class="num">${r.applied_count}</td>
                <td class="summary-cell">${escapeHTML(r.summary || '—')}</td>
                <td class="expand-cell"><i data-lucide="${this.expandedRunId === r.id ? 'chevron-up' : 'chevron-down'}"></i></td>
            </tr>
            ${this.expandedRunId === r.id ? `<tr class="detail-row"><td colspan="7"><div class="run-detail" id="detail-${escapeHTML(r.id)}"><div class="pulse-loader"></div></div></td></tr>` : ''}
        `).join('');

        setHTML(content, `
            <div class="improver-table-wrap">
                <table class="improver-table">
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Trigger</th>
                            <th>Status</th>
                            <th>Recs</th>
                            <th>Applied</th>
                            <th>Summary</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `);

        // Attach row click handlers
        content.querySelectorAll('.improver-row').forEach(row => {
            row.addEventListener('click', () => this.toggleDetail(row.dataset.runId));
        });

        // Load detail if expanded
        if (this.expandedRunId) {
            this.loadDetail(this.expandedRunId);
        }
    },

    async toggleDetail(runId) {
        if (this.expandedRunId === runId) {
            this.expandedRunId = null;
        } else {
            this.expandedRunId = runId;
        }
        const content = document.getElementById('improver-content');
        if (content) this.renderTable(content);
    },

    async loadDetail(runId) {
        const el = document.getElementById(`detail-${runId}`);
        if (!el) return;

        if (this.detailCache[runId]) {
            this.renderDetail(el, this.detailCache[runId]);
            return;
        }

        try {
            const data = await api.getSeedImproverRunDetail(runId);
            this.detailCache[runId] = data;
            this.renderDetail(el, data);
        } catch (err) {
            setHTML(el, `<div class="detail-error">Failed to load details: ${escapeHTML(err.message)}</div>`);
        }
    },

    renderDetail(el, data) {
        const changes = data.changes || [];

        // Verdict summary
        const verdicts = { approve: 0, reject: 0, defer: 0, pending: 0 };
        const implResults = { implemented: 0, failed: 0, skipped: 0 };
        changes.forEach(c => {
            if (c.verdict) verdicts[c.verdict] = (verdicts[c.verdict] || 0) + 1;
            else verdicts.pending++;

            if (c.implementation_commit_sha) implResults.implemented++;
            else if (c.implementation_error) implResults.failed++;
            else if (c.verdict === 'reject') implResults.skipped++;
        });

        const changesHtml = changes.length ? changes.map(c => `
            <div class="change-card">
                <div class="change-header">
                    <span class="change-priority" style="color:${PRIORITY_COLORS[c.priority] || 'var(--text-secondary)'}">${escapeHTML(c.priority || 'unknown')}</span>
                    <span class="change-risk">${escapeHTML(c.risk_assessment || c.verdict_risk_score || '—')}</span>
                    ${c.verdict ? `<span class="change-verdict">${VERDICT_ICONS[c.verdict] || '?'} ${escapeHTML(c.verdict)}</span>` : '<span class="change-verdict pending">⏸ pending</span>'}
                    ${c.status ? `<span class="badge ${STATUS_BADGE[c.status] || 'badge-neutral'} badge-sm">${escapeHTML(c.status)}</span>` : ''}
                </div>
                <div class="change-summary">${escapeHTML(c.change_summary || '—')}</div>
                ${c.verdict_reason ? `<div class="change-reason"><strong>Reason:</strong> ${escapeHTML(c.verdict_reason)}</div>` : ''}
                ${c.implementation_branch ? `<div class="change-impl"><strong>Branch:</strong> ${escapeHTML(c.implementation_branch)}${c.implementation_commit_sha ? ` · <code>${escapeHTML(c.implementation_commit_sha.slice(0, 8))}</code>` : ''}${c.implementation_check_result ? ` · ${escapeHTML(c.implementation_check_result)}` : ''}</div>` : ''}
                ${c.implementation_error ? `<div class="change-impl-error"><strong>Error:</strong> ${escapeHTML(c.implementation_error)}</div>` : ''}
            </div>
        `).join('') : '<div class="no-changes">No recommendations in this cycle</div>';

        setHTML(el, `
            <div class="detail-grid">
                <div class="detail-stats">
                    <div class="detail-stat">
                        <span class="detail-stat-label">Duration</span>
                        <span class="detail-stat-value">${data.started_at && data.finished_at ? this.formatDuration(data.started_at, data.finished_at) : '—'}</span>
                    </div>
                    <div class="detail-stat">
                        <span class="detail-stat-label">Verdicts</span>
                        <span class="detail-stat-value">${verdicts.approve}✅ ${verdicts.reject}❌ ${verdicts.defer}⏳ ${verdicts.pending}⏸</span>
                    </div>
                    <div class="detail-stat">
                        <span class="detail-stat-label">Implementation</span>
                        <span class="detail-stat-value">${implResults.implemented} done · ${implResults.failed} failed · ${implResults.skipped} skipped</span>
                    </div>
                    <div class="detail-stat">
                        <span class="detail-stat-label">Patterns Updated</span>
                        <span class="detail-stat-value">${data.pattern_updates_count || 0}</span>
                    </div>
                </div>
                ${data.error ? `<div class="detail-error-banner"><strong>Error:</strong> ${escapeHTML(data.error)}</div>` : ''}
                <div class="detail-changes-header">Recommendations (${changes.length})</div>
                <div class="detail-changes">${changesHtml}</div>
            </div>
        `);
    },

    formatDuration(start, end) {
        const ms = new Date(end) - new Date(start);
        if (ms < 1000) return `${ms}ms`;
        const secs = Math.round(ms / 1000);
        if (secs < 60) return `${secs}s`;
        const mins = Math.floor(secs / 60);
        const remSecs = secs % 60;
        return `${mins}m ${remSecs}s`;
    },

    updatePagination() {
        const pag = document.getElementById('improver-pagination');
        if (!pag) return;

        if (this.total <= this.limit) {
            pag.style.display = 'none';
            return;
        }

        pag.style.display = 'flex';
        const page = Math.floor(this.offset / this.limit) + 1;
        const totalPages = Math.ceil(this.total / this.limit);

        document.getElementById('improver-page-info').textContent = `Page ${page} of ${totalPages} (${this.total} runs)`;
        document.getElementById('improver-prev').disabled = this.offset === 0;
        document.getElementById('improver-next').disabled = this.offset + this.limit >= this.total;
    },

    prevPage() {
        this.offset = Math.max(0, this.offset - this.limit);
        this.expandedRunId = null;
        this.loadRuns();
    },

    nextPage() {
        if (this.offset + this.limit < this.total) {
            this.offset += this.limit;
            this.expandedRunId = null;
            this.loadRuns();
        }
    },
};

export default ImproverPage;
