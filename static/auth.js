/**
 * Authentication Manager for Kraken Trading Dashboard
 * Handles login, signup, password change, and Google OAuth
 */

// Auth Manager - handles token and user state
const AuthManager = {
    TOKEN_KEY: 'kraken_auth_token',
    USER_KEY: 'kraken_user',

    getToken() {
        return localStorage.getItem(this.TOKEN_KEY);
    },

    setToken(token) {
        localStorage.setItem(this.TOKEN_KEY, token);
    },

    clearToken() {
        localStorage.removeItem(this.TOKEN_KEY);
        localStorage.removeItem(this.USER_KEY);
    },

    getUser() {
        const user = localStorage.getItem(this.USER_KEY);
        return user ? JSON.parse(user) : null;
    },

    setUser(user) {
        localStorage.setItem(this.USER_KEY, JSON.stringify(user));
    },

    isAuthenticated() {
        return !!this.getToken();
    },

    // Get Authorization header
    getAuthHeader() {
        const token = this.getToken();
        return token ? { 'Authorization': `Bearer ${token}` } : {};
    },

    // Check if current token is valid
    async checkAuth() {
        if (!this.isAuthenticated()) {
            return false;
        }

        try {
            const response = await fetch('/api/auth/me', {
                headers: this.getAuthHeader()
            });

            if (response.ok) {
                const user = await response.json();
                this.setUser(user);
                return true;
            } else {
                this.clearToken();
                return false;
            }
        } catch (error) {
            console.warn('[AUTH] Token validation failed:', error);
            return false;
        }
    },

    // Sign out
    async signOut() {
        try {
            await fetch('/api/auth/signout', {
                method: 'POST',
                headers: this.getAuthHeader()
            });
        } catch (error) {
            console.warn('[AUTH] Signout error:', error);
        } finally {
            this.clearToken();
            showAuthModal('signin');
            if (typeof toast !== 'undefined') {
                toast.info('Signed out');
            }
        }
    }
};

