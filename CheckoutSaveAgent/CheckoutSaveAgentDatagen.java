package io.deltastream.datagen.random.checkout;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.deltastream.datagen.random.util.Helper;
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.config.TopicConfig;

import java.lang.management.ManagementFactory;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.*;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Checkout Save Agent datagen.
 *
 * This generator simulates a realistic e-commerce checkout platform for 1,000 customers.
 *
 * Goals:
 * - Continuous long-running data generation.
 * - Restart-safe: stopping/restarting does not require clearing Kafka or DeltaStream context.
 * - Stable upsert records for customer profile, cart state, and incentive policy.
 * - Append-only events for session activity and payment attempts.
 * - All timestamps are Linux epoch milliseconds.
 * - Field names avoid common SQL keywords.
 *
 * Topics:
 * - checkout_customer_profile_events     upsert-style by customer_id
 * - checkout_cart_state_events           upsert-style by cart_id
 * - checkout_session_activity_events     append events by activity_id
 * - checkout_payment_attempt_events      append events by payment_attempt_id
 * - checkout_incentive_policy_events     upsert-style by customer_segment
 *
 * Repeatable demo case:
 * - customer_id = C-0001
 * - cart_id     = CART-DEMO-9001
 * - session_id  = SES-DEMO-9001
 *
 * Run:
 *   mvn clean package
 *   java -jar target/checkout-save-agent-datagen-1.0.0.jar localhost:9092 1000
 *
 * Args:
 *   arg0 = Kafka bootstrap servers, default localhost:9092
 *   arg1 = loop sleep ms, default 1000
 */
public class CheckoutSaveAgentDatagen {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Random RANDOM = new Random(42);

    private static final String TOPIC_CUSTOMER_PROFILE = "checkout_customer_profile_events";
    private static final String TOPIC_CART_STATE = "checkout_cart_state_events";
    private static final String TOPIC_SESSION_ACTIVITY = "checkout_session_activity_events";
    private static final String TOPIC_PAYMENT_ATTEMPT = "checkout_payment_attempt_events";
    private static final String TOPIC_INCENTIVE_POLICY = "checkout_incentive_policy_events";

    private static final int CUSTOMER_COUNT = 1000;

    private static final String DEMO_CUSTOMER_ID = "C-0001";
    private static final String DEMO_CART_ID = "CART-DEMO-9001";
    private static final String DEMO_SESSION_ID = "SES-DEMO-9001";

    private static final long PROCESS_START_MS = System.currentTimeMillis();
    private static final String PROCESS_ID = buildProcessId();

    private static final AtomicLong EVENT_SEQ = new AtomicLong(1);
    private static final AtomicLong CART_SEQ = new AtomicLong(1);
    private static final AtomicLong SESSION_SEQ = new AtomicLong(1);
    private static final AtomicLong PAYMENT_SEQ = new AtomicLong(1);

    private static final List<Customer> CUSTOMERS = buildCustomers();

    private static final List<Product> PRODUCTS = List.of(
            new Product("RUN-LTD-RED-10", "Limited Runner Red Size 10", "Footwear", 189.00, 52.0),
            new Product("RUN-LTD-BLK-10", "Limited Runner Black Size 10", "Footwear", 189.00, 51.0),
            new Product("HD-PHN-BLK", "Noise Canceling Headphones Black", "Electronics", 249.00, 38.0),
            new Product("BAG-TRV-GRY", "Travel Backpack Gray", "Travel", 99.00, 46.0),
            new Product("JKT-WTR-BLU-M", "Waterproof Jacket Blue Medium", "Apparel", 159.00, 44.0),
            new Product("WATCH-FIT-SLV", "Fitness Watch Silver", "Electronics", 229.00, 35.0),
            new Product("HOME-AIR-PUR", "Smart Air Purifier", "Home", 299.00, 41.0),
            new Product("TOY-DRONE-MINI", "Mini Camera Drone", "Toys", 149.00, 37.0)
    );

    private record Customer(
            String customerId,
            String customerName,
            String customerSegment,
            String loyaltyTier,
            String homeZip,
            double lifetimeValueUsd,
            int priorPurchaseCount,
            String churnRiskBand
    ) {}

    private record Product(
            String skuId,
            String productName,
            String categoryName,
            double unitPriceUsd,
            double grossMarginPercent
    ) {}

