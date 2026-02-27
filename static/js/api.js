/**
 * API Client for Kraken Trading Dashboard
 * Centralized API calls with error handling and auth
 */

import store from './store.js';

class ApiClient {
    constructor() {
        this.baseUrl = '';
        this.token = null;
    }

    /**
     * Set auth token
     * @param {string} token - JWT token
     */
    setToken(token) {
        this.token = token;
    }

    /**
     * Make API request
     * @param {string} endpoint - API endpoint
     * @param {object} options - Fetch options
     * @returns {Promise<any>} - Response data
     */
    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;

        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };

        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }

        try {
            const response = await fetch(url, {
                ...options,
                headers
            });

            if (!response.ok) {
                const error = new Error(`HTTP ${response.status}: ${response.statusText}`);
                error.status = response.status;
                error.response = response;
                throw error;
            }

            // Handle empty responses
            const text = await response.text();
            return text ? JSON.parse(text) : null;

        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error);
            throw error;
        }
    }

    /**
     * GET request
     */
    async get(endpoint, params = {}) {
        const queryString = new URLSearchParams(params).toString();
        const url = queryString ? `${endpoint}?${queryString}` : endpoint;
        return this.request(url, { method: 'GET' });
    }

    /**
     * POST request
     */
    async post(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    /**
     * PUT request
     */
    async put(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    /**
     * DELETE request
     */
    async delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }

    // ========================================
    // Portfolio Endpoints
    // ========================================

    async getPortfolio() {
        return this.get('/portfolio');
    }

    async getPerformance() {
        return this.get('/performance');
    }

    async getHistory(limit = 50) {
        return this.get('/history', { limit });
    }

    async getTrades(limit = 50) {
        return this.get('/history', { limit });
    }

    async getPortfolioHistory(range = '7D') {
        return this.get('/api/portfolio/history', { range });
    }

    async getStatus() {
        return this.get('/status');
    }

    // ========================================
    // Trading Control Endpoints
    // ========================================

    async triggerCycle() {
        return this.post('/trigger');
    }

    async pauseTrading() {
        return this.post('/pause');
    }

    async resumeTrading() {
        return this.post('/resume');
    }

    async emergencyStop() {
        return this.post('/emergency-stop');
    }

    // ========================================
    // AI Activity Endpoints
    // ========================================

    async getAIActivity(limit = 10) {
        return this.get('/api/ai/activity', { limit });
    }

    async getCurrentCycle() {
        return this.get('/api/ai/cycle/current');
    }

    // ========================================
    // Phase 2 Endpoints
    // ========================================

    async getPhase2Info() {
        return this.get('/api/phase2/info');
    }

    async getBreakers() {
        return this.get('/api/phase2/breakers');
    }

    async getSentiment() {
        return this.get('/api/phase2/sentiment');
    }

    async getFusion() {
        return this.get('/api/phase2/fusion');
    }

    async getExecutionStats() {
        return this.get('/api/phase2/execution');
    }

    // ========================================
    // Positions & Market Endpoints
    // ========================================

    async getDetailedPositions() {
        return this.get('/api/positions/detailed');
    }

    async getOHLCV(pair, interval = 60, limit = 48) {
        return this.get(`/api/market/ohlcv/${encodeURIComponent(pair)}`, { interval, limit });
    }

    async getCorrelation() {
        return this.get('/api/correlation');
    }

    // ========================================
    // Analytics Endpoints
    // ========================================

    async getAnalyticsSummary() {
        return this.get('/api/analytics/summary');
    }

    async getAnalyticsByPair() {
        return this.get('/api/analytics/by-pair');
    }

    async getAnalyticsByHour() {
        return this.get('/api/analytics/by-hour');
    }

    async getAnalyticsByRegime() {
        return this.get('/api/analytics/by-regime');
    }

    async getAnalyticsMetrics() {
        return this.get('/api/analytics/metrics');
    }

    async exportAnalytics() {
        return this.get('/api/analytics/export');
    }

    // ========================================
    // P&L & Cost Endpoints
    // ========================================

    async getPnLSummary() {
        return this.get('/api/pnl/summary');
    }

    async getPnLByPair() {
        return this.get('/api/pnl/by-pair');
    }

    async getCostsUsage() {
        return this.get('/api/costs/usage');
    }

    async getCostsBreakdown() {
        return this.get('/api/costs/breakdown');
    }

    async getCostStats() {
        return this.get('/api/cost/stats');
    }

    async getCostConfig() {
        return this.get('/api/cost/config');
    }

    // ========================================
    // Alert Endpoints
    // ========================================

    async getRecentAlerts(limit = 50) {
        return this.get('/api/alerts/recent', { limit });
    }

    async getAlertConfig() {
        return this.get('/api/alerts/config');
    }

    async getAlertChannels() {
        return this.get('/api/alerts/channels');
    }

    async getAlertStats() {
        return this.get('/api/alerts/stats');
    }

    async testAlert() {
        return this.post('/api/alerts/test');
    }

    // ========================================
    // Agent Endpoints (NEW)
    // ========================================

    async getAgents() {
        return this.get('/api/agents');
    }

    async getAgent(name) {
        return this.get(`/api/agents/${encodeURIComponent(name)}`);
    }

    // ========================================
    // Settings Endpoints (NEW)
    // ========================================

    async getSettings() {
        return this.get('/api/settings');
    }

    async updateSettings(section, updates) {
        return this.put('/api/settings', { section, updates });
    }

    // ========================================
    // Trade Rejection Endpoints (NEW)
    // ========================================

    async getRejectedTrades(limit = 50) {
        return this.get('/api/trades/rejected', { limit });
    }

    async getTradeReasoning(tradeId) {
        return this.get(`/api/trades/${encodeURIComponent(tradeId)}/reasoning`);
    }

    // ========================================
    // Usage Tracking Endpoints (NEW)
    // ========================================

    async getTokenUsage() {
        return this.get('/api/usage/tokens');
    }

    async allocateUsage(accountId, period, allocation) {
        return this.post('/api/usage/allocate', { account_id: accountId, period, allocation });
    }

    // ========================================
    // Metrics Endpoints (NEW)
    // ========================================

    async getMetricDefinitions() {
        return this.get('/api/metrics/definitions');
    }

    // ========================================
    // Batch Loading Helpers
    // ========================================

    /**
     * Load all dashboard data in parallel
     */
    async loadDashboardData() {
        const results = await Promise.allSettled([
            this.getPortfolio(),
            this.getHistory(20),
            this.getPerformance(),
            this.getStatus(),
            this.getPhase2Info()
        ]);

        return {
            portfolio: results[0].status === 'fulfilled' ? results[0].value : null,
            trades: results[1].status === 'fulfilled' ? results[1].value : null,
            performance: results[2].status === 'fulfilled' ? results[2].value : null,
            status: results[3].status === 'fulfilled' ? results[3].value : null,
            phase2: results[4].status === 'fulfilled' ? results[4].value : null
        };
    }

    /**
     * Load homepage specific data
     */
    async loadHomepageData() {
        const results = await Promise.allSettled([
            this.getPortfolio(),
            this.getAIActivity(10),
            this.getCurrentCycle(),
            this.getPerformance()
        ]);

        return {
            portfolio: results[0].status === 'fulfilled' ? results[0].value : null,
            aiActivity: results[1].status === 'fulfilled' ? results[1].value : null,
            cycle: results[2].status === 'fulfilled' ? results[2].value : null,
            performance: results[3].status === 'fulfilled' ? results[3].value : null
        };
    }

    // ------------------------------------------------------------------
    // Seed Improver
    // ------------------------------------------------------------------

    async getSeedImproverRuns(limit = 20, offset = 0) {
        return this.request(`/internal/seed-improver/runs?limit=${limit}&offset=${offset}`);
    }

    async getSeedImproverRunDetail(runId) {
        return this.request(`/internal/seed-improver/runs/${runId}`);
    }

    async triggerSeedImproverRun(triggerType = 'manual') {
        return this.request('/internal/seed-improver/run', {
            method: 'POST',
            body: JSON.stringify({ trigger_type: triggerType }),
        });
    }

    /**
     * Load P&L page data
     */
    async loadPnLData() {
        const results = await Promise.allSettled([
            this.getPnLSummary(),
            this.getPnLByPair(),
            this.getCostsUsage(),
            this.getCostsBreakdown()
        ]);

        return {
            summary: results[0].status === 'fulfilled' ? results[0].value : null,
            byPair: results[1].status === 'fulfilled' ? results[1].value : null,
            usage: results[2].status === 'fulfilled' ? results[2].value : null,
            breakdown: results[3].status === 'fulfilled' ? results[3].value : null
        };
    }
}

// Export singleton instance
const api = new ApiClient();
export default api;
