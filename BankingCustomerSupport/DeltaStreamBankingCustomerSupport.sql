-- Ledger updates (balance snapshots)
CREATE STREAM ledger_updates_stream (
  event_id VARCHAR,
  customer_id VARCHAR,
  account_id VARCHAR,
  available_balance DOUBLE,
  current_balance DOUBLE,
  ledger_balance DOUBLE,
  currency VARCHAR,
  updated_at BIGINT
)
WITH (
  'topic' = 'bank_support_ledger_updates',
  'value.format' = 'json',
  'timestamp'    = 'updated_at'
);


-- Authorization events (pending/settled/reversed)
CREATE STREAM auth_events_stream (
  event_id VARCHAR,
  customer_id VARCHAR,
  account_id VARCHAR,
  auth_id VARCHAR,
  merchant VARCHAR,
  amount DOUBLE,
  currency VARCHAR,
  status VARCHAR,
  expected_settlement_at BIGINT,
  created_at BIGINT
)
WITH (
  'topic' = 'bank_support_auth_events',
  'value.format' = 'json',
  'timestamp'    = 'created_at'
);


CREATE CHANGELOG auth_events_cl (
  event_id VARCHAR,
  customer_id VARCHAR,
  account_id VARCHAR,
  auth_id VARCHAR,
  merchant VARCHAR,
  amount DOUBLE,
  currency VARCHAR,
  status VARCHAR,
  expected_settlement_at BIGINT,
  created_at BIGINT,
  PRIMARY KEY(customer_id)
)
WITH (
  'topic' = 'bank_support_auth_events',
  'value.format' = 'json',
  'timestamp'    = 'created_at'
);



-- Transfers lifecycle
CREATE STREAM transfers_stream (
  event_id VARCHAR,
  customer_id VARCHAR,
  account_id VARCHAR,
  transfer_id VARCHAR,
  "type" VARCHAR,
  amount DOUBLE,
  currency VARCHAR,
  status VARCHAR,
  failure_reason VARCHAR,
  expected_eta BIGINT,
  tracking_ref VARCHAR,
  initiated_at BIGINT,
  updated_at BIGINT
)
WITH (
  'topic' = 'bank_support_transfers',
  'value.format' = 'json',
  'timestamp'    = 'initiated_at'
);


-- Transfers lifecycle
CREATE CHANGELOG transfers_cl (
  event_id VARCHAR,
  customer_id VARCHAR,
  account_id VARCHAR,
  transfer_id VARCHAR,
  "type" VARCHAR,
  amount DOUBLE,
  currency VARCHAR,
  status VARCHAR,
  failure_reason VARCHAR,
  expected_eta BIGINT,
  tracking_ref VARCHAR,
  initiated_at BIGINT,
  updated_at BIGINT,
  PRIMARY KEY(customer_id)
)
WITH (
  'topic' = 'bank_support_transfers',
  'value.format' = 'json',
  'timestamp'    = 'updated_at'
);

-- Holds
CREATE CHANGELOG holds_cl (
  event_id VARCHAR,
  customer_id VARCHAR,
  account_id VARCHAR,
  hold_id VARCHAR,
  reason_code VARCHAR,
  status VARCHAR,
  release_conditions VARCHAR,
  velocity_limit_per_hour INT,
  created_at BIGINT,
  updated_at BIGINT,
  PRIMARY KEY(customer_id)
)
WITH (
  'topic' = 'bank_support_holds',
  'value.format' = 'json',
  'timestamp'    = 'created_at'
);


-- Disputes
CREATE CHANGELOG disputes_cl (
  event_id VARCHAR,
  customer_id VARCHAR,
  account_id VARCHAR,
  dispute_id VARCHAR,
  related_auth_id VARCHAR,
  stage VARCHAR,
  provisional_credit_status VARCHAR,
  next_required_action VARCHAR,
  created_at BIGINT,
  updated_at BIGINT,
  PRIMARY KEY(customer_id)
)
WITH (
  'topic' = 'bank_support_disputes',
  'value.format' = 'json',
  'timestamp'    = 'created_at'
);


-- Notifications
CREATE STREAM notifications_stream (
  event_id VARCHAR,
  customer_id VARCHAR,
  channel VARCHAR,
  message_type VARCHAR,
  message VARCHAR,
  sent_at BIGINT
)
WITH (
  'topic' = 'bank_support_notifications',
  'value.format' = 'json',
  'timestamp'    = 'sent_at'
);