    public static void main(String[] args) throws Exception {
        String bootstrapServers = "Kafka Broker url";
        String KAFKA_API_KEY = "Your Kafka Key";
        String KAFKA_API_SECRET = "Your Kafka Secret";
        long sleepMs = args.length > 1 ? Long.parseLong(args[1]) : 1000L;

        Properties props = new Properties();
        props.put("bootstrap.servers", bootstrapServers);
        props.put("acks", "all");
        props.put("retries", 3);
        props.put("linger.ms", 10);
        props.put("compression.type", "snappy");
        props.put("key.serializer", "org.apache.kafka.common.serialization.StringSerializer");
        props.put("value.serializer", "org.apache.kafka.common.serialization.StringSerializer");
        props.put("retries", "3");
        props.put("linger.ms", "50");
        props.put("batch.size", "32768");
        props.put("security.protocol", "SASL_SSL");
        props.put("sasl.mechanism", "PLAIN");
        props.put("sasl.jaas.config", "org.apache.kafka.common.security.plain.PlainLoginModule required username=\"" + KAFKA_API_KEY + "\" password=\"" + KAFKA_API_SECRET + "\";");

        try (KafkaProducer<String, String> producer = new KafkaProducer<>(props)) {
            long nowMs = System.currentTimeMillis();

            emitAllCustomerProfiles(producer, nowMs);
            emitIncentivePolicies(producer, nowMs);

            System.out.printf(
                    "Checkout Save Agent datagen started. bootstrap=%s sleep_ms=%d customers=%d process_id=%s%n",
                    bootstrapServers,
                    sleepMs,
                    CUSTOMER_COUNT,
                    PROCESS_ID
            );

            long loopCounter = 0;

            while (true) {
                nowMs = System.currentTimeMillis();
                loopCounter++;

                // Emit small batches of upsert reference data periodically.
                if (loopCounter % 60 == 0) {
                    emitCustomerProfileRefreshBatch(producer, nowMs, 50);
                    emitIncentivePolicies(producer, nowMs);
                }

                // Always keep the demo case fresh and valid.
                emitDemoCheckoutCase(producer, nowMs);

                // Continuous realistic traffic.
                emitRandomCheckoutTraffic(producer, nowMs);

                producer.flush();
                Thread.sleep(sleepMs);
            }
        }
    }

    private static List<Customer> buildCustomers() {
        List<Customer> result = new ArrayList<>(CUSTOMER_COUNT);

        String[] firstNames = {
                "Avery", "Mia", "Daniel", "Priya", "Chris", "Nora", "Owen", "Lena", "Amir", "Sofia",
                "Ethan", "Olivia", "Noah", "Emma", "Lucas", "Isabella", "Mason", "Ava", "Logan", "Zoe"
        };

        String[] lastNames = {
                "Johnson", "Chen", "Reyes", "Patel", "Miller", "Wilson", "Davis", "Brown", "Singh", "Garcia",
                "Kim", "Nguyen", "Smith", "Lee", "Martinez", "Taylor", "Anderson", "Thomas", "Moore", "Clark"
        };

        String[] zips = {
                "90028", "90036", "94107", "10011", "60614", "73301", "98101", "30301", "80202", "02118"
        };

        for (int i = 1; i <= CUSTOMER_COUNT; i++) {
            String customerId = "C-" + String.format("%04d", i);
            String firstName = firstNames[(i - 1) % firstNames.length];
            String lastName = lastNames[(i * 7) % lastNames.length];
            String name = firstName + " " + lastName;
            String homeZip = zips[(i * 13) % zips.length];

            String segment;
            String loyaltyTier;
            double ltv;
            int priorPurchases;
            String churnRisk;

            if (i == 1) {
                segment = "HIGH_VALUE";
                loyaltyTier = "GOLD";
                ltv = 3480.00;
                priorPurchases = 18;
                churnRisk = "LOW";
            } else if (i % 20 == 0) {
                segment = "HIGH_VALUE";
                loyaltyTier = i % 40 == 0 ? "PLATINUM" : "GOLD";
                ltv = 2500.00 + (i % 100) * 42.0;
                priorPurchases = 10 + (i % 40);
                churnRisk = "LOW";
            } else if (i % 7 == 0) {
                segment = "GROWTH";
                loyaltyTier = "SILVER";
                ltv = 500.00 + (i % 50) * 15.0;
                priorPurchases = 3 + (i % 8);
                churnRisk = "LOW";
            } else if (i % 11 == 0) {
                segment = "PRICE_SENSITIVE";
                loyaltyTier = "STANDARD";
                ltv = 120.00 + (i % 30) * 7.5;
                priorPurchases = 1 + (i % 4);
                churnRisk = i % 22 == 0 ? "HIGH" : "MEDIUM";
            } else if (i % 5 == 0) {
                segment = "NEW_CUSTOMER";
                loyaltyTier = "STANDARD";
                ltv = 0.00;
                priorPurchases = 0;
                churnRisk = "UNKNOWN";
            } else {
                segment = "STANDARD";
                loyaltyTier = "STANDARD";
                ltv = 200.00 + (i % 60) * 9.0;
                priorPurchases = 1 + (i % 6);
                churnRisk = "LOW";
            }

            result.add(new Customer(
                    customerId,
                    name,
                    segment,
                    loyaltyTier,
                    homeZip,
                    round(ltv),
                    priorPurchases,
                    churnRisk
            ));
        }

        return result;
    }

