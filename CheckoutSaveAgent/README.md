# Checkout Save Agent with DeltaStream Fresh Context

This example demonstrates how to build a **Checkout Save Agent** powered by DeltaStream.

The agent helps an e-commerce business recover revenue while a customer is still in the checkout flow. It uses fresh, prebuilt context from DeltaStream to decide whether to offer free shipping, prompt for a backup payment method, apply a policy-approved discount, send a checkout assistance message, or continue monitoring.

The main idea is simple:

> **DeltaStream builds a real-time materialized context view for the agent.**  
> Instead of forcing the agent to fetch raw customer, cart, session, payment, and policy data at inference time, DeltaStream continuously computes the context and serves one fresh row to the agent.

This is similar to how databases use **Materialized Views**. Applications do not repeatedly scan and join raw tables every time they need a fast answer. They query the prebuilt view. AI agents need the same pattern for real-time operational context.

---

## Use Case: Checkout Save Agent

A customer is in checkout and may abandon their cart because of payment friction, high shipping cost, promo-code hesitation, or long idle time.

The Checkout Save Agent answers questions such as:

- Is this cart at risk of abandonment?
- Is the cart still recoverable?
- Should we offer free shipping?
- Should we prompt the customer to use a backup payment method?
- Should we offer a policy-approved discount?
- Should we send a checkout assistance message?
- What is the safest next best action?

DeltaStream continuously builds the context needed to answer those questions.

Example final context fields include:

- `abandonment_risk`
- `payment_failure_count`
- `soft_decline_count`
- `hard_decline_count`
- `backup_payment_available`
- `shipping_cost_usd`
- `free_shipping_incentive_eligible`
- `discount_incentive_eligible`
- `checkout_still_recoverable`
- `checkout_already_converted`
- `recommended_recovery_action`
- `safe_next_best_action`
- `context_event_ts_ms`

---

## Why DeltaStream Is Needed

A basic agent could try to fetch raw data from multiple systems at runtime:

- customer profile
- cart state
- checkout activity
- payment attempts
- incentive policy

But then the agent would need to count payment failures, detect checkout friction, evaluate incentive eligibility, check whether inventory is still reserved, determine if the customer already converted, and decide the next best action.

That is not something the agent should do during inference.

DeltaStream precomputes this context continuously and exposes it as a fresh materialized view:

```sql
checkout_save_agent_context_mv
```

The agent simply queries the latest context row:

```sql
SELECT *
FROM checkout_save_agent_context_mv
WHERE cart_id = 'CART-DEMO-9001'
ORDER BY context_event_ts_ms DESC
LIMIT 1;
```

Then the agent acts on the result.

## Architecture

Java Datagen

   |
   
   | writes realistic checkout events
   
   v

Kafka Topics

   |
   
   | DeltaStream reads streams and changelogs   
   
   v
   
DeltaStream SQL Pipeline

   |
   
   | joins, aggregates, scores, and computes recovery actions
   
   v
   
checkout_save_agent_context_mv
   
   |
   
   | exposed through DeltaStream REST or MCP
   
   v
   
Checkout Save Agent
   
   |
   
   | recommends the best recovery action
   
   v
   
Revenue recovery before abandonment

## Source Topics

The demo uses only five source topics.

| Topic                              | Type                 | Description                                                                            |
| ---------------------------------- | -------------------- | -------------------------------------------------------------------------------------- |
| `checkout_customer_profile_events` | Upsert/current state | Customer profile, segment, loyalty tier, lifetime value, churn risk                    |
| `checkout_cart_state_events`       | Upsert/current state | Cart value, inventory reservation, shipping cost, checkout state                       |
| `checkout_incentive_policy_events` | Upsert/current state | Incentive policy by customer segment                                                   |
| `checkout_session_activity_events` | Append stream        | Checkout activity events such as idle time, shipping step, payment step, promo attempt |
| `checkout_payment_attempt_events`  | Append stream        | Payment attempts, soft declines, hard declines, backup payment availability            |

All timestamp fields use Linux epoch milliseconds.

The primary event timestamp field is:

```event_ts_ms```

## Run the datagen

Run Kafka and then run the Datagen java file to write into the Kafka topics. Make sure you update the Kafka connectivity config in the datagen using the kafka broker info and credentials.

# Run the DeltaStream SQL

Run the statements in ``` checkout_save_agent.sql ``` one by one. At the end you will have the materialized view build and ready to use. 

