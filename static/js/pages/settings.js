/**
 * Settings Page - Kraken Trading Dashboard
 * Configure risk parameters, circuit breakers, analyst weights, and alerts
 */

import store from '../store.js';
import api from '../api.js';
import { formatPercent, setHTML, escapeHTML, showToast } from '../utils.js';

// ========================================
// Settings Page Module
// ========================================

const SettingsPage = {
    name: 'settings',
    config: {},
    hasChanges: false,

    /**
     * Render the settings page
     */
    async render(container) {
        const html = `
            <div class="page settings-page">
                <header class="page-header">
                    <div class="page-title-group">
                        <h1 class="page-title font-display">
                            <i data-lucide="settings"></i>
                            SETTINGS
                        </h1>
                        <p class="page-subtitle">Configure risk parameters, circuit breakers, and alerts</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-secondary" id="reset-defaults">
                            <i data-lucide="rotate-ccw"></i>
                            Reset Defaults
                        </button>
                        <button class="btn btn-primary" id="save-settings" disabled>
                            <i data-lucide="save"></i>
                            Save Changes
                        </button>
                    </div>
                </header>

                <!-- Settings Sections -->
                <div class="settings-container">
                    <!-- Risk Parameters -->
                    <section class="settings-section">
                        <div class="section-header">
                            <h2 class="section-title font-display">
                                <i data-lucide="shield"></i>
                                RISK PARAMETERS
                            </h2>
                            <span class="section-desc">Control position sizing and exposure limits</span>
                        </div>
                        <div class="settings-grid">
                            <div class="setting-item">
                                <label for="max-position">Max Position Size</label>
                                <div class="setting-control">
                                    <input type="range" id="max-position" min="5" max="50" value="20" step="5">
                                    <span class="setting-value font-mono" id="val-max-position">20%</span>
                                </div>
                                <span class="setting-help">Maximum allocation per asset</span>
                            </div>

                            <div class="setting-item">
                                <label for="max-exposure">Max Total Exposure</label>
                                <div class="setting-control">
                                    <input type="range" id="max-exposure" min="20" max="100" value="80" step="10">
                                    <span class="setting-value font-mono" id="val-max-exposure">80%</span>
                                </div>
                                <span class="setting-help">Maximum portfolio deployment</span>
                            </div>

                            <div class="setting-item">
                                <label for="stop-loss">Stop Loss</label>
                                <div class="setting-control">
                                    <input type="range" id="stop-loss" min="2" max="15" value="5" step="1">
                                    <span class="setting-value font-mono" id="val-stop-loss">5%</span>
                                </div>
                                <span class="setting-help">Auto-sell threshold per position</span>
                            </div>

                            <div class="setting-item">
                                <label for="min-confidence">Min Confidence</label>
                                <div class="setting-control">
                                    <input type="range" id="min-confidence" min="50" max="95" value="70" step="5">
                                    <span class="setting-value font-mono" id="val-min-confidence">70%</span>
                                </div>
                                <span class="setting-help">Minimum confidence to execute trade</span>
                            </div>
                        </div>
                    </section>

                    <!-- Circuit Breakers -->
                    <section class="settings-section">
                        <div class="section-header">
                            <h2 class="section-title font-display">
                                <i data-lucide="alert-octagon"></i>
                                CIRCUIT BREAKERS
                            </h2>
                            <span class="section-desc">Automatic trading pauses to protect capital</span>
                        </div>
                        <div class="settings-grid">
                            <div class="setting-item">
                                <label for="daily-loss-limit">Daily Loss Limit</label>
                                <div class="setting-control">
                                    <input type="range" id="daily-loss-limit" min="5" max="25" value="10" step="1">
                                    <span class="setting-value font-mono" id="val-daily-loss-limit">10%</span>
                                </div>
                                <span class="setting-help">Pause trading if portfolio drops by this amount</span>
                            </div>

                            <div class="setting-item">
                                <label for="max-daily-trades">Max Daily Trades</label>
                                <div class="setting-control">
                                    <input type="range" id="max-daily-trades" min="5" max="50" value="15" step="5">
                                    <span class="setting-value font-mono" id="val-max-daily-trades">15</span>
                                </div>
                                <span class="setting-help">Maximum trades per 24 hours</span>
                            </div>

                            <div class="setting-item">
                                <label for="volatility-threshold">Volatility Threshold</label>
                                <div class="setting-control">
                                    <input type="range" id="volatility-threshold" min="5" max="20" value="10" step="1">
                                    <span class="setting-value font-mono" id="val-volatility-threshold">10%</span>
                                </div>
                                <span class="setting-help">Pause if 1-hour price move exceeds this</span>
                            </div>

                            <div class="setting-item">
                                <label for="consecutive-losses">Consecutive Loss Limit</label>
                                <div class="setting-control">
                                    <input type="range" id="consecutive-losses" min="2" max="10" value="3" step="1">
                                    <span class="setting-value font-mono" id="val-consecutive-losses">3</span>
                                </div>
                                <span class="setting-help">Pause after this many losing trades in a row</span>
                            </div>
                        </div>

                        <!-- Breaker Status -->
                        <div class="breaker-status" id="breaker-status">
                            <div class="breaker-indicator" data-breaker="daily_loss">
                                <span class="indicator-dot green"></span>
                                <span class="indicator-label">Daily Loss</span>
                            </div>
                            <div class="breaker-indicator" data-breaker="trade_frequency">
                                <span class="indicator-dot green"></span>
                                <span class="indicator-label">Trade Frequency</span>
                            </div>
                            <div class="breaker-indicator" data-breaker="volatility">
                                <span class="indicator-dot green"></span>
                                <span class="indicator-label">Volatility</span>
                            </div>
                            <div class="breaker-indicator" data-breaker="consecutive_loss">
                                <span class="indicator-dot green"></span>
                                <span class="indicator-label">Consecutive Loss</span>
                            </div>
                        </div>
                    </section>

                    <!-- Analyst Weights -->
                    <section class="settings-section">
                        <div class="section-header">
                            <h2 class="section-title font-display">
                                <i data-lucide="sliders-horizontal"></i>
                                ANALYST WEIGHTS
                            </h2>
                            <span class="section-desc">Adjust influence of each analyst (auto-normalized to 100%)</span>
                        </div>
                        <div class="settings-grid weights-grid">
                            <div class="setting-item weight-item">
                                <label for="weight-technical">
                                    <i data-lucide="candlestick-chart"></i>
                                    Technical
                                </label>
                                <div class="setting-control">
                                    <input type="range" id="weight-technical" min="0" max="100" value="45" step="5" class="weight-slider">
                                    <span class="setting-value font-mono" id="val-weight-technical">45%</span>
                                </div>
                            </div>

                            <div class="setting-item weight-item">
                                <label for="weight-sentiment">
                                    <i data-lucide="heart-pulse"></i>
                                    Sentiment
                                </label>
                                <div class="setting-control">
                                    <input type="range" id="weight-sentiment" min="0" max="100" value="35" step="5" class="weight-slider">
                                    <span class="setting-value font-mono" id="val-weight-sentiment">35%</span>
                                </div>
                            </div>

                            <div class="setting-item weight-item">
                                <label for="weight-onchain">
                                    <i data-lucide="link"></i>
                                    On-Chain
                                </label>
                                <div class="setting-control">
                                    <input type="range" id="weight-onchain" min="0" max="100" value="20" step="5" class="weight-slider">
                                    <span class="setting-value font-mono" id="val-weight-onchain">20%</span>
                                </div>
                            </div>

                            <div class="setting-item weight-item">
                                <label for="weight-macro">
                                    <i data-lucide="globe"></i>
                                    Macro
                                </label>
                                <div class="setting-control">
                                    <input type="range" id="weight-macro" min="0" max="100" value="0" step="5" class="weight-slider">
                                    <span class="setting-value font-mono" id="val-weight-macro">0%</span>
                                </div>
                            </div>
                        </div>
                        <div class="weights-total">
                            <span>Total Weight:</span>
                            <span class="font-mono" id="weights-total">100%</span>
                        </div>
                    </section>

                    <!-- Fear & Greed Components -->
                    <section class="settings-section">
                        <div class="section-header">
                            <h2 class="section-title font-display">
                                <i data-lucide="gauge"></i>
                                FEAR & GREED CONFIG
                            </h2>
                            <span class="section-desc">Adjust sentiment indicator weights and thresholds</span>
                        </div>
                        <div class="settings-grid">
                            <div class="setting-item">
                                <label for="fg-fear-threshold">Extreme Fear Threshold</label>
                                <div class="setting-control">
                                    <input type="range" id="fg-fear-threshold" min="10" max="40" value="25" step="5">
                                    <span class="setting-value font-mono" id="val-fg-fear-threshold">25</span>
                                </div>
                                <span class="setting-help">Below this value = extreme fear (bullish signal)</span>
                            </div>

                            <div class="setting-item">
                                <label for="fg-greed-threshold">Extreme Greed Threshold</label>
                                <div class="setting-control">
                                    <input type="range" id="fg-greed-threshold" min="60" max="90" value="75" step="5">
                                    <span class="setting-value font-mono" id="val-fg-greed-threshold">75</span>
                                </div>
                                <span class="setting-help">Above this value = extreme greed (bearish signal)</span>
                            </div>

                            <div class="setting-item">
                                <label for="fg-news-weight">News Sentiment Weight</label>
                                <div class="setting-control">
                                    <input type="range" id="fg-news-weight" min="0" max="100" value="40" step="10">
                                    <span class="setting-value font-mono" id="val-fg-news-weight">40%</span>
                                </div>
                                <span class="setting-help">Weight of news headlines in sentiment score</span>
                            </div>

                            <div class="setting-item toggle-item">
                                <label for="fg-contrarian">Contrarian Mode</label>
                                <div class="setting-control">
                                    <label class="toggle-switch">
                                        <input type="checkbox" id="fg-contrarian" checked>
                                        <span class="toggle-slider"></span>
                                    </label>
                                    <span class="toggle-label" id="val-fg-contrarian">Enabled</span>
                                </div>
                                <span class="setting-help">Buy on fear, sell on greed (recommended)</span>
                            </div>
                        </div>
                    </section>

                    <!-- Alert Configuration -->
                    <section class="settings-section">
                        <div class="section-header">
                            <h2 class="section-title font-display">
                                <i data-lucide="bell"></i>
                                ALERTS
                            </h2>
                            <span class="section-desc">Configure notification channels and triggers</span>
                        </div>
                        <div class="settings-grid">
                            <div class="setting-item toggle-item">
                                <label for="alert-trades">Trade Execution Alerts</label>
                                <div class="setting-control">
                                    <label class="toggle-switch">
                                        <input type="checkbox" id="alert-trades" checked>
                                        <span class="toggle-slider"></span>
                                    </label>
                                </div>
                                <span class="setting-help">Notify on each trade execution</span>
                            </div>

                            <div class="setting-item toggle-item">
                                <label for="alert-breakers">Circuit Breaker Alerts</label>
                                <div class="setting-control">
                                    <label class="toggle-switch">
                                        <input type="checkbox" id="alert-breakers" checked>
                                        <span class="toggle-slider"></span>
                                    </label>
                                </div>
                                <span class="setting-help">Notify when circuit breakers trigger</span>
                            </div>

                            <div class="setting-item toggle-item">
                                <label for="alert-daily">Daily Summary</label>
                                <div class="setting-control">
                                    <label class="toggle-switch">
                                        <input type="checkbox" id="alert-daily" checked>
                                        <span class="toggle-slider"></span>
                                    </label>
                                </div>
                                <span class="setting-help">Send daily P&L summary</span>
                            </div>

                            <div class="setting-item toggle-item">
                                <label for="alert-target">Target Reached</label>
                                <div class="setting-control">
                                    <label class="toggle-switch">
                                        <input type="checkbox" id="alert-target" checked>
                                        <span class="toggle-slider"></span>
                                    </label>
                                </div>
                                <span class="setting-help">Notify when profit target is reached</span>
                            </div>
                        </div>
                    </section>
                </div>
            </div>
        `;

        setHTML(container, html);

        // Initialize controls
        this.initSliders();
        this.initToggles();
        this.initWeightSliders();

        // Setup event listeners
        document.getElementById('save-settings')?.addEventListener('click', () => this.saveSettings());
        document.getElementById('reset-defaults')?.addEventListener('click', () => this.resetDefaults());

        // Load current settings
        await this.loadSettings();

        return this;
    },

    /**
     * Initialize range sliders
     */
    initSliders() {
        const sliders = document.querySelectorAll('input[type="range"]:not(.weight-slider)');
        sliders.forEach(slider => {
            const valueEl = document.getElementById(`val-${slider.id}`);
            slider.addEventListener('input', () => {
                let value = slider.value;
                if (slider.id.includes('trades') || slider.id.includes('losses')) {
                    valueEl.textContent = value;
                } else {
                    valueEl.textContent = `${value}%`;
                }
                this.markChanged();
            });
        });
    },

    /**
     * Initialize toggle switches
     */
    initToggles() {
        const toggles = document.querySelectorAll('input[type="checkbox"]');
        toggles.forEach(toggle => {
            toggle.addEventListener('change', () => {
                const labelEl = document.getElementById(`val-${toggle.id}`);
                if (labelEl) {
                    labelEl.textContent = toggle.checked ? 'Enabled' : 'Disabled';
                }
                this.markChanged();
            });
        });
    },

    /**
     * Initialize weight sliders with auto-normalization
     */
    initWeightSliders() {
        const weightSliders = document.querySelectorAll('.weight-slider');
        weightSliders.forEach(slider => {
            slider.addEventListener('input', () => {
                this.updateWeightDisplay(slider);
                this.normalizeWeights();
                this.markChanged();
            });
        });
    },

    /**
     * Update individual weight display
     */
    updateWeightDisplay(slider) {
        const valueEl = document.getElementById(`val-${slider.id}`);
        if (valueEl) {
            valueEl.textContent = `${slider.value}%`;
        }
    },

    /**
     * Normalize weights to show total (but don't auto-adjust)
     */
    normalizeWeights() {
        const sliders = document.querySelectorAll('.weight-slider');
        let total = 0;
        sliders.forEach(slider => {
            total += parseInt(slider.value);
        });

        const totalEl = document.getElementById('weights-total');
        if (totalEl) {
            totalEl.textContent = `${total}%`;
            totalEl.className = total === 100 ? 'font-mono' : 'font-mono warning';
        }
    },

    /**
     * Mark settings as changed
     */
    markChanged() {
        this.hasChanges = true;
        const saveBtn = document.getElementById('save-settings');
        if (saveBtn) {
            saveBtn.disabled = false;
        }
    },

    /**
     * Load current settings
     */
    async loadSettings() {
        try {
            const [settings, breakers] = await Promise.all([
                api.getSettings().catch(() => null),
                api.getBreakers().catch(() => null)
            ]);

            if (settings) {
                this.applySettings(settings);
            }

            if (breakers) {
                this.updateBreakerStatus(breakers);
            }
        } catch (error) {
            console.error('Failed to load settings:', error);
        }
    },

    /**
     * Apply settings to form controls
     */
    applySettings(settings) {
        const risk = settings.risk || {};
        const breakers = settings.circuit_breakers || {};
        const weights = settings.analyst_weights || {};
        const fearGreed = settings.fear_greed || {};
        const alerts = settings.alerts || {};

        // Risk parameters
        this.setSlider('max-position', risk.max_position_pct * 100 || 20);
        this.setSlider('max-exposure', risk.max_exposure_pct * 100 || 80);
        this.setSlider('stop-loss', risk.stop_loss_pct * 100 || 5);
        this.setSlider('min-confidence', risk.min_confidence * 100 || 70);

        // Circuit breakers
        this.setSlider('daily-loss-limit', breakers.max_daily_loss_pct * 100 || 10);
        this.setSlider('max-daily-trades', breakers.max_daily_trades || 15);
        this.setSlider('volatility-threshold', breakers.volatility_threshold_pct * 100 || 10);
        this.setSlider('consecutive-losses', breakers.consecutive_loss_limit || 3);

        // Analyst weights
        this.setSlider('weight-technical', weights.technical * 100 || 45);
        this.setSlider('weight-sentiment', weights.sentiment * 100 || 35);
        this.setSlider('weight-onchain', weights.onchain * 100 || 20);
        this.setSlider('weight-macro', weights.macro * 100 || 0);
        this.normalizeWeights();

        // Fear & Greed
        this.setSlider('fg-fear-threshold', fearGreed.extreme_fear_threshold || 25);
        this.setSlider('fg-greed-threshold', fearGreed.extreme_greed_threshold || 75);
        this.setSlider('fg-news-weight', fearGreed.news_weight * 100 || 40);
        this.setToggle('fg-contrarian', fearGreed.contrarian_mode !== false);

        // Alerts
        this.setToggle('alert-trades', alerts.on_trade !== false);
        this.setToggle('alert-breakers', alerts.on_circuit_breaker !== false);
        this.setToggle('alert-daily', alerts.daily_summary !== false);
        this.setToggle('alert-target', alerts.on_target !== false);
    },

    /**
     * Set slider value and display
     */
    setSlider(id, value) {
        const slider = document.getElementById(id);
        const valueEl = document.getElementById(`val-${id}`);
        if (slider) {
            slider.value = value;
            if (valueEl) {
                if (id.includes('trades') || id.includes('losses') || id.includes('threshold') && !id.includes('volatility')) {
                    valueEl.textContent = value;
                } else {
                    valueEl.textContent = `${value}%`;
                }
            }
        }
    },

    /**
     * Set toggle value
     */
    setToggle(id, checked) {
        const toggle = document.getElementById(id);
        const labelEl = document.getElementById(`val-${id}`);
        if (toggle) {
            toggle.checked = checked;
            if (labelEl) {
                labelEl.textContent = checked ? 'Enabled' : 'Disabled';
            }
        }
    },

    /**
     * Update circuit breaker status indicators
     */
    updateBreakerStatus(breakers) {
        Object.entries(breakers.status || {}).forEach(([key, tripped]) => {
            const indicator = document.querySelector(`[data-breaker="${key}"] .indicator-dot`);
            if (indicator) {
                indicator.className = `indicator-dot ${tripped ? 'red' : 'green'}`;
            }
        });
    },

    /**
     * Save settings
     */
    async saveSettings() {
        const settings = this.gatherSettings();

        try {
            await api.updateSettings('all', settings);
            showToast('Settings saved successfully', 'success');
            this.hasChanges = false;
            document.getElementById('save-settings').disabled = true;
        } catch (error) {
            console.error('Failed to save settings:', error);
            showToast('Failed to save settings', 'error');
        }
    },

    /**
     * Gather settings from form
     */
    gatherSettings() {
        return {
            risk: {
                max_position_pct: parseInt(document.getElementById('max-position').value) / 100,
                max_exposure_pct: parseInt(document.getElementById('max-exposure').value) / 100,
                stop_loss_pct: parseInt(document.getElementById('stop-loss').value) / 100,
                min_confidence: parseInt(document.getElementById('min-confidence').value) / 100
            },
            circuit_breakers: {
                max_daily_loss_pct: parseInt(document.getElementById('daily-loss-limit').value) / 100,
                max_daily_trades: parseInt(document.getElementById('max-daily-trades').value),
                volatility_threshold_pct: parseInt(document.getElementById('volatility-threshold').value) / 100,
                consecutive_loss_limit: parseInt(document.getElementById('consecutive-losses').value)
            },
            analyst_weights: {
                technical: parseInt(document.getElementById('weight-technical').value) / 100,
                sentiment: parseInt(document.getElementById('weight-sentiment').value) / 100,
                onchain: parseInt(document.getElementById('weight-onchain').value) / 100,
                macro: parseInt(document.getElementById('weight-macro').value) / 100
            },
            fear_greed: {
                extreme_fear_threshold: parseInt(document.getElementById('fg-fear-threshold').value),
                extreme_greed_threshold: parseInt(document.getElementById('fg-greed-threshold').value),
                news_weight: parseInt(document.getElementById('fg-news-weight').value) / 100,
                contrarian_mode: document.getElementById('fg-contrarian').checked
            },
            alerts: {
                on_trade: document.getElementById('alert-trades').checked,
                on_circuit_breaker: document.getElementById('alert-breakers').checked,
                daily_summary: document.getElementById('alert-daily').checked,
                on_target: document.getElementById('alert-target').checked
            }
        };
    },

    /**
     * Reset to defaults
     */
    resetDefaults() {
        const defaults = {
            risk: { max_position_pct: 0.20, max_exposure_pct: 0.80, stop_loss_pct: 0.05, min_confidence: 0.70 },
            circuit_breakers: { max_daily_loss_pct: 0.10, max_daily_trades: 15, volatility_threshold_pct: 0.10, consecutive_loss_limit: 3 },
            analyst_weights: { technical: 0.45, sentiment: 0.35, onchain: 0.20, macro: 0 },
            fear_greed: { extreme_fear_threshold: 25, extreme_greed_threshold: 75, news_weight: 0.40, contrarian_mode: true },
            alerts: { on_trade: true, on_circuit_breaker: true, daily_summary: true, on_target: true }
        };

        this.applySettings(defaults);
        this.markChanged();
        showToast('Settings reset to defaults', 'info');
    },

    /**
     * Cleanup on page destroy
     */
    destroy() {
        // Nothing to cleanup
    }
};

export default SettingsPage;