    private static void emitAllCustomerProfiles(KafkaProducer<String, String> producer, long nowMs) throws Exception {
        for (Customer c : CUSTOMERS) {
            emitCustomerProfile(producer, c, nowMs);
        }
    }

    private static void emitCustomerProfileRefreshBatch(
            KafkaProducer<String, String> producer,
            long nowMs,
            int batchSize
    ) throws Exception {
        for (int i = 0; i < batchSize; i++) {
            Customer c = CUSTOMERS.get(RANDOM.nextInt(CUSTOMERS.size()));
            emitCustomerProfile(producer, c, nowMs);
        }

        // Keep demo profile fresh.
        emitCustomerProfile(producer, customerById(DEMO_CUSTOMER_ID), nowMs);
    }

    private static void emitCustomerProfile(
            KafkaProducer<String, String> producer,
            Customer c,
            long nowMs
    ) throws Exception {
        int supportIssueOpenCount = c.customerId().equals(DEMO_CUSTOMER_ID)
                ? 0
                : RANDOM.nextInt(100) < 8 ? 1 + RANDOM.nextInt(2) : 0;

        send(producer, TOPIC_CUSTOMER_PROFILE, c.customerId(), map(
                "customer_id", c.customerId(),
                "customer_name", c.customerName(),
                "customer_segment", c.customerSegment(),
                "loyalty_tier", c.loyaltyTier(),
                "home_zip", c.homeZip(),
                "lifetime_value_usd", c.lifetimeValueUsd(),
                "prior_purchase_count", c.priorPurchaseCount(),
                "churn_risk_band", c.churnRiskBand(),
                "support_issue_open_count", supportIssueOpenCount,
                "profile_record_state", "ACTIVE",
                "profile_version", profileVersion(nowMs),
                "event_ts_ms", nowMs
        ));
    }

    private static void emitIncentivePolicies(KafkaProducer<String, String> producer, long nowMs) throws Exception {
        emitIncentivePolicy(producer, "HIGH_VALUE", 100.0, 25.0, 0.0, "FREE_EXPEDITED_SHIPPING", nowMs);
        emitIncentivePolicy(producer, "GROWTH", 75.0, 15.0, 5.0, "FREE_SHIPPING_OR_5_PERCENT_OFF", nowMs);
        emitIncentivePolicy(producer, "NEW_CUSTOMER", 50.0, 10.0, 10.0, "WELCOME_10_PERCENT_OFF", nowMs);
        emitIncentivePolicy(producer, "PRICE_SENSITIVE", 40.0, 8.0, 8.0, "SAVE_8_PERCENT_NOW", nowMs);
        emitIncentivePolicy(producer, "STANDARD", 75.0, 10.0, 5.0, "FREE_STANDARD_SHIPPING", nowMs);
    }

