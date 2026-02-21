/**
 * Global State Store for Kraken Trading Dashboard
 * Centralized state management with pub/sub pattern
 */

class Store {
    constructor() {
        this.state = {
            // Portfolio data
            portfolio: null,
            positions: [],
            availableQuote: 0,
            totalValue: 0,
            totalPnL: 0,
            pnlPercent: 0,
            progressToTarget: 0,

            // Performance data
            performance: null,
            winRate: 0,
            totalTrades: 0,
            profitFactor: 0,

            // Trade history
            trades: [],
            rejectedTrades: [],

            // AI/Agent status
            aiStatus: null,
            cycleCount: 0,
            secondsUntilNext: null,
            isTrading: false,
            isPaused: false,
            schedulerRunning: false,

            // Phase 2 data
            phase2Info: null,
            fusion: null,
            breakers: null,
            sentiment: null,

            // Settings
            settings: null,

            // UI state
            sidebarOpen: false,
            currentPage: '/',
            theme: 'light',
            loading: false,
            error: null,

            // WebSocket state
            wsConnected: false,
            wsReconnecting: false
        };

        this.subscribers = new Map();
        this.history = [];
        this.maxHistory = 100;
    }

    /**
     * Get a state value
     * @param {string} key - State key
     * @returns {any} - State value
     */
    get(key) {
        if (key.includes('.')) {
            return key.split('.').reduce((obj, k) => obj?.[k], this.state);
        }
        return this.state[key];
    }

    /**
     * Set a state value and notify subscribers
     * @param {string} key - State key
     * @param {any} value - New value
     */
    set(key, value) {
        const oldValue = this.get(key);

        // Update state
        if (key.includes('.')) {
            const keys = key.split('.');
            let obj = this.state;
            for (let i = 0; i < keys.length - 1; i++) {
                if (!obj[keys[i]]) obj[keys[i]] = {};
                obj = obj[keys[i]];
            }
            obj[keys[keys.length - 1]] = value;
        } else {
            this.state[key] = value;
        }

        // Track history for debugging
        this.history.push({
            key,
            oldValue,
            newValue: value,
            timestamp: Date.now()
        });
        if (this.history.length > this.maxHistory) {
            this.history.shift();
        }

        // Notify subscribers
        this.notify(key, value, oldValue);
    }

    /**
     * Update multiple state values at once
     * @param {object} updates - Object with key-value pairs
     */
    update(updates) {
        for (const [key, value] of Object.entries(updates)) {
            this.set(key, value);
        }
    }

    /**
     * Subscribe to state changes
     * @param {string} key - State key to watch (use '*' for all changes)
     * @param {function} callback - Callback function(newValue, oldValue, key)
     * @returns {function} - Unsubscribe function
     */
    subscribe(key, callback) {
        if (!this.subscribers.has(key)) {
            this.subscribers.set(key, new Set());
        }
        this.subscribers.get(key).add(callback);

        // Return unsubscribe function
        return () => {
            const subs = this.subscribers.get(key);
            if (subs) {
                subs.delete(callback);
            }
        };
    }

    /**
     * Notify subscribers of state change
     * @param {string} key - Changed key
     * @param {any} newValue - New value
     * @param {any} oldValue - Old value
     */
    notify(key, newValue, oldValue) {
        // Notify specific key subscribers
        if (this.subscribers.has(key)) {
            this.subscribers.get(key).forEach(cb => {
                try {
                    cb(newValue, oldValue, key);
                } catch (e) {
                    console.error('Store subscriber error:', e);
                }
            });
        }

        // Notify wildcard subscribers
        if (this.subscribers.has('*')) {
            this.subscribers.get('*').forEach(cb => {
                try {
                    cb(newValue, oldValue, key);
                } catch (e) {
                    console.error('Store wildcard subscriber error:', e);
                }
            });
        }
    }

    /**
     * Reset state to initial values
     */
    reset() {
        this.state = {
            portfolio: null,
            positions: [],
            availableQuote: 0,
            totalValue: 0,
            totalPnL: 0,
            pnlPercent: 0,
            progressToTarget: 0,
            performance: null,
            winRate: 0,
            totalTrades: 0,
            profitFactor: 0,
            trades: [],
            rejectedTrades: [],
            aiStatus: null,
            cycleCount: 0,
            secondsUntilNext: null,
            isTrading: false,
            isPaused: false,
            schedulerRunning: false,
            phase2Info: null,
            fusion: null,
            breakers: null,
            sentiment: null,
            settings: null,
            sidebarOpen: false,
            currentPage: '/',
            theme: 'light',
            loading: false,
            error: null,
            wsConnected: false,
            wsReconnecting: false
        };
        this.notify('*', this.state, null);
    }

    /**
     * Get full state snapshot
     * @returns {object} - Full state object
     */
    getState() {
        return { ...this.state };
    }

    /**
     * Debug: Get state history
     * @returns {array} - State change history
     */
    getHistory() {
        return [...this.history];
    }
}

// Export singleton instance
const store = new Store();
export default store;
