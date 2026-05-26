CREATE CHANGELOG checkout_customer_profile_cl (
  customer_id VARCHAR,
  customer_name VARCHAR,
  customer_segment VARCHAR,
  loyalty_tier VARCHAR,
  home_zip VARCHAR,
  lifetime_value_usd DOUBLE,
  prior_purchase_count INTEGER,
  churn_risk_band VARCHAR,
  support_issue_open_count INTEGER,
  profile_record_state VARCHAR,
  profile_version BIGINT,
  event_ts_ms BIGINT,
  PRIMARY KEY (customer_id)
) WITH (
  'topic' = 'checkout_customer_profile_events',
  'value.format' = 'json',
  'key.format' = 'primitive',
  'timestamp' = 'event_ts_ms',
  'enable.upsert.mode' = true
);


CREATE CHANGELOG checkout_cart_state_cl (
  cart_id VARCHAR,
  session_id VARCHAR,
  customer_id VARCHAR,
  primary_sku_id VARCHAR,
  primary_product_name VARCHAR,
  category_name VARCHAR,
  item_count INTEGER,
  cart_value_usd DOUBLE,
  gross_margin_usd DOUBLE,
  shipping_cost_usd DOUBLE,
  tax_amount_usd DOUBLE,
  inventory_available BOOLEAN,
  inventory_reserved BOOLEAN,
  inventory_reserved_until_ts_ms BIGINT,
  cart_record_state VARCHAR,
  cart_update_reason VARCHAR,
  event_ts_ms BIGINT,
  PRIMARY KEY (cart_id)
) WITH (
  'topic' = 'checkout_cart_state_events',
  'value.format' = 'json',
  'key.format' = 'primitive',
  'timestamp' = 'event_ts_ms',
  'enable.upsert.mode' = true
);

CREATE CHANGELOG checkout_incentive_policy_cl (
  customer_segment VARCHAR,
  min_cart_value_usd DOUBLE,
  max_shipping_credit_usd DOUBLE,
  max_discount_percent DOUBLE,
  incentive_name VARCHAR,
  free_shipping_allowed BOOLEAN,
  discount_allowed BOOLEAN,
  policy_record_state VARCHAR,
  policy_version BIGINT,
  event_ts_ms BIGINT,
  PRIMARY KEY (customer_segment)
) WITH (
  'topic' = 'checkout_incentive_policy_events',
  'value.format' = 'json',
  'key.format' = 'primitive',
  'timestamp' = 'event_ts_ms',
  'enable.upsert.mode' = true
);

CREATE STREAM checkout_payment_attempt_s (
  payment_attempt_id VARCHAR,
  cart_id VARCHAR,
  customer_id VARCHAR,
  payment_amount_usd DOUBLE,
  payment_method_family VARCHAR,
  payment_result_code VARCHAR,
  payment_authorized BOOLEAN,
  decline_category VARCHAR,
  backup_payment_available BOOLEAN,
  payment_provider VARCHAR,
  event_ts_ms BIGINT
) WITH (
  'topic' = 'checkout_payment_attempt_events',
  'value.format' = 'json',
  'key.format' = 'primitive',
  'key.type' = 'VARCHAR',
  'timestamp' = 'event_ts_ms'
);