    private static void emitIncentivePolicy(
            KafkaProducer<String, String> producer,
            String customerSegment,
            double minCartValueUsd,
            double maxShippingCreditUsd,
            double maxDiscountPercent,
            String incentiveName,
            long nowMs
    ) throws Exception {
        send(producer, TOPIC_INCENTIVE_POLICY, customerSegment, map(
                "customer_segment", customerSegment,
                "min_cart_value_usd", minCartValueUsd,
                "max_shipping_credit_usd", maxShippingCreditUsd,
                "max_discount_percent", maxDiscountPercent,
                "incentive_name", incentiveName,
                "free_shipping_allowed", maxShippingCreditUsd > 0,
                "discount_allowed", maxDiscountPercent > 0,
                "policy_record_state", "ACTIVE",
                "policy_version", policyVersion(nowMs),
                "event_ts_ms", nowMs
        ));
    }

    private static void emitDemoCheckoutCase(KafkaProducer<String, String> producer, long nowMs) throws Exception {
        Customer customer = customerById(DEMO_CUSTOMER_ID);
        Product product = productBySku("RUN-LTD-RED-10");

        send(producer, TOPIC_CART_STATE, DEMO_CART_ID, map(
                "cart_id", DEMO_CART_ID,
                "session_id", DEMO_SESSION_ID,
                "customer_id", customer.customerId(),
                "primary_sku_id", product.skuId(),
                "primary_product_name", product.productName(),
                "category_name", product.categoryName(),
                "item_count", 2,
                "cart_value_usd", 238.00,
                "gross_margin_usd", 112.00,
                "shipping_cost_usd", 18.95,
                "tax_amount_usd", 20.23,
                "inventory_available", true,
                "inventory_reserved", true,
                "inventory_reserved_until_ts_ms", nowMs + 10 * 60_000L,
                "cart_record_state", "CHECKOUT_ACTIVE",
                "cart_update_reason", "DEMO_HIGH_VALUE_CHECKOUT_FRICTION",
                "event_ts_ms", nowMs
        ));

        sendCheckoutActivity(
                producer,
                "ACT-DEMO-" + nowMs + "-1",
                DEMO_SESSION_ID,
                DEMO_CART_ID,
                customer.customerId(),
                "SHIPPING_METHOD_VIEW",
                68,
                "HIGH",
                "/checkout/shipping",
                "MOBILE_WEB",
                "EMAIL",
                nowMs - 35_000L
        );

        sendCheckoutActivity(
                producer,
                "ACT-DEMO-" + nowMs + "-2",
                DEMO_SESSION_ID,
                DEMO_CART_ID,
                customer.customerId(),
                "PAYMENT_STEP_VIEW",
                96,
                "HIGH",
                "/checkout/payment",
                "MOBILE_WEB",
                "EMAIL",
                nowMs - 15_000L
        );

        sendCheckoutActivity(
                producer,
                "ACT-DEMO-" + nowMs + "-3",
                DEMO_SESSION_ID,
                DEMO_CART_ID,
                customer.customerId(),
                "CHECKOUT_IDLE",
                132,
                "HIGH",
                "/checkout",
                "MOBILE_WEB",
                "EMAIL",
                nowMs
        );

        sendPaymentAttempt(
                producer,
                "PAY-DEMO-" + nowMs + "-1",
                DEMO_CART_ID,
                customer.customerId(),
                238.00,
                "CARD_DECLINED_SOFT",
                false,
                "SOFT_DECLINE",
                true,
                "STRIPE",
                nowMs - 20_000L
        );

        sendPaymentAttempt(
                producer,
                "PAY-DEMO-" + nowMs + "-2",
                DEMO_CART_ID,
                customer.customerId(),
                238.00,
                "CARD_DECLINED_SOFT",
                false,
                "SOFT_DECLINE",
                true,
                "STRIPE",
                nowMs - 5_000L
        );
    }