CREATE CHANGELOG notifications_cl (
  event_id VARCHAR,
  customer_id VARCHAR,
  channel VARCHAR,
  message_type VARCHAR,
  message VARCHAR,
  sent_at BIGINT,
  PRIMARY KEY(customer_id)
)
WITH (
  'topic' = 'bank_support_notifications',
  'value.format' = 'json',
  'timestamp'    = 'sent_at'
);

--=====================================================

CREATE MATERIALIZED VIEW bank_support_recent_transfer_stats_mv AS
SELECT
  window_start,
  window_end,
  customer_id,
  COUNT(*) AS transfer_events_30m,
  SUM(amount) AS transfer_amount_30m,
  MAX(updated_at) AS last_transfer_update_at
FROM TUMBLE(transfers_stream, SIZE 30 MINUTES)
GROUP BY window_start, window_end, customer_id;


CREATE MATERIALIZED VIEW bank_support_recent_auth_stats_mv AS
SELECT
  window_start,
  window_end,
  customer_id,
  COUNT(*) AS auth_events_30m,
  SUM(amount) AS auth_amount_30m,
  MAX(created_at) AS last_auth_event_at
FROM TUMBLE(auth_events_stream, SIZE 30 MINUTES)
GROUP BY window_start, window_end, customer_id;








CREATE STREAM bank_support_balances_transfer AS
SELECT
  b.customer_id,
  b.account_id,

  -- Balances
  b.available_balance,
  b.current_balance,
  b.ledger_balance,
  b.currency,
  b.updated_at,

  -- Most recent transfer (lifecycle)
  t.transfer_id,
  t."type" AS transfer_type,
  t.amount AS transfer_amount,
  t.status AS transfer_status,
  t.failure_reason AS transfer_failure_reason,
  t.expected_eta AS transfer_expected_eta,
  t.tracking_ref AS transfer_tracking_ref,
  t.initiated_at AS transfer_initiated_at,
  t.updated_at AS transfer_updated_at
FROM ledger_updates_stream b
LEFT JOIN transfers_cl t
  ON b.customer_id = t.customer_id
;

CREATE STREAM bank_support_balances_transfer_auth AS
SELECT 
  bt.customer_id,
  bt.account_id,

  -- Balances
  bt.available_balance,
  bt.current_balance,
  bt.ledger_balance,
  bt.currency,
  bt.updated_at,

  -- Most recent transfer (lifecycle)
  bt.transfer_id,
  bt.transfer_type,
  bt.transfer_amount,
  bt.transfer_status,
  bt.transfer_failure_reason,
  bt.transfer_expected_eta,
  bt.transfer_tracking_ref,
  bt.transfer_initiated_at,
  bt.transfer_updated_at,

  -- Most recent authorization (pending/settled/reversed)
  a.auth_id,
  a.merchant AS auth_merchant,
  a.amount AS auth_amount,
  a.status AS auth_status,
  a.expected_settlement_at AS auth_expected_settlement_at,
  a.created_at AS auth_created_at
FROM bank_support_balances_transfer bt
LEFT JOIN auth_events_cl a
  ON bt.customer_id = a.customer_id;


CREATE STREAM bank_support_balances_transfer_auth_hold AS
SELECT 
  bt.customer_id,
  bt.account_id,

  -- Balances
  bt.available_balance,
  bt.current_balance,
  bt.ledger_balance,
  bt.currency,
  bt.updated_at,

  -- Most recent transfer (lifecycle)
  bt.transfer_id,
  bt.transfer_type,
  bt.transfer_amount,
  bt.transfer_status,
  bt.transfer_failure_reason,
  bt.transfer_expected_eta,
  bt.transfer_tracking_ref,
  bt.transfer_initiated_at,
  bt.transfer_updated_at,

  -- Most recent authorization (pending/settled/reversed)
  bt.auth_id,
  bt.auth_merchant,
  bt.auth_amount,
  bt.auth_status,
  bt.auth_expected_settlement_at,
  bt.auth_created_at,

  -- Holds (latest by hold_id; agent can filter active)
  h.hold_id,
  h.reason_code AS hold_reason_code,
  h.status AS hold_status,
  h.release_conditions AS hold_release_conditions,
  h.velocity_limit_per_hour