CREATE CHANGELOG checkout_activity_by_cart_cl WITH (
  'topic' = 'checkout_ctx_activity_by_cart_cl',
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  cart_id,

  MAX(session_id) AS latest_session_id,
  MAX(customer_id) AS activity_customer_id,

  COUNT(*) AS activity_event_count,
  MAX(seconds_on_step) AS max_seconds_on_step,

  MAX(CASE WHEN friction_band = 'HIGH' THEN 1 ELSE 0 END) AS high_friction_observed,
  MAX(CASE WHEN friction_band = 'MEDIUM' THEN 1 ELSE 0 END) AS medium_friction_observed,

  MAX(CASE WHEN activity_name = 'CHECKOUT_IDLE' THEN 1 ELSE 0 END) AS checkout_idle_observed,
  MAX(CASE WHEN activity_name = 'SHIPPING_METHOD_VIEW' THEN 1 ELSE 0 END) AS shipping_step_observed,
  MAX(CASE WHEN activity_name = 'PAYMENT_STEP_VIEW' THEN 1 ELSE 0 END) AS payment_step_observed,
  MAX(CASE WHEN activity_name = 'PROMO_CODE_ATTEMPT' THEN 1 ELSE 0 END) AS promo_attempt_observed,

  MAX(device_channel) AS latest_device_channel,
  MAX(traffic_source) AS latest_traffic_source,
  MAX(page_url_path) AS latest_page_url_path,

  MAX(event_ts_ms) AS activity_event_ts_ms

FROM checkout_session_activity_s
GROUP BY cart_id;


CREATE CHANGELOG checkout_payment_by_cart_cl WITH (
  'topic' = 'checkout_ctx_payment_by_cart_cl',
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  cart_id,

  MAX(customer_id) AS payment_customer_id,

  COUNT(*) AS payment_attempt_count,

  SUM(CASE
    WHEN payment_authorized = false
    THEN 1 ELSE 0
  END) AS payment_failure_count,

  SUM(CASE
    WHEN decline_category = 'SOFT_DECLINE'
    THEN 1 ELSE 0
  END) AS soft_decline_count,

  SUM(CASE
    WHEN decline_category = 'HARD_DECLINE'
    THEN 1 ELSE 0
  END) AS hard_decline_count,

  MAX(CASE
    WHEN payment_authorized = true
    THEN 1 ELSE 0
  END) AS payment_authorized_observed,

  MAX(CASE
    WHEN backup_payment_available = true
    THEN 1 ELSE 0
  END) AS backup_payment_available,

  MAX(payment_result_code) AS latest_payment_result_code,
  MAX(decline_category) AS latest_decline_category,
  MAX(payment_provider) AS latest_payment_provider,
  MAX(event_ts_ms) AS payment_event_ts_ms

FROM checkout_payment_attempt_s
GROUP BY cart_id;


CREATE CHANGELOG checkout_cart_customer_cl WITH (
  'topic' = 'checkout_ctx_cart_customer_cl',
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  c.cart_id,
  c.customer_id,

  c.session_id,
  c.primary_sku_id,
  c.primary_product_name,
  c.category_name,
  c.item_count,
  c.cart_value_usd,
  c.gross_margin_usd,
  c.shipping_cost_usd,
  c.tax_amount_usd,
  c.inventory_available,
  c.inventory_reserved,
  c.inventory_reserved_until_ts_ms,
  c.cart_record_state,
  c.cart_update_reason,
  c.event_ts_ms AS cart_event_ts_ms,

  p.customer_id AS p_customer_id,
  p.customer_name,
  p.customer_segment,
  p.loyalty_tier,
  p.home_zip,
  p.lifetime_value_usd,
  p.prior_purchase_count,
  p.churn_risk_band,
  p.support_issue_open_count,
  p.profile_record_state,
  p.profile_version,
  p.event_ts_ms AS customer_event_ts_ms

FROM checkout_cart_state_cl c
JOIN checkout_customer_profile_cl p
  ON c.customer_id = p.customer_id;


  CREATE CHANGELOG checkout_cart_policy_cl WITH (
  'topic' = 'checkout_ctx_cart_policy_cl',
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  cc.cart_id,
  cc.customer_id,
  cc.customer_segment,

  cc.session_id,
  cc.primary_sku_id,
  cc.primary_product_name,
  cc.category_name,
  cc.item_count,
  cc.cart_value_usd,
  cc.gross_margin_usd,
  cc.shipping_cost_usd,
  cc.tax_amount_usd,
  cc.inventory_available,
  cc.inventory_reserved,
  cc.inventory_reserved_until_ts_ms,
  cc.cart_record_state,
  cc.cart_update_reason,
  cc.cart_event_ts_ms,

  cc.customer_segment AS cc_customer_segment,
  cc.customer_name,
  cc.loyalty_tier,
  cc.home_zip,
  cc.lifetime_value_usd,
  cc.prior_purchase_count,
  cc.churn_risk_band,
  cc.support_issue_open_count,
  cc.profile_record_state,
  cc.profile_version,
  cc.customer_event_ts_ms,

  cc.p_customer_id AS cc_p_customer_id,
  pol.customer_segment AS pol_customer_segment,
  pol.min_cart_value_usd,
  pol.max_shipping_credit_usd,
  pol.max_discount_percent,
  pol.incentive_name,
  pol.free_shipping_allowed,
  pol.discount_allowed,
  pol.policy_record_state,
  pol.policy_version,
  pol.event_ts_ms AS policy_event_ts_ms

FROM checkout_cart_customer_cl cc
JOIN checkout_incentive_policy_cl pol
  ON cc.customer_segment = pol.customer_segment;





  CREATE CHANGELOG checkout_cart_activity_enriched_cl WITH (
  'topic' = 'checkout_ctx_cart_activity_enriched_cl',
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  cp.cart_id,
  cp.customer_id,
  cp.customer_segment,

  cp.session_id,
  cp.primary_sku_id,
  cp.primary_product_name,
  cp.category_name,
  cp.item_count,
  cp.cart_value_usd,
  cp.gross_margin_usd,
  cp.shipping_cost_usd,
  cp.tax_amount_usd,
  cp.inventory_available,
  cp.inventory_reserved,
  cp.inventory_reserved_until_ts_ms,
  cp.cart_record_state,
  cp.cart_update_reason,
  cp.cart_event_ts_ms,

  cp.cc_p_customer_id AS cp_cc_p_customer_id,
  cp.pol_customer_segment AS cp_pol_customer_segment,
  cp.customer_name,
  cp.loyalty_tier,
  cp.home_zip,
  cp.lifetime_value_usd,
  cp.prior_purchase_count,
  cp.churn_risk_band,
  cp.support_issue_open_count,
  cp.profile_record_state,
  cp.profile_version,
  cp.customer_event_ts_ms,

  cp.min_cart_value_usd,
  cp.max_shipping_credit_usd,
  cp.max_discount_percent,
  cp.incentive_name,
  cp.free_shipping_allowed,
  cp.discount_allowed,
  cp.policy_record_state,
  cp.policy_version,
  cp.policy_event_ts_ms,

  act.cart_id AS act_cart_id,
  act.latest_session_id AS activity_session_id,
  act.activity_customer_id,
  act.activity_event_count,
  act.max_seconds_on_step,
  act.high_friction_observed,
  act.medium_friction_observed,
  act.checkout_idle_observed,
  act.shipping_step_observed,
  act.payment_step_observed,
  act.promo_attempt_observed,
  act.latest_device_channel,
  act.latest_traffic_source,
  act.latest_page_url_path,
  act.activity_event_ts_ms

FROM checkout_cart_policy_cl cp
JOIN checkout_activity_by_cart_cl act
  ON cp.cart_id = act.cart_id;


  CREATE CHANGELOG checkout_context_enriched_cl WITH (
  'topic' = 'checkout_ctx_context_enriched_cl',
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  ca.cart_id,
  ca.customer_id,
  ca.customer_segment,

  ca.session_id,
  ca.primary_sku_id,
  ca.primary_product_name,
  ca.category_name,
  ca.item_count,
  ca.cart_value_usd,
  ca.gross_margin_usd,
  ca.shipping_cost_usd,
  ca.tax_amount_usd,
  ca.inventory_available,
  ca.inventory_reserved,
  ca.inventory_reserved_until_ts_ms,
  ca.cart_record_state,
  ca.cart_update_reason,
  ca.cart_event_ts_ms,

  ca.customer_name,
  ca.loyalty_tier,
  ca.home_zip,
  ca.lifetime_value_usd,
  ca.prior_purchase_count,
  ca.churn_risk_band,
  ca.support_issue_open_count,
  ca.profile_record_state,
  ca.profile_version,
  ca.customer_event_ts_ms,

  ca.min_cart_value_usd,
  ca.max_shipping_credit_usd,
  ca.max_discount_percent,
  ca.incentive_name,
  ca.free_shipping_allowed,
  ca.discount_allowed,
  ca.policy_record_state,
  ca.policy_version,
  ca.policy_event_ts_ms,

  ca.activity_session_id,
  ca.activity_customer_id,
  ca.activity_event_count,
  ca.max_seconds_on_step,
  ca.high_friction_observed,
  ca.medium_friction_observed,
  ca.checkout_idle_observed,
  ca.shipping_step_observed,
  ca.payment_step_observed,
  ca.promo_attempt_observed,
  ca.latest_device_channel,
  ca.latest_traffic_source,
  ca.latest_page_url_path,
  ca.activity_event_ts_ms,
  ca.cp_cc_p_customer_id AS ca_cp_cc_p_customer_id,
  ca.cp_pol_customer_segment AS ca_cp_pol_customer_segment,
  ca.act_cart_id AS ca_act_cart_id,

  pay.cart_id AS pay_cart_id,
  pay.payment_customer_id,
  pay.payment_attempt_count,
  pay.payment_failure_count,
  pay.soft_decline_count,
  pay.hard_decline_count,
  pay.payment_authorized_observed,
  pay.backup_payment_available,
  pay.latest_payment_result_code,
  pay.latest_decline_category,
  pay.latest_payment_provider,
  pay.payment_event_ts_ms

FROM checkout_cart_activity_enriched_cl ca
JOIN checkout_payment_by_cart_cl pay
  ON ca.cart_id = pay.cart_id;


  CREATE CHANGELOG checkout_save_context_cl WITH (
  'topic' = 'checkout_ctx_save_context_final_cl',
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  cart_id,
  customer_id,
  customer_segment,

  session_id,
  primary_sku_id,
  primary_product_name,
  category_name,
  item_count,
  cart_value_usd,
  gross_margin_usd,
  shipping_cost_usd,
  tax_amount_usd,
  inventory_available,
  inventory_reserved,
  inventory_reserved_until_ts_ms,
  cart_record_state,
  cart_update_reason,

  customer_name,
  loyalty_tier,
  home_zip,
  lifetime_value_usd,
  prior_purchase_count,
  churn_risk_band,
  support_issue_open_count,

  min_cart_value_usd,
  max_shipping_credit_usd,
  max_discount_percent,
  incentive_name,
  free_shipping_allowed,
  discount_allowed,

  activity_event_count,
  max_seconds_on_step,
  high_friction_observed,
  medium_friction_observed,
  checkout_idle_observed,
  shipping_step_observed,
  payment_step_observed,
  promo_attempt_observed,
  latest_device_channel,
  latest_traffic_source,
  latest_page_url_path,

  payment_attempt_count,
  payment_failure_count,
  soft_decline_count,
  hard_decline_count,
  payment_authorized_observed,
  backup_payment_available,
  latest_payment_result_code,
  latest_decline_category,
  latest_payment_provider,
  ca_cp_cc_p_customer_id,
  ca_cp_pol_customer_segment,
  ca_act_cart_id,
  pay_cart_id,

  CASE
    WHEN inventory_available = true
     AND inventory_reserved = true
     AND cart_record_state IN ('CHECKOUT_ACTIVE', 'PAYMENT_RETRY', 'ABANDONMENT_RISK')
    THEN 1 ELSE 0
  END AS checkout_still_recoverable,

  CASE
    WHEN payment_authorized_observed = 1
    THEN 1 ELSE 0
  END AS checkout_already_converted,

  CASE
    WHEN cart_value_usd >= min_cart_value_usd
     AND free_shipping_allowed = true
     AND shipping_cost_usd > 0
     AND max_shipping_credit_usd >= shipping_cost_usd
    THEN 1 ELSE 0
  END AS free_shipping_incentive_eligible,

  CASE
    WHEN cart_value_usd >= min_cart_value_usd
     AND discount_allowed = true
     AND max_discount_percent > 0
    THEN 1 ELSE 0
  END AS discount_incentive_eligible,

  CASE
    WHEN backup_payment_available = 1
     AND soft_decline_count > 0
     AND hard_decline_count = 0
    THEN 1 ELSE 0
  END AS backup_payment_recommended,

  CASE
    WHEN high_friction_observed = 1
      OR checkout_idle_observed = 1
      OR max_seconds_on_step >= 90
      OR payment_failure_count >= 2
      OR shipping_cost_usd >= 12.0
    THEN 'HIGH'
    WHEN medium_friction_observed = 1
      OR payment_failure_count = 1
      OR promo_attempt_observed = 1
      OR max_seconds_on_step >= 45
    THEN 'MEDIUM'
    ELSE 'LOW'
  END AS abandonment_risk,

  CASE
    WHEN payment_authorized_observed = 1
    THEN 'NO_ACTION_ALREADY_CONVERTED'

    WHEN inventory_available = false
    THEN 'ESCALATE_INVENTORY_UNAVAILABLE'

    WHEN hard_decline_count > 0
    THEN 'REQUEST_NEW_PAYMENT_METHOD'

    WHEN soft_decline_count > 0
     AND backup_payment_available = 1
     AND free_shipping_allowed = true
     AND shipping_cost_usd > 0
     AND max_shipping_credit_usd >= shipping_cost_usd
    THEN 'OFFER_FREE_SHIPPING_AND_BACKUP_PAYMENT'

    WHEN soft_decline_count > 0
     AND backup_payment_available = 1
    THEN 'PROMPT_BACKUP_PAYMENT_METHOD'

    WHEN shipping_cost_usd > 0
     AND free_shipping_allowed = true
     AND max_shipping_credit_usd >= shipping_cost_usd
    THEN 'OFFER_FREE_SHIPPING'

    WHEN promo_attempt_observed = 1
     AND discount_allowed = true
     AND max_discount_percent > 0
    THEN 'OFFER_POLICY_APPROVED_DISCOUNT'

    WHEN checkout_idle_observed = 1
      OR max_seconds_on_step >= 90
    THEN 'SEND_CHECKOUT_ASSISTANCE_MESSAGE'

    ELSE 'CONTINUE_MONITORING'
  END AS recommended_recovery_action,

  CASE
    WHEN payment_authorized_observed = 1
    THEN 'The checkout has already converted. No recovery action is needed.'

    WHEN inventory_available = false
    THEN 'Do not offer an incentive yet. Inventory is unavailable, so escalate or recommend a replacement item.'

    WHEN hard_decline_count > 0
    THEN 'Ask the customer to use a different payment method. Do not offer a discount before payment is recoverable.'

    WHEN soft_decline_count > 0
     AND backup_payment_available = 1
     AND free_shipping_allowed = true
     AND shipping_cost_usd > 0
     AND max_shipping_credit_usd >= shipping_cost_usd
    THEN 'Offer free shipping and prompt the customer to try their backup payment method. Keep the cart reserved while the customer retries.'

    WHEN soft_decline_count > 0
     AND backup_payment_available = 1
    THEN 'Prompt the customer to try their backup payment method and keep the cart reserved while they retry.'

    WHEN shipping_cost_usd > 0
     AND free_shipping_allowed = true
     AND max_shipping_credit_usd >= shipping_cost_usd
    THEN 'Offer free shipping to reduce checkout friction and keep the customer moving.'

    WHEN promo_attempt_observed = 1
     AND discount_allowed = true
     AND max_discount_percent > 0
    THEN 'Offer the policy-approved discount and remind the customer that inventory is currently reserved.'

    WHEN checkout_idle_observed = 1
      OR max_seconds_on_step >= 90
    THEN 'Send a checkout assistance message and remind the customer that the cart is still reserved.'

    ELSE 'Continue monitoring the checkout session.'
  END AS safe_next_best_action,

  CASE
    WHEN payment_authorized_observed = 0
     AND inventory_available = true
     AND inventory_reserved = true
     AND (
       high_friction_observed = 1
       OR checkout_idle_observed = 1
       OR payment_failure_count > 0
       OR shipping_cost_usd >= 12.0
     )
    THEN 1 ELSE 0
  END AS agent_intervention_recommended,

  CASE
    WHEN payment_authorized_observed = 0
     AND customer_segment IN ('HIGH_VALUE', 'GROWTH')
     AND (
       high_friction_observed = 1
       OR payment_failure_count > 0
       OR checkout_idle_observed = 1
     )
    THEN 1 ELSE 0
  END AS proactive_message_recommended,

  CASE
    WHEN cart_event_ts_ms >= activity_event_ts_ms
     AND cart_event_ts_ms >= payment_event_ts_ms
     AND cart_event_ts_ms >= customer_event_ts_ms
     AND cart_event_ts_ms >= policy_event_ts_ms
    THEN cart_event_ts_ms
    WHEN activity_event_ts_ms >= payment_event_ts_ms
     AND activity_event_ts_ms >= customer_event_ts_ms
     AND activity_event_ts_ms >= policy_event_ts_ms
    THEN activity_event_ts_ms
    WHEN payment_event_ts_ms >= customer_event_ts_ms
     AND payment_event_ts_ms >= policy_event_ts_ms
    THEN payment_event_ts_ms
    WHEN customer_event_ts_ms >= policy_event_ts_ms
    THEN customer_event_ts_ms
    ELSE policy_event_ts_ms
  END AS context_event_ts_ms

FROM checkout_context_enriched_cl;


CREATE MATERIALIZED VIEW checkout_save_agent_context_mv AS
SELECT
  cart_id,
  customer_id,
  customer_segment,

  session_id,
  primary_sku_id,
  primary_product_name,
  category_name,
  item_count,
  cart_value_usd,
  gross_margin_usd,
  shipping_cost_usd,
  tax_amount_usd,
  inventory_available,
  inventory_reserved,
  inventory_reserved_until_ts_ms,
  cart_record_state,
  cart_update_reason,

  customer_name,
  loyalty_tier,
  home_zip,
  lifetime_value_usd,
  prior_purchase_count,
  churn_risk_band,
  support_issue_open_count,

  min_cart_value_usd,
  max_shipping_credit_usd,
  max_discount_percent,
  incentive_name,
  free_shipping_allowed,
  discount_allowed,

  activity_event_count,
  max_seconds_on_step,
  high_friction_observed,
  medium_friction_observed,
  checkout_idle_observed,
  shipping_step_observed,
  payment_step_observed,
  promo_attempt_observed,
  latest_device_channel,
  latest_traffic_source,
  latest_page_url_path,

  payment_attempt_count,
  payment_failure_count,
  soft_decline_count,
  hard_decline_count,
  payment_authorized_observed,
  backup_payment_available,
  latest_payment_result_code,
  latest_decline_category,
  latest_payment_provider,

  checkout_still_recoverable,
  checkout_already_converted,
  free_shipping_incentive_eligible,
  discount_incentive_eligible,
  backup_payment_recommended,
  abandonment_risk,
  recommended_recovery_action,
  safe_next_best_action,
  agent_intervention_recommended,
  proactive_message_recommended,
  ca_cp_cc_p_customer_id,
  ca_cp_pol_customer_segment,
  ca_act_cart_id,
  pay_cart_id,
  context_event_ts_ms

FROM checkout_save_context_cl;