    private static void emitRandomCheckoutTraffic(KafkaProducer<String, String> producer, long nowMs) throws Exception {
        int activeSessionCount = 5 + RANDOM.nextInt(10);

        for (int i = 0; i < activeSessionCount; i++) {
            Customer customer = CUSTOMERS.get(RANDOM.nextInt(CUSTOMERS.size()));
            Product product = weightedProduct();

            String sessionId = buildUniqueId("SES");
            String cartId = buildUniqueId("CART");

            int itemCount = 1 + RANDOM.nextInt(4);
            double cartValueUsd = round(product.unitPriceUsd() * itemCount);
            double grossMarginUsd = round(cartValueUsd * (product.grossMarginPercent() / 100.0));
            double shippingCostUsd = chooseShippingCost(customer, cartValueUsd);

            boolean inventoryAvailable = RANDOM.nextInt(100) < 94;
            boolean inventoryReserved = inventoryAvailable && RANDOM.nextInt(100) < 85;

            String cartRecordState = chooseCartRecordState();

            send(producer, TOPIC_CART_STATE, cartId, map(
                    "cart_id", cartId,
                    "session_id", sessionId,
                    "customer_id", customer.customerId(),
                    "primary_sku_id", product.skuId(),
                    "primary_product_name", product.productName(),
                    "category_name", product.categoryName(),
                    "item_count", itemCount,
                    "cart_value_usd", cartValueUsd,
                    "gross_margin_usd", grossMarginUsd,
                    "shipping_cost_usd", shippingCostUsd,
                    "tax_amount_usd", round(cartValueUsd * 0.085),
                    "inventory_available", inventoryAvailable,
                    "inventory_reserved", inventoryReserved,
                    "inventory_reserved_until_ts_ms", inventoryReserved ? nowMs + (5 + RANDOM.nextInt(20)) * 60_000L : null,
                    "cart_record_state", cartRecordState,
                    "cart_update_reason", "CUSTOMER_CHECKOUT_ACTIVITY",
                    "event_ts_ms", nowMs
            ));

            emitSessionActivitySeries(producer, sessionId, cartId, customer, shippingCostUsd, nowMs);
            maybeEmitPaymentAttempts(producer, cartId, customer, cartValueUsd, nowMs);
        }
    }

    private static void emitSessionActivitySeries(
            KafkaProducer<String, String> producer,
            String sessionId,
            String cartId,
            Customer customer,
            double shippingCostUsd,
            long nowMs
    ) throws Exception {
        int activityCount = 1 + RANDOM.nextInt(5);
        long baseTs = nowMs - activityCount * 20_000L;

        for (int i = 0; i < activityCount; i++) {
            String activityName = chooseActivityName(i, activityCount);
            int secondsOnStep = chooseSecondsOnStep(activityName);
            String frictionBand = classifyFriction(activityName, secondsOnStep, shippingCostUsd);

            sendCheckoutActivity(
                    producer,
                    buildUniqueId("ACT"),
                    sessionId,
                    cartId,
                    customer.customerId(),
                    activityName,
                    secondsOnStep,
                    frictionBand,
                    pagePath(activityName),
                    chooseDeviceChannel(),
                    chooseTrafficSource(),
                    baseTs + i * 20_000L
            );
        }
    }

    private static void maybeEmitPaymentAttempts(
            KafkaProducer<String, String> producer,
            String cartId,
            Customer customer,
            double cartValueUsd,
            long nowMs
    ) throws Exception {
        int r = RANDOM.nextInt(100);

        if (r < 38) {
            return;
        }

        if (r < 72) {
            sendPaymentAttempt(
                    producer,
                    buildUniqueId("PAY"),
                    cartId,
                    customer.customerId(),
                    cartValueUsd,
                    "AUTHORIZED",
                    true,
                    "APPROVED",
                    RANDOM.nextInt(100) < 35,
                    RANDOM.nextBoolean() ? "STRIPE" : "ADYEN",
                    nowMs
            );
        } else if (r < 92) {
            sendPaymentAttempt(
                    producer,
                    buildUniqueId("PAY"),
                    cartId,
                    customer.customerId(),
                    cartValueUsd,
                    "CARD_DECLINED_SOFT",
                    false,
                    "SOFT_DECLINE",
                    RANDOM.nextInt(100) < 60,
                    RANDOM.nextBoolean() ? "STRIPE" : "ADYEN",
                    nowMs
            );
        } else {
            sendPaymentAttempt(
                    producer,
                    buildUniqueId("PAY"),
                    cartId,
                    customer.customerId(),
                    cartValueUsd,
                    "INSUFFICIENT_FUNDS",
                    false,
                    "HARD_DECLINE",
                    RANDOM.nextInt(100) < 25,
                    RANDOM.nextBoolean() ? "STRIPE" : "ADYEN",
                    nowMs
            );
        }
    }

