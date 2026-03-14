-- Daily Portfolio Ledger
-- Tracks start-of-day value, 5:30 PM snapshot value, and daily P&L
-- Used by improvement cycle to evaluate daily performance and optimise

CREATE TABLE IF NOT EXISTS daily_portfolio_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL UNIQUE,
    start_value DECIMAL(20, 8) NOT NULL,        -- previous day's end value (or initial capital)
    end_value DECIMAL(20, 8) NOT NULL,           -- 5:30 PM portfolio snapshot
    daily_pnl DECIMAL(20, 8) NOT NULL,           -- end_value - start_value
    daily_pnl_pct DECIMAL(10, 4) NOT NULL,       -- daily_pnl / start_value * 100
    realized_pnl DECIMAL(20, 8) DEFAULT 0,       -- realized from closed trades today
    unrealized_pnl DECIMAL(20, 8) DEFAULT 0,     -- open position unrealized P&L
    total_trades INT DEFAULT 0,
    wins INT DEFAULT 0,
    losses INT DEFAULT 0,
    win_rate DECIMAL(5, 4) DEFAULT 0,
    main_pnl DECIMAL(20, 8) DEFAULT 0,           -- main trading strategy P&L
    meme_pnl DECIMAL(20, 8) DEFAULT 0,           -- meme coin P&L
    fees_total DECIMAL(20, 8) DEFAULT 0,          -- total fees paid
    status VARCHAR(20) NOT NULL DEFAULT 'NO_DATA', -- PROFIT, LOSS, STAGNANT, NO_DATA
    improvement_action TEXT,                       -- what the DGM/seed improver did after evaluating
    improvement_result TEXT,                       -- outcome of the improvement action
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_daily_ledger_date ON daily_portfolio_ledger(date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_ledger_status ON daily_portfolio_ledger(status);

-- Auto-update trigger
CREATE TRIGGER update_daily_ledger_updated_at BEFORE UPDATE ON daily_portfolio_ledger
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
