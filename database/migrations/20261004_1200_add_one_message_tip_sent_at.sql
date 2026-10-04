-- Many SMS contributors log a sighting over three messages (photo, then plate,
-- then borough), which costs us two extra inbound and two extra outbound Twilio
-- messages per sighting. After a multi-message submission we append a tip that
-- the whole thing fits in one text ("702788 in Brooklyn" alongside the photo).
--
-- one_message_tip_sent_at rate-limits that tip to once per 30 days per
-- contributor. It is claimed with a single UPDATE ... RETURNING so concurrent
-- webhooks can't both send it.
ALTER TABLE contributors ADD COLUMN IF NOT EXISTS one_message_tip_sent_at TIMESTAMPTZ;