    private static void sendCheckoutActivity(
            KafkaProducer<String, String> producer,
            String activityId,
            String sessionId,
            String cartId,
            String customerId,
            String activityName,
            int secondsOnStep,
            String frictionBand,
            String pageUrlPath,
            String deviceChannel,
            String trafficSource,
            long eventTsMs
    ) throws Exception {
        send(producer, TOPIC_SESSION_ACTIVITY, activityId, map(
                "activity_id", activityId,
                "session_id", sessionId,
                "cart_id", cartId,
                "customer_id", customerId,
                "activity_name", activityName,
                "seconds_on_step", secondsOnStep,
                "friction_band", frictionBand,
                "page_url_path", pageUrlPath,
                "device_channel", deviceChannel,
                "traffic_source", trafficSource,
                "event_ts_ms", eventTsMs
        ));
    }

    private static void sendPaymentAttempt(
            KafkaProducer<String, String> producer,
            String paymentAttemptId,
            String cartId,
            String customerId,
            double amountUsd,
            String paymentResultCode,
            boolean paymentAuthorized,
            String declineCategory,
            boolean backupPaymentAvailable,
            String paymentProvider,
            long eventTsMs
    ) throws Exception {
        send(producer, TOPIC_PAYMENT_ATTEMPT, paymentAttemptId, map(
                "payment_attempt_id", paymentAttemptId,
                "cart_id", cartId,
                "customer_id", customerId,
                "payment_amount_usd", amountUsd,
                "payment_method_family", RANDOM.nextInt(100) < 78 ? "CARD" : "WALLET",
                "payment_result_code", paymentResultCode,
                "payment_authorized", paymentAuthorized,
                "decline_category", declineCategory,
                "backup_payment_available", backupPaymentAvailable,
                "payment_provider", paymentProvider,
                "event_ts_ms", eventTsMs
        ));
    }

    private static Product weightedProduct() {
        int r = RANDOM.nextInt(100);
        if (r < 22) return productBySku("RUN-LTD-RED-10");
        if (r < 38) return productBySku("RUN-LTD-BLK-10");
        if (r < 55) return productBySku("HD-PHN-BLK");
        if (r < 70) return productBySku("WATCH-FIT-SLV");
        return PRODUCTS.get(RANDOM.nextInt(PRODUCTS.size()));
    }

    private static String chooseCartRecordState() {
        int r = RANDOM.nextInt(100);
        if (r < 58) return "CHECKOUT_ACTIVE";
        if (r < 73) return "PAYMENT_RETRY";
        if (r < 86) return "ABANDONMENT_RISK";
        if (r < 96) return "CONVERTED";
        return "EXPIRED";
    }

    private static double chooseShippingCost(Customer customer, double cartValueUsd) {
        if ("HIGH_VALUE".equals(customer.customerSegment()) && cartValueUsd > 100.0) {
            return RANDOM.nextInt(100) < 65 ? 14.95 + RANDOM.nextInt(6) : 0.0;
        }

        if ("PRICE_SENSITIVE".equals(customer.customerSegment())) {
            return RANDOM.nextInt(100) < 75 ? 9.95 + RANDOM.nextInt(8) : 0.0;
        }

        if (cartValueUsd > 150.0) {
            return RANDOM.nextInt(100) < 45 ? 0.0 : 8.95;
        }

        return RANDOM.nextInt(100) < 70 ? 6.95 + RANDOM.nextInt(9) : 0.0;
    }

    private static String chooseActivityName(int index, int activityCount) {
        if (index == 0) {
            return "CART_VIEW";
        }

        if (index == activityCount - 1) {
            int r = RANDOM.nextInt(100);
            if (r < 25) return "SHIPPING_METHOD_VIEW";
            if (r < 55) return "PAYMENT_STEP_VIEW";
            if (r < 75) return "CHECKOUT_IDLE";
            if (r < 90) return "PROMO_CODE_ATTEMPT";
            return "ORDER_REVIEW_VIEW";
        }

        String[] names = {
                "SHIPPING_ADDRESS_VIEW",
                "SHIPPING_METHOD_VIEW",
                "ORDER_REVIEW_VIEW",
                "PAYMENT_STEP_VIEW",
                "PROMO_CODE_ATTEMPT"
        };

        return names[RANDOM.nextInt(names.length)];
    }

    private static int chooseSecondsOnStep(String activityName) {
        return switch (activityName) {
            case "CHECKOUT_IDLE" -> 85 + RANDOM.nextInt(180);
            case "PAYMENT_STEP_VIEW" -> 25 + RANDOM.nextInt(130);
            case "SHIPPING_METHOD_VIEW" -> 20 + RANDOM.nextInt(110);
            case "PROMO_CODE_ATTEMPT" -> 15 + RANDOM.nextInt(95);
            case "ORDER_REVIEW_VIEW" -> 10 + RANDOM.nextInt(70);
            default -> 5 + RANDOM.nextInt(45);
        };
    }