// Auth UI Controller
const AuthUI = {
    currentMode: 'signin', // signin, signup, change-password

    elements: {
        overlay: null,
        modal: null,
        title: null,
        subtitle: null,
        signinForm: null,
        signupForm: null,
        changePasswordForm: null,
        divider: null,
        googleContainer: null,
        footer: null,
        toggleBtn: null,
        toggleText: null,
        closeBtn: null,
        passwordPopup: null,
        generatedPassword: null,
    },

    init() {
        // Cache elements
        this.elements.overlay = document.getElementById('authOverlay');
        this.elements.modal = document.getElementById('authModal');
        this.elements.title = document.getElementById('authTitle');
        this.elements.subtitle = document.getElementById('authSubtitle');
        this.elements.signinForm = document.getElementById('signinForm');
        this.elements.signupForm = document.getElementById('signupForm');
        this.elements.changePasswordForm = document.getElementById('changePasswordForm');
        this.elements.divider = document.getElementById('authDivider');
        this.elements.googleContainer = document.getElementById('googleSignInContainer');
        this.elements.footer = document.getElementById('authFooter');
        this.elements.toggleBtn = document.getElementById('authToggle');
        this.elements.toggleText = document.getElementById('authToggleText');
        this.elements.closeBtn = document.getElementById('authClose');
        this.elements.passwordPopup = document.getElementById('passwordPopup');
        this.elements.generatedPassword = document.getElementById('generatedPassword');

        // Bind event handlers
        this.bindEvents();
    },

    bindEvents() {
        // Toggle between signin/signup
        if (this.elements.toggleBtn) {
            this.elements.toggleBtn.addEventListener('click', () => {
                this.toggleMode();
            });
        }

        // Close button (for change password modal)
        if (this.elements.closeBtn) {
            this.elements.closeBtn.addEventListener('click', () => {
                this.hide();
            });
        }

        // Signin form
        if (this.elements.signinForm) {
            this.elements.signinForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleSignin();
            });
        }

        // Signup form
        if (this.elements.signupForm) {
            this.elements.signupForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleSignup();
            });
        }

        // Change password form
        if (this.elements.changePasswordForm) {
            this.elements.changePasswordForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleChangePassword();
            });
        }

        // Google sign in button
        const googleBtn = document.getElementById('googleSignIn');
        if (googleBtn) {
            googleBtn.addEventListener('click', () => {
                this.handleGoogleSignIn();
            });
        }

        // Copy password button
        const copyBtn = document.getElementById('copyPassword');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => {
                this.copyPassword();
            });
        }

        // Password confirm button
        const confirmBtn = document.getElementById('passwordConfirm');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', () => {
                this.hidePasswordPopup();
                this.setMode('signin');
            });
        }

        // Password visibility toggles
        document.querySelectorAll('.toggle-password').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const wrapper = e.target.closest('.input-wrapper');
                const input = wrapper.querySelector('input');
                const icon = wrapper.querySelector('.toggle-password i');

                if (input.type === 'password') {
                    input.type = 'text';
                    icon.setAttribute('data-lucide', 'eye-off');
                } else {
                    input.type = 'password';
                    icon.setAttribute('data-lucide', 'eye');
                }

                // Re-render lucide icons
                if (typeof lucide !== 'undefined') {
                    lucide.createIcons();
                }
            });
        });

        // Close modal on overlay click (only for change password)
        if (this.elements.overlay) {
            this.elements.overlay.addEventListener('click', (e) => {
                if (e.target === this.elements.overlay && this.currentMode === 'change-password') {
                    this.hide();
                }
            });
        }
    },

    setMode(mode) {
        this.currentMode = mode;

        // Hide all forms
        if (this.elements.signinForm) this.elements.signinForm.style.display = 'none';
        if (this.elements.signupForm) this.elements.signupForm.style.display = 'none';
        if (this.elements.changePasswordForm) this.elements.changePasswordForm.style.display = 'none';

        // Update UI based on mode
        switch (mode) {
            case 'signin':
                this.elements.title.textContent = 'Sign In';
                this.elements.subtitle.textContent = 'Access your trading dashboard';
                this.elements.signinForm.style.display = 'flex';
                this.elements.divider.style.display = 'flex';
                this.elements.googleContainer.style.display = 'block';
                this.elements.footer.style.display = 'block';
                this.elements.closeBtn.style.display = 'none';
                this.elements.toggleText.textContent = "Don't have an account?";
                this.elements.toggleBtn.textContent = 'Sign Up';
                break;

            case 'signup':
                this.elements.title.textContent = 'Sign Up';
                this.elements.subtitle.textContent = 'Create your trading account';
                this.elements.signupForm.style.display = 'flex';
                this.elements.divider.style.display = 'flex';
                this.elements.googleContainer.style.display = 'block';
                this.elements.footer.style.display = 'block';
                this.elements.closeBtn.style.display = 'none';
                this.elements.toggleText.textContent = 'Already have an account?';
                this.elements.toggleBtn.textContent = 'Sign In';
                break;

            case 'change-password':
                this.elements.title.textContent = 'Change Password';
                this.elements.subtitle.textContent = 'Update your account password';
                this.elements.changePasswordForm.style.display = 'flex';
                this.elements.divider.style.display = 'none';
                this.elements.googleContainer.style.display = 'none';
                this.elements.footer.style.display = 'none';
                this.elements.closeBtn.style.display = 'flex';
                break;
        }

        // Re-render icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    },

    toggleMode() {
        if (this.currentMode === 'signin') {
            this.setMode('signup');
        } else if (this.currentMode === 'signup') {
            this.setMode('signin');
        }
    },

    show(mode = 'signin') {
        this.setMode(mode);
        if (this.elements.overlay) {
            this.elements.overlay.setAttribute('aria-hidden', 'false');
        }
    },

    hide() {
        if (this.elements.overlay) {
            this.elements.overlay.setAttribute('aria-hidden', 'true');
        }
    },

    showPasswordPopup(password) {
        if (this.elements.generatedPassword) {
            this.elements.generatedPassword.textContent = password;
        }
        if (this.elements.passwordPopup) {
            this.elements.passwordPopup.setAttribute('aria-hidden', 'false');
        }
    },

    hidePasswordPopup() {
        if (this.elements.passwordPopup) {
            this.elements.passwordPopup.setAttribute('aria-hidden', 'true');
        }
    },

    async copyPassword() {
        const password = this.elements.generatedPassword?.textContent;
        if (password) {
            try {
                await navigator.clipboard.writeText(password);
                if (typeof toast !== 'undefined') {
                    toast.success('Password copied to clipboard');
                }
            } catch (err) {
                console.error('Failed to copy password:', err);
            }
        }
    },

    async handleSignin() {
        const email = document.getElementById('signinEmail')?.value;
        const password = document.getElementById('signinPassword')?.value;

        if (!email || !password) {
            if (typeof toast !== 'undefined') {
                toast.error('Please enter email and password');
            }
            return;
        }

        try {
            const response = await fetch('/api/auth/signin', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });

            const data = await response.json();

            if (response.ok) {
                AuthManager.setToken(data.access_token);
                AuthManager.setUser(data.user);
                this.hide();
                if (typeof toast !== 'undefined') {
                    toast.success('Signed in successfully');
                }
                // Trigger dashboard initialization
                if (typeof initDashboard === 'function') {
                    initDashboard();
                } else {
                    window.location.reload();
                }
            } else {
                if (typeof toast !== 'undefined') {
                    toast.error(data.detail || 'Sign in failed');
                }
            }
        } catch (error) {
            console.error('[AUTH] Signin error:', error);
            if (typeof toast !== 'undefined') {
                toast.error('Connection error. Please try again.');
            }
        }
    },

    async handleSignup() {
        const email = document.getElementById('signupEmail')?.value;

        if (!email) {
            if (typeof toast !== 'undefined') {
                toast.error('Please enter your email');
            }
            return;
        }

        try {
            const response = await fetch('/api/auth/signup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email })
            });

            const data = await response.json();

            if (response.ok) {
                // Show the generated password
                this.showPasswordPopup(data.generated_password);
                if (typeof toast !== 'undefined') {
                    toast.success('Account created! Save your password.');
                }
            } else {
                if (typeof toast !== 'undefined') {
                    toast.error(data.detail || 'Signup failed');
                }
            }
        } catch (error) {
            console.error('[AUTH] Signup error:', error);
            if (typeof toast !== 'undefined') {
                toast.error('Connection error. Please try again.');
            }
        }
    },

    async handleChangePassword() {
        const currentPassword = document.getElementById('currentPassword')?.value;
        const newPassword = document.getElementById('newPassword')?.value;
        const confirmPassword = document.getElementById('confirmPassword')?.value;

        if (!currentPassword || !newPassword || !confirmPassword) {
            if (typeof toast !== 'undefined') {
                toast.error('Please fill in all fields');
            }
            return;
        }

        if (newPassword !== confirmPassword) {
            if (typeof toast !== 'undefined') {
                toast.error('New passwords do not match');
            }
            return;
        }

        if (newPassword.length < 8) {
            if (typeof toast !== 'undefined') {
                toast.error('Password must be at least 8 characters');
            }
            return;
        }

        try {
            const response = await fetch('/api/auth/change-password', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...AuthManager.getAuthHeader()
                },
                body: JSON.stringify({
                    current_password: currentPassword,
                    new_password: newPassword
                })
            });

            const data = await response.json();

            if (response.ok) {
                this.hide();
                // Clear form
                document.getElementById('currentPassword').value = '';
                document.getElementById('newPassword').value = '';
                document.getElementById('confirmPassword').value = '';

                if (typeof toast !== 'undefined') {
                    toast.success('Password updated successfully');
                }
            } else {
                if (typeof toast !== 'undefined') {
                    toast.error(data.detail || 'Failed to change password');
                }
            }
        } catch (error) {
            console.error('[AUTH] Change password error:', error);
            if (typeof toast !== 'undefined') {
                toast.error('Connection error. Please try again.');
            }
        }
    },

    handleGoogleSignIn() {
        // Google OAuth - requires GOOGLE_CLIENT_ID to be configured
        if (typeof toast !== 'undefined') {
            toast.info('Google sign-in requires configuration. Please use email/password.');
        }

        // If Google Identity Services is loaded, use it
        if (typeof google !== 'undefined' && google.accounts) {
            google.accounts.id.prompt();
        }
    }
};

// Global functions for easy access
function showAuthModal(mode = 'signin') {
    AuthUI.show(mode);
}

function hideAuthModal() {
    AuthUI.hide();
}

function showChangePasswordModal() {
    AuthUI.show('change-password');
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    AuthUI.init();
});

// Export for use in dashboard.js
window.AuthManager = AuthManager;
window.AuthUI = AuthUI;
window.showAuthModal = showAuthModal;
window.hideAuthModal = hideAuthModal;
window.showChangePasswordModal = showChangePasswordModal;
