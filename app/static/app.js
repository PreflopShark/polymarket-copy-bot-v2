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

        init() {
            this.loadConfig();
            this.connectWebSocket();
            setInterval(() => this.updateRuntime(), 1000);
        },

        async loadConfig() {
            try {
                const response = await fetch('/api/config');
                if (response.ok) {
                    this.config = await response.json();
                    this.walletInput = this.config.target_wallet || '';
                }
            } catch (e) {
                console.error('Failed to load config:', e);
            }
        },

        async saveConfig() {
            try {
                const response = await fetch('/api/config', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.config)
                });
                if (response.ok) {
                    const data = await response.json();
                    this.config = data.config;
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
                            positions: data.paper.positions || []
                        };
                    }
                    if (data.start_time) {
                        this.startTime = new Date(data.start_time);
                    }
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
        }
    });
});

// Initialize app store when page loads
document.addEventListener('DOMContentLoaded', () => {
    Alpine.store('app').init();
});