    private static String classifyFriction(String activityName, int secondsOnStep, double shippingCostUsd) {
        if ("CHECKOUT_IDLE".equals(activityName) && secondsOnStep >= 90) return "HIGH";
        if ("PAYMENT_STEP_VIEW".equals(activityName) && secondsOnStep >= 75) return "HIGH";
        if ("SHIPPING_METHOD_VIEW".equals(activityName) && shippingCostUsd >= 12.0) return "HIGH";
        if ("PROMO_CODE_ATTEMPT".equals(activityName) && secondsOnStep >= 45) return "MEDIUM";
        if (secondsOnStep >= 50) return "MEDIUM";
        return "LOW";
    }

    private static String pagePath(String activityName) {
        return switch (activityName) {
            case "CART_VIEW" -> "/cart";
            case "SHIPPING_ADDRESS_VIEW" -> "/checkout/address";
            case "SHIPPING_METHOD_VIEW" -> "/checkout/shipping";
            case "PAYMENT_STEP_VIEW" -> "/checkout/payment";
            case "PROMO_CODE_ATTEMPT" -> "/checkout/promo";
            case "ORDER_REVIEW_VIEW" -> "/checkout/review";
            case "CHECKOUT_IDLE" -> "/checkout";
            default -> "/checkout";
        };
    }

    private static String chooseDeviceChannel() {
        int r = RANDOM.nextInt(100);
        if (r < 52) return "MOBILE_WEB";
        if (r < 80) return "DESKTOP_WEB";
        return "MOBILE_APP";
    }

    private static String chooseTrafficSource() {
        int r = RANDOM.nextInt(100);
        if (r < 32) return "PAID_SEARCH";
        if (r < 52) return "EMAIL";
        if (r < 72) return "ORGANIC";
        if (r < 90) return "SOCIAL";
        return "DIRECT";
    }

    private static String buildUniqueId(String prefix) {
        long seq = switch (prefix) {
            case "CART" -> CART_SEQ.getAndIncrement();
            case "SES" -> SESSION_SEQ.getAndIncrement();
            case "PAY" -> PAYMENT_SEQ.getAndIncrement();
            default -> EVENT_SEQ.getAndIncrement();
        };

        return prefix + "-" + PROCESS_START_MS + "-" + PROCESS_ID + "-" + seq;
    }

    private static String buildProcessId() {
        String runtime = ManagementFactory.getRuntimeMXBean().getName();
        String cleaned = runtime.replaceAll("[^a-zA-Z0-9]", "");
        return cleaned.length() > 18 ? cleaned.substring(0, 18) : cleaned;
    }

    private static long profileVersion(long nowMs) {
        return LocalDate.ofEpochDay(nowMs / 86_400_000L).atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli();
    }

    private static long policyVersion(long nowMs) {
        return profileVersion(nowMs);
    }

    private static Customer customerById(String customerId) {
        return CUSTOMERS.stream()
                .filter(c -> c.customerId().equals(customerId))
                .findFirst()
                .orElseThrow();
    }

    private static Product productBySku(String skuId) {
        return PRODUCTS.stream()
                .filter(p -> p.skuId().equals(skuId))
                .findFirst()
                .orElseThrow();
    }

    private static double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }

    private static Map<String, Object> map(Object... kvs) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("event_id", "EV-" + PROCESS_START_MS + "-" + PROCESS_ID + "-" + EVENT_SEQ.getAndIncrement());

        for (int i = 0; i < kvs.length; i += 2) {
            result.put((String) kvs[i], kvs[i + 1]);
        }

        return result;
    }

    private static void send(
            KafkaProducer<String, String> producer,
            String topic,
            String key,
            Map<String, Object> value
    ) throws Exception {
        String json = MAPPER.writeValueAsString(value);

        try {
            producer.send(new ProducerRecord<>(topic, key, json)).get();
            System.out.printf("topic=%s key=%s value=%s%n", topic, key, json);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw e;
        } catch (ExecutionException e) {
            throw new RuntimeException("Failed to write record to topic " + topic + " with key " + key, e);
        }
    }
}
