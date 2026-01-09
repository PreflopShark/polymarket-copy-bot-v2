/**
 * Polymarket Copy Bot - Web App
 * Alpine.js application logic
 */

// Format runtime in human readable format
function formatRuntime(seconds) {
    if (!seconds) return '0s';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m ${s}s`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

// Format currency
function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2
    }).format(value);
}

// Format percentage
function formatPercent(value) {
    return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

// Format time for logs
function formatLogTime(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', { hour12: false });
}

// Convert slippage between percent and cents
function slippageToPercent(cents) {
    return cents / 100;
}

function slippageToCents(percent) {
    return percent * 100;
}

// Main Alpine.js application
document.addEventListener('alpine:init', () => {
    // Global app store
    Alpine.store('app', {
        wsConnected: false,
        botState: 'stopped',
        config: {},
        stats: {
            trades_detected: 0,
            trades_copied: 0,
            trades_skipped: 0,
            poll_count: 0
        },
        portfolio: {
            usdc_balance: 0,
            portfolio_value: 0,
            pnl: 0,
            pnl_percentage: 0,
            unrealized_pnl: 0,
            realized_pnl: 0,
            positions: []
        },
        logs: [],
        trades: [],
        startTime: null,
        runtime: 0,
        showSummary: false,
        sessionSummary: null,

        // Wallet validation
        walletInput: '',
        walletValidating: false,
        walletValid: null,
        walletUsername: null,

        // UI preferences
        slippageUnit: 'percent', // 'percent' or 'cents'
        slippageDisplay: 0,

        // Session history (persisted)
        sessionHistory: [],
        lastSession: null,

        // Cumulative stats across all sessions
        allTimeStats: {
            total_pnl: 0,
            total_realized_pnl: 0,
            total_trades: 0,
            sessions_count: 0
        },

        init() {
            this.loadConfig();
            this.loadSessionHistory();
            this.loadLastSession();
            this.calculateAllTimeStats();
            this.connectWebSocket();
            setInterval(() => this.updateRuntime(), 1000);
            // Check for resolved markets periodically
            setInterval(() => this.checkResolvedMarkets(), 30000);
        },

        // Load persisted session history from localStorage
        loadSessionHistory() {
            try {
                const saved = localStorage.getItem('polymarket_session_history');
                if (saved) {
                    this.sessionHistory = JSON.parse(saved);
                }
            } catch (e) {
                console.error('Failed to load session history:', e);
            }
        },

        // Save session history to localStorage
        saveSessionHistory() {
            try {
                // Keep last 50 sessions
                const toSave = this.sessionHistory.slice(-50);
                localStorage.setItem('polymarket_session_history', JSON.stringify(toSave));
                this.calculateAllTimeStats();
            } catch (e) {
                console.error('Failed to save session history:', e);
            }
        },

        // Calculate cumulative stats from all sessions
        calculateAllTimeStats() {
            let totalPnl = 0;
            let totalRealizedPnl = 0;
            let totalTrades = 0;

            for (const session of this.sessionHistory) {
                if (session.paper) {
                    totalPnl += session.paper.pnl || 0;
                    totalRealizedPnl += session.paper.realized_pnl || 0;
                }
                if (session.stats) {
                    totalTrades += session.stats.trades_copied || 0;
                }
            }

            this.allTimeStats = {
                total_pnl: totalPnl,
                total_realized_pnl: totalRealizedPnl,
                total_trades: totalTrades,
                sessions_count: this.sessionHistory.length
            };
        },

        // Load last active session
        loadLastSession() {
            try {
                const saved = localStorage.getItem('polymarket_last_session');
                if (saved) {
                    this.lastSession = JSON.parse(saved);
                }
            } catch (e) {
                console.error('Failed to load last session:', e);
            }
        },

        // Save current session state
        saveCurrentSession() {
            try {
                const sessionData = {
                    timestamp: new Date().toISOString(),
                    stats: { ...this.stats },
                    paper: {
                        usdc_balance: this.portfolio.usdc_balance,
                        portfolio_value: this.portfolio.portfolio_value,
                        pnl: this.portfolio.pnl,
                        pnl_percentage: this.portfolio.pnl_percentage,
                        realized_pnl: this.portfolio.realized_pnl || 0,
                        positions: this.portfolio.positions || []
                    },
                    config: {
                        target_wallet: this.config.target_wallet,
                        initial_balance: this.config.initial_balance
                    }
                };
                localStorage.setItem('polymarket_last_session', JSON.stringify(sessionData));
                this.lastSession = sessionData;
            } catch (e) {
                console.error('Failed to save current session:', e);
            }
        },

        // Update slippage display based on unit
        updateSlippageDisplay() {
            if (this.slippageUnit === 'cents') {
                this.slippageDisplay = slippageToCents(this.config.max_slippage || 0);
            } else {
                this.slippageDisplay = (this.config.max_slippage || 0) * 100;
            }
        },

        // Update config slippage from display value
        updateSlippageConfig() {
            if (this.slippageUnit === 'cents') {
                this.config.max_slippage = slippageToPercent(this.slippageDisplay);
            } else {
                this.config.max_slippage = this.slippageDisplay / 100;
            }
        },

        // Toggle slippage unit
        toggleSlippageUnit() {
            if (this.slippageUnit === 'percent') {
                this.slippageUnit = 'cents';
                this.slippageDisplay = slippageToCents(this.config.max_slippage || 0);
            } else {
                this.slippageUnit = 'percent';
                this.slippageDisplay = (this.config.max_slippage || 0) * 100;
            }
        },

        async loadConfig() {
            try {
                const response = await fetch('/api/config');
                if (response.ok) {
                    this.config = await response.json();
                    this.walletInput = this.config.target_wallet || '';
                    this.updateSlippageDisplay();
                }
            } catch (e) {
                console.error('Failed to load config:', e);
            }
        },

        async saveConfig() {
            try {
                // Update slippage before saving
                this.updateSlippageConfig();

                const response = await fetch('/api/config', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.config)
                });
                if (response.ok) {
                    const data = await response.json();
                    this.config = data.config;
                    this.updateSlippageDisplay();
                    this.addLog('INFO', 'Configuration saved');
                } else {
                    const error = await response.json();
                    this.addLog('ERROR', `Failed to save config: ${error.detail}`);
                }
            } catch (e) {
                this.addLog('ERROR', `Failed to save config: ${e.message}`);
            }
        },

        async validateWallet() {
            if (!this.walletInput.trim()) return;

            this.walletValidating = true;
            this.walletValid = null;

            try {
                const response = await fetch('/api/config/validate-wallet', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ wallet_or_url: this.walletInput })
                });

                const data = await response.json();
                this.walletValid = data.valid;
                this.walletUsername = data.username;

                if (data.valid && data.address) {
                    this.config.target_wallet = data.address;
                    this.walletInput = data.address;
                }
            } catch (e) {
                this.walletValid = false;
            } finally {
                this.walletValidating = false;
            }
        },

        async startBot() {
            try {
                const response = await fetch('/api/bot/start', { method: 'POST' });
                if (!response.ok) {
                    const error = await response.json();
                    this.addLog('ERROR', `Failed to start: ${error.detail}`);
                }
            } catch (e) {
                this.addLog('ERROR', `Failed to start: ${e.message}`);
            }
        },

        async stopBot() {
            try {
                const response = await fetch('/api/bot/stop', { method: 'POST' });
                if (!response.ok) {
                    const error = await response.json();
                    this.addLog('ERROR', `Failed to stop: ${error.detail}`);
                }
            } catch (e) {
                this.addLog('ERROR', `Failed to stop: ${e.message}`);
            }
        },

        async killBot() {
            if (!confirm('Force kill the bot? This will immediately terminate without cleanup.')) {
                return;
            }
            try {
                const response = await fetch('/api/bot/kill', { method: 'POST' });
                if (response.ok) {
                    this.addLog('WARN', 'Bot force killed');
                    this.botState = 'stopped';
                } else {
                    const error = await response.json();
                    this.addLog('ERROR', `Failed to kill: ${error.detail}`);
                }
            } catch (e) {
                this.addLog('ERROR', `Failed to kill: ${e.message}`);
            }
        },

        // Check for resolved markets and update PnL
        async checkResolvedMarkets() {
            if (this.portfolio.positions.length === 0) return;

            try {
                const response = await fetch('/api/portfolio/check-resolved');
                if (response.ok) {
                    const data = await response.json();
                    if (data.resolved_positions && data.resolved_positions.length > 0) {
                        this.portfolio.resolved_pnl = data.total_resolved_pnl || 0;
                        this.addLog('INFO', `Resolved ${data.resolved_positions.length} position(s), PnL: ${formatCurrency(data.total_resolved_pnl)}`);
                        this.saveCurrentSession();
                    }
                }
            } catch (e) {
                // Silently fail - endpoint might not exist yet
            }
        },

        // Clear last session data
        clearLastSession() {
            localStorage.removeItem('polymarket_last_session');
            this.lastSession = null;
            this.addLog('INFO', 'Last session data cleared');
        },

        // Clear all session history
        clearAllSessions() {
            localStorage.removeItem('polymarket_session_history');
            localStorage.removeItem('polymarket_last_session');
            this.sessionHistory = [];
            this.lastSession = null;
            this.allTimeStats = {
                total_pnl: 0,
                total_realized_pnl: 0,
                total_trades: 0,
                sessions_count: 0
            };
            this.addLog('INFO', 'All session history cleared');
        },

        connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

            ws.onopen = () => {
                this.wsConnected = true;
                console.log('WebSocket connected');
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            };

            ws.onclose = () => {
                this.wsConnected = false;
                console.log('WebSocket disconnected, reconnecting...');
                setTimeout(() => this.connectWebSocket(), 3000);
            };

            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
        },

        handleMessage(data) {
            switch (data.type) {
                case 'log':
                    this.logs.unshift({
                        time: formatLogTime(data.timestamp),
                        level: data.level,
                        message: data.message
                    });
                    // Keep log size manageable
                    if (this.logs.length > 200) this.logs.pop();
                    break;

                case 'state':
                    this.botState = data.state;
                    if (data.state === 'running') {
                        this.startTime = new Date();
                    } else if (data.state === 'stopped') {
                        this.startTime = null;
                    }
                    break;

                case 'status':
                    if (data.stats) this.stats = data.stats;
                    if (data.paper) {
                        this.portfolio = {
                            usdc_balance: data.paper.usdc_balance,
                            portfolio_value: data.paper.portfolio_value,
                            pnl: data.paper.pnl,
                            pnl_percentage: data.paper.pnl_percentage,
                            unrealized_pnl: data.paper.unrealized_pnl || 0,
                            realized_pnl: data.paper.realized_pnl || 0,
                            positions: data.paper.positions || [],
                            initial_balance: data.paper.initial_balance || this.config.initial_balance
                        };
                    }
                    if (data.start_time) {
                        this.startTime = new Date(data.start_time);
                    }
                    // Save session state periodically
                    this.saveCurrentSession();
                    break;

                case 'trade':
                    this.trades.unshift({
                        time: formatLogTime(data.timestamp),
                        ...data
                    });
                    if (this.trades.length > 100) this.trades.pop();
                    break;

                case 'session_complete':
                    this.sessionSummary = data.summary;
                    this.showSummary = true;
                    // Save to history
                    this.sessionHistory.push({
                        ...data.summary,
                        saved_at: new Date().toISOString()
                    });
                    this.saveSessionHistory();
                    this.saveCurrentSession();
                    break;

                case 'position_resolved':
                    this.addLog('INFO', `Position resolved: ${data.market} - PnL: ${formatCurrency(data.pnl)}`);
                    this.portfolio.resolved_pnl = (this.portfolio.resolved_pnl || 0) + data.pnl;
                    break;
            }
        },

        addLog(level, message) {
            this.logs.unshift({
                time: formatLogTime(new Date().toISOString()),
                level: level,
                message: message
            });
        },

        updateRuntime() {
            if (this.startTime && this.botState === 'running') {
                this.runtime = Math.floor((new Date() - this.startTime) / 1000);
            }
        },

        clearLogs() {
            this.logs = [];
        },

        closeSummary() {
            this.showSummary = false;
        },

        exportSummary() {
            if (!this.sessionSummary) return;
            const blob = new Blob([JSON.stringify(this.sessionSummary, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `session_${new Date().toISOString().slice(0, 10)}.json`;
            a.click();
            URL.revokeObjectURL(url);
        },

        // View session history
        showSessionHistory: false,
        toggleSessionHistory() {
            this.showSessionHistory = !this.showSessionHistory;
        }
    });
});

// Initialize app store when page loads
document.addEventListener('DOMContentLoaded', () => {
    Alpine.store('app').init();
});
