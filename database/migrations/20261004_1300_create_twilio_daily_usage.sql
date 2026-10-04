-- Daily Twilio usage totals by billing category, pulled from the Usage Records
-- API (/Usage/Records/Daily) by the sync_twilio_usage Modal job. Used to track
-- Twilio $ per submission on the unlisted /admin-stats page.
--
-- One row per (UTC day, category). Twilio's categories nest (e.g. "sms" rolls up
-- "sms-inbound" and "sms-outbound", and "totalprice" is the account total), so
-- never SUM(price) across all categories — pick the rollup or the leaves you want.
-- Categories with zero count, usage and price for a day are not stored.
CREATE TABLE IF NOT EXISTS twilio_daily_usage (
    usage_date DATE NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    count NUMERIC,
    count_unit TEXT,
    usage NUMERIC,
    usage_unit TEXT,
    price NUMERIC,
    price_unit TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (usage_date, category)
);