FROM bank_support_balances_transfer_auth bt
LEFT JOIN holds_cl h
WITH
  ('source.idle.timeout.millis' = 1000)
  ON bt.customer_id = h.customer_id;


CREATE STREAM bank_support_balances_transfer_auth_hold_dispute AS
SELECT 
  bt.customer_id,
  bt.account_id,

  -- Balances
  bt.available_balance,
  bt.current_balance,
  bt.ledger_balance,
  bt.currency,
  bt.updated_at,

  -- Most recent transfer (lifecycle)
  bt.transfer_id,
  bt.transfer_type,
  bt.transfer_amount,
  bt.transfer_status,
  bt.transfer_failure_reason,
  bt.transfer_expected_eta,
  bt.transfer_tracking_ref,
  bt.transfer_initiated_at,
  bt.transfer_updated_at,

  -- Most recent authorization (pending/settled/reversed)
  bt.auth_id,
  bt.auth_merchant,
  bt.auth_amount,
  bt.auth_status,
  bt.auth_expected_settlement_at,
  bt.auth_created_at,

  -- Holds (latest by hold_id; agent can filter active)
  bt.hold_id,
  bt.hold_reason_code,
  bt.hold_status,
  bt.hold_release_conditions,
  bt.velocity_limit_per_hour,

  -- Disputes (latest by dispute_id; agent can filter open)
  d.dispute_id,
  d.stage AS dispute_stage,
  d.provisional_credit_status,
  d.next_required_action,
  d.updated_at AS dispute_updated_at

FROM bank_support_balances_transfer_auth_hold bt
LEFT JOIN disputes_cl d 
  WITH
  ('source.idle.timeout.millis' = 1000)
  ON bt.customer_id = d.customer_id;



--CREATE STREAM bank_support_balances_transfer_auth_hold_dispute_notification AS
CREATE MATERIALIZED VIEW support_context_mv AS
SELECT 
  bt.customer_id,
  bt.account_id,

  -- Balances
  bt.available_balance,
  bt.current_balance,
  bt.ledger_balance,
  bt.currency,
  bt.updated_at,

  -- Most recent transfer (lifecycle)
  bt.transfer_id,
  bt.transfer_type,
  bt.transfer_amount,
  bt.transfer_status,
  bt.transfer_failure_reason,
  bt.transfer_expected_eta,
  bt.transfer_tracking_ref,
  bt.transfer_initiated_at,
  bt.transfer_updated_at,

  -- Most recent authorization (pending/settled/reversed)
  bt.auth_id,
  bt.auth_merchant,
  bt.auth_amount,
  bt.auth_status,
  bt.auth_expected_settlement_at,
  bt.auth_created_at,

  -- Holds (latest by hold_id; agent can filter active)
  bt.hold_id,
  bt.hold_reason_code,
  bt.hold_status,
  bt.hold_release_conditions,
  bt.velocity_limit_per_hour,

  -- Disputes (latest by dispute_id; agent can filter open)
  bt.dispute_id,
  bt.dispute_stage,
  bt.provisional_credit_status,
  bt.next_required_action,
  bt.dispute_updated_at,

  -- Latest customer communication
  n.sent_at,
  n.message_type AS last_message_type,
  n.message AS last_message

FROM bank_support_balances_transfer_auth_hold_dispute bt
LEFT JOIN notifications_stream n 
  WITH
  ('source.idle.timeout.millis' = 1000)
  ON bt.customer_id = n.customer_id;





CREATE MATERIALIZED VIEW latest_transfer_per_customer_mv AS
SELECT
  customer_id,
  MAX(updated_at) AS max_transfer_updated_at
FROM transfers_stream
GROUP BY customer_id;

CREATE MATERIALIZED VIEW latest_auth_per_customer_mv AS
SELECT
  customer_id,
  MAX(created_at) AS max_auth_created_at
FROM auth_events_stream
GROUP BY customer_id;

CREATE MATERIALIZED VIEW latest_notification_per_customer_mv AS
SELECT
  customer_id,
  MAX(sent_at) AS last_notif_at
FROM notifications_stream
GROUP BY customer_id;