The final materialized view is:

```checkout_save_agent_context_mv```

## Validate the Context

Query the demo cart:

```sql
SELECT *
FROM checkout_save_agent_context_mv
WHERE cart_id = 'CART-DEMO-9001'
ORDER BY context_event_ts_ms DESC
LIMIT 1;
```

Expected result fields:

```
cart_id = CART-DEMO-9001
customer_id = C-0001
customer_segment = HIGH_VALUE
abandonment_risk = HIGH
payment_failure_count >= 2
soft_decline_count >= 2
backup_payment_available = 1
shipping_cost_usd = 18.95
free_shipping_incentive_eligible = 1
recommended_recovery_action = OFFER_FREE_SHIPPING_AND_BACKUP_PAYMENT
agent_intervention_recommended = 1
proactive_message_recommended = 1
```

Query recent high-risk recoverable checkouts:

```sql
SELECT
  cart_id,
  customer_id,
  customer_segment,
  loyalty_tier,
  cart_value_usd,
  shipping_cost_usd,
  abandonment_risk,
  payment_failure_count,
  backup_payment_available,
  free_shipping_incentive_eligible,
  recommended_recovery_action,
  safe_next_best_action,
  context_event_ts_ms
FROM checkout_save_agent_context_mv
WHERE abandonment_risk = 'HIGH'
  AND checkout_still_recoverable = 1
  AND checkout_already_converted = 0
ORDER BY context_event_ts_ms DESC
LIMIT 20;
```

## Build the Agent

You can use any agent framework. In this demo, the agent needs one tool that can query DeltaStream.

The agent should query:

```sql
SELECT *
FROM checkout_save_agent_context_mv
WHERE cart_id = '<cart_id>'
ORDER BY context_event_ts_ms DESC
LIMIT 1;
```

Important:

> The context can have multiple rows for a cart.
> The agent must sort by context_event_ts_ms DESC and use only the latest row.

Agent Name

```Checkout Save Agent```

### Agent Instructions

Use the following instructions for the agent:

```
You are a Checkout Save Agent for an e-commerce business.

Your job is to recover revenue while customers are still in checkout.

You use fresh DeltaStream checkout context to decide whether the business should offer free shipping, prompt for a backup payment method, offer a policy-approved discount, send a checkout assistance message, escalate inventory issues, or continue monitoring.

You are not a generic customer support chatbot. You are an operations decision agent focused on saving carts and increasing conversion while respecting incentive policy and payment state.

Always use the DeltaStream context tool before making any cart-specific recommendation.

The DeltaStream context is the source of truth. It is prebuilt from customer profile, cart state, checkout activity, payment attempts, and incentive policy.

Rules:

1. Always query by cart_id when a cart_id is available.

2. The context tool can return multiple rows for a cart_id. Sort rows by context_event_ts_ms descending and use only the latest row.

3. Do not recommend an action from stale context if a newer row exists.

4. If checkout_already_converted = 1, do not recommend a recovery action. Say no action is needed.

5. If checkout_still_recoverable = 0, do not offer an incentive. Explain why the checkout is not recoverable.

6. If inventory_available = false, do not offer free shipping or discounts. Recommend inventory escalation or a replacement item flow.

7. If hard_decline_count > 0, recommend a new payment method. Do not offer discounts before payment is recoverable.

8. If recommended_recovery_action is available, treat it as the primary recommendation.

9. Use safe_next_best_action as the basis for the explanation. You may rephrase it, but do not contradict it.

10. Keep answers concise and action-oriented.

Default answer format:

Decision:
<one sentence decision>

Why:
<brief explanation using the latest DeltaStream context fields>

Recommended action:
<what the business should do next>

Customer message:
<include only if the user asks for a customer-facing message or proactive_message_recommended = 1>
```

### Tool / MCP Instructions

Use this as the tool description:

