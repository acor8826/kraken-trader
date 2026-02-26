/**
 * Hash-based SPA Router for Kraken Trading Dashboard
 * Handles navigation between pages without full page reloads
 */

class Router {
    constructor() {
        this.routes = new Map();
        this.currentPage = null;
        this.currentPath = null;
        this.beforeNavigate = null;
        this.afterNavigate = null;

        // Listen for hash changes
        window.addEventListener('hashchange', () => this.handleRoute());
    }

    /**
     * Register a route with its page module
     * @param {string} path - Route path (e.g., '/', '/pairs', '/agents/:name')
     * @param {object} pageModule - Page module with render() method
     */
    register(path, pageModule) {
        this.routes.set(path, pageModule);
    }

    /**
     * Navigate to a path
     * @param {string} path - Path to navigate to
     */
    navigate(path) {
        window.location.hash = path;
    }

    /**
     * Get current route params (for dynamic routes like /agents/:name)
     */
    getParams() {
        const hash = window.location.hash.slice(1) || '/';
        const parts = hash.split('/').filter(Boolean);

        for (const [pattern, _] of this.routes) {
            const patternParts = pattern.split('/').filter(Boolean);
            if (patternParts.length !== parts.length) continue;

            const params = {};
            let match = true;

            for (let i = 0; i < patternParts.length; i++) {
                if (patternParts[i].startsWith(':')) {
                    params[patternParts[i].slice(1)] = parts[i];
                } else if (patternParts[i] !== parts[i]) {
                    match = false;
                    break;
                }
            }

            if (match) return params;
        }

        return {};
    }

    /**
     * Handle route change
     */
    async handleRoute() {
        const hash = window.location.hash.slice(1) || '/';

        // Skip if same route
        if (hash === this.currentPath) return;

        // Before navigate callback
        if (this.beforeNavigate) {
            const shouldContinue = await this.beforeNavigate(hash, this.currentPath);
            if (shouldContinue === false) {
                // Restore previous hash if navigation cancelled
                if (this.currentPath) {
                    window.location.hash = this.currentPath;
                }
                return;
            }
        }

        // Cleanup previous page
        if (this.currentPage && this.currentPage.destroy) {
            try {
                this.currentPage.destroy();
            } catch (e) {
                console.warn('Page cleanup error:', e);
            }
        }

        // Find matching route
        const pageModule = this.matchRoute(hash);

        if (!pageModule) {
            console.warn(`No route found for: ${hash}`);
            // Redirect to home if route not found
            if (hash !== '/') {
                this.navigate('/');
            }
            return;
        }

        // Get app container
        const container = document.getElementById('app');
        if (!container) {
            console.error('App container not found');
            return;
        }

        // Show loading state
        container.innerHTML = `
            <div class="page-loading">
                <div class="loading-spinner"></div>
                <span class="loading-text">Loading...</span>
            </div>
        `;

        try {
            // Get route params
            const params = this.getParams();

            // Render new page
            this.currentPage = await pageModule.render(container, params);
            this.currentPath = hash;

            // Update active nav item
            this.updateActiveNav(hash);

            // After navigate callback
            if (this.afterNavigate) {
                this.afterNavigate(hash, params);
            }

            // Scroll to top
            window.scrollTo(0, 0);

        } catch (error) {
            console.error('Page render error:', error);
            container.innerHTML = `
                <div class="page-error">
                    <i data-lucide="alert-triangle"></i>
                    <h2>Failed to load page</h2>
                    <p>${error.message}</p>
                    <button class="btn btn-primary" onclick="window.location.hash='/'">
                        Go Home
                    </button>
                </div>
            `;
            // Re-initialize lucide icons
            if (window.lucide) {
                window.lucide.createIcons();
            }
        }
    }

    /**
     * Match a hash to a registered route
     * @param {string} hash - Current hash
     * @returns {object|null} - Page module or null
     */
    matchRoute(hash) {
        const parts = hash.split('/').filter(Boolean);

        // Exact match first
        if (this.routes.has(hash)) {
            return this.routes.get(hash);
        }

        // Check for root
        if (hash === '/' || hash === '') {
            return this.routes.get('/');
        }

        // Dynamic route matching
        for (const [pattern, module] of this.routes) {
            const patternParts = pattern.split('/').filter(Boolean);

            if (patternParts.length !== parts.length) continue;

            let match = true;
            for (let i = 0; i < patternParts.length; i++) {
                if (!patternParts[i].startsWith(':') && patternParts[i] !== parts[i]) {
                    match = false;
                    break;
                }
            }

            if (match) return module;
        }

        return null;
    }

    /**
     * Update active navigation item
     * @param {string} path - Current path
     */
    updateActiveNav(path) {
        // Remove active class from all nav items
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.remove('active');
        });

        // Add active class to matching nav item
        const basePath = '/' + (path.split('/')[1] || '');
        const activeItem = document.querySelector(`.nav-item[data-path="${basePath}"]`) ||
                          document.querySelector(`.nav-item[data-path="${path}"]`);

        if (activeItem) {
            activeItem.classList.add('active');
        }
    }

    /**
     * Set callback for before navigation
     * @param {function} callback - Callback function
     */
    onBeforeNavigate(callback) {
        this.beforeNavigate = callback;
    }

    /**
     * Set callback for after navigation
     * @param {function} callback - Callback function
     */
    onAfterNavigate(callback) {
        this.afterNavigate = callback;
    }
}

// Export singleton instance
const router = new Router();
export default router;
