-- User reports for objectionable content / abusive behavior.
-- Required by App Store Review Guideline 1.2 (UGC apps): all reports
-- must be actioned within 24 hours.
CREATE TABLE IF NOT EXISTS user_reports (
    id BIGSERIAL PRIMARY KEY,
    reporter_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    reported_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    resolution_note TEXT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_reports_reporter ON user_reports (reporter_id);
CREATE INDEX IF NOT EXISTS idx_user_reports_reported ON user_reports (reported_id);
CREATE INDEX IF NOT EXISTS idx_user_reports_status ON user_reports (status);
CREATE INDEX IF NOT EXISTS idx_user_reports_created_at ON user_reports (created_at DESC);