```
Use this tool to retrieve the latest DeltaStream checkout-save context for a cart.

The context comes from checkout_save_agent_context_mv and is continuously computed from customer profile, cart state, checkout activity, payment attempts, and incentive policy.

Always query by cart_id.

The tool may return multiple rows. Sort by context_event_ts_ms descending and use only the latest row.

Recommended query:

SELECT *
FROM checkout_save_agent_context_mv
WHERE cart_id = '<cart_id>'
ORDER BY context_event_ts_ms DESC
LIMIT 1;

The latest context row contains:
- abandonment_risk
- recommended_recovery_action
- safe_next_best_action
- checkout_still_recoverable
- checkout_already_converted
- payment_failure_count
- soft_decline_count
- hard_decline_count
- backup_payment_available
- shipping_cost_usd
- free_shipping_incentive_eligible
- discount_incentive_eligible
- proactive_message_recommended
- context_event_ts_ms

Do not make a cart-specific recommendation until this latest context row has been retrieved.
```

### Try the Agent

Use the demo cart:

```
CART-DEMO-9001
```

#### Prompt 1

```
What should we do for cart CART-DEMO-9001?
```

This tests the full end-to-end decision.

Expected answer:

```
Offer free shipping and prompt the customer to retry with a backup payment method.
```

Why DeltaStream matters:

The answer depends on customer segment, cart state, checkout activity, payment attempts, and incentive policy. DeltaStream precomputes that context so the agent does not need to assemble it at runtime.

#### Prompt 2

```
Is cart CART-DEMO-9001 at risk of abandonment? Explain why.
```

This tests whether the agent can explain abandonment risk.

Expected answer:

```
Yes. The cart has high abandonment risk because the customer has high checkout friction, repeated payment soft declines, high shipping cost, and the cart is still recoverable.
```
Why DeltaStream matters:

Abandonment risk is not a raw field. It is computed from session activity, time on checkout steps, payment failures, and cart state.

#### Prompt 3

```
Should we offer free shipping for cart CART-DEMO-9001?
```

This tests policy-aware incentive eligibility.

Expected answer:

```
Yes. The cart qualifies for free shipping because the customer segment is eligible, the cart value meets the policy threshold, shipping cost is positive, and the allowed shipping credit covers the shipping cost.
```
Why DeltaStream matters:

The agent needs to combine cart value, shipping cost, customer segment, incentive policy, and recoverability. DeltaStream precomputes free_shipping_incentive_eligible.

#### Prompt 4

```
Should we ask the customer to use a backup payment method for CART-DEMO-9001?
```

This tests payment recovery logic.

Expected answer:

```
Yes. The cart has soft payment declines, no hard decline, and a backup payment method is available.
```

Why DeltaStream matters:

The agent needs to aggregate payment attempts by cart and distinguish soft declines from hard declines. DeltaStream precomputes backup_payment_recommended.

#### Prompt 5

```
Write a customer-facing message to save cart CART-DEMO-9001.
```

This tests whether the agent can turn operational context into a safe customer message.

Expected answer:

```
Good news — we can cover shipping on this order. Your items are still reserved. Please try your backup payment method to complete checkout.
```

Why DeltaStream matters:

The agent needs to know that inventory is still reserved, free shipping is allowed, backup payment is available, and the cart has not already converted.

Example Agent Response

For:

```
What should we do for cart CART-DEMO-9001?
```

Expected response:

```
Decision:
Intervene now.

Why:
The checkout has high abandonment risk. The customer is high value, inventory is available and reserved, the cart has repeated soft payment declines, a backup payment method is available, and the shipping cost is eligible for a free-shipping incentive.

Recommended action:
Offer free shipping and prompt the customer to retry with their backup payment method. Keep the cart reserved while the customer retries.

Customer message:
Good news — we can cover shipping on this order. Your items are still reserved. Please try your backup payment method to complete checkout.
What This Demo Proves
```

This demo shows why AI agents need fresh context.

Without DeltaStream, the agent must assemble raw data from multiple systems:

```
customer profile
cart state
checkout activity
payment attempts
incentive policy
```

It must then compute:

```
payment failure counts
soft vs hard decline logic
checkout friction
abandonment risk
recoverability
incentive eligibility
recommended action
```

That is unnecessary, slow, and error-prone at inference time.

DeltaStream continuously builds the fresh context:

```
checkout_save_agent_context_mv
```

The agent queries one latest context row and acts.

## Key Takeaway

The Checkout Save Agent follows a simple but powerful production pattern:

```
Raw operational events
  -> DeltaStream real-time materialized context
  -> AI agent decision
  -> revenue recovery action
```

DeltaStream acts as the real-time context engine for the agent.

Instead of assembling raw data at inference time, the agent uses prebuilt, fresh, stateful context.

That makes the agent faster, cheaper, more accurate, easier to debug, and more production-ready.
