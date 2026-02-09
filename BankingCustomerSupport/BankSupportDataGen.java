import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.javafaker.Faker;
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.CreateTopicsResult;
import org.apache.kafka.clients.admin.DeleteTopicsResult;
import org.apache.kafka.clients.admin.DescribeTopicsResult;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.admin.TopicDescription;
import org.apache.kafka.clients.producer.*;
import org.apache.kafka.common.config.TopicConfig;
import org.apache.kafka.common.errors.UnknownTopicOrPartitionException;
import org.apache.kafka.common.serialization.StringSerializer;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ThreadLocalRandom;

public class BankSupportDataGen {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Faker FAKER = new Faker();

    private static final String KAFKA_BOOTSTRAP_SERVERS = "Kafka Bootstrap Server Address";
    private static final String KAFKA_API_KEY = "Your Kafka API Key";
    private static final String KAFKA_API_SECRET = "Your Kafka API Secret";

    // Topics
    private static final String T_LEDGER = "bank_support_ledger_updates";
    private static final String T_AUTH = "bank_support_auth_events";
    private static final String T_TRANSFERS = "bank_support_transfers";
    private static final String T_HOLDS = "bank_support_holds";
    private static final String T_DISPUTES = "bank_support_disputes";
    private static final String T_NOTIFS = "bank_support_notifications";

    // Simple in-memory state to generate realistic lifecycles
    private static final Map<String, AccountState> ACCOUNT_STATE = new HashMap<>();

    private static class AccountState {
        String customerId;
        String accountId;
        BigDecimal ledger = new BigDecimal("5000.00");
        BigDecimal current = new BigDecimal("5000.00");
        BigDecimal available = new BigDecimal("5000.00");
        String currency = "USD";

        // track a few IDs so later events can reference earlier ones
        Deque<String> recentAuthIds = new ArrayDeque<>();
        Deque<String> recentTransferIds = new ArrayDeque<>();
        Deque<String> recentHoldIds = new ArrayDeque<>();
        Deque<String> recentDisputeIds = new ArrayDeque<>();
    }

    public static void main(String[] args) throws Exception {
        String bootstrap = env("KAFKA_BOOTSTRAP", "localhost:9092");
        int customerCount = Integer.parseInt(env("CUSTOMERS", "200"));
        int eventsPerSecond = Integer.parseInt(env("EPS", "40"));

        Properties props = new Properties();
        props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA_BOOTSTRAP_SERVERS);
        props.put(ProducerConfig.ACKS_CONFIG, "all");
        props.put(ProducerConfig.LINGER_MS_CONFIG, "10");
        props.put(ProducerConfig.BATCH_SIZE_CONFIG, Integer.toString(64 * 1024));
        props.put(ProducerConfig.COMPRESSION_TYPE_CONFIG, "lz4");
        props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.CLIENT_ID_CONFIG, "BankSupportDataGen");
        props.put("security.protocol", "SASL_SSL");
        props.put("sasl.mechanism", "PLAIN");
        props.put("sasl.jaas.config", "org.apache.kafka.common.security.plain.PlainLoginModule required username=\"" + KAFKA_API_KEY + "\" password=\"" + KAFKA_API_SECRET + "\";");

        // Use try-with-resources to ensure the AdminClient is closed
        try (AdminClient adminClient = AdminClient.create(props)) {

            // Optional: Add any specific topic configurations
            Map<String, String> topicConfig = new HashMap<>();
            topicConfig.put(TopicConfig.CLEANUP_POLICY_CONFIG, TopicConfig.CLEANUP_POLICY_DELETE);
            topicConfig.put(TopicConfig.RETENTION_MS_CONFIG, "-1"); // infinite
            topicConfig.put(TopicConfig.SEGMENT_BYTES_CONFIG, "1073741824"); // 1 GB

            recreateTopic(adminClient, T_LEDGER, 1, (short) 3, topicConfig);
            recreateTopic(adminClient, T_AUTH, 1, (short) 3, topicConfig);
            recreateTopic(adminClient, T_TRANSFERS, 1, (short) 3, topicConfig);
            recreateTopic(adminClient, T_HOLDS, 1, (short) 3, topicConfig);
            recreateTopic(adminClient, T_DISPUTES, 1, (short) 3, topicConfig);
            recreateTopic(adminClient, T_NOTIFS, 1, (short) 3, topicConfig);
        } catch (Exception e) {
            System.err.println("Failed to initialize AdminClient: " + e.getMessage());
            e.printStackTrace();
        }

        try (KafkaProducer<String, String> producer = new KafkaProducer<>(props)) {
            initAccounts(customerCount);

            long sleepMs = Math.max(1, 5000L / Math.max(1, eventsPerSecond));
            while (true) {
                // Generate a small burst of mixed events each cycle
                for (int i = 0; i < 5; i++) {
                    AccountState st = pickAccount();
                    int kind = ThreadLocalRandom.current().nextInt(100);

                    if (kind < 25) {
                        sendLedgerUpdate(producer, st);
                    } else if (kind < 55) {
                        sendAuthEvent(producer, st);
                    } else if (kind < 75) {
                        sendTransferEvent(producer, st);
                    } else if (kind < 85) {
                        sendHoldEvent(producer, st);
                    } else if (kind < 93) {
                        sendDisputeEvent(producer, st);
                    } else {
                        sendNotification(producer, st);
                    }
                }

                producer.flush();
                Thread.sleep(sleepMs);
            }
        }
    }

    private static void initAccounts(int n) {
        for (int i = 1; i <= n; i++) {
            AccountState st = new AccountState();
            st.customerId = String.format("C%06d", i);
            st.accountId = String.format("A%06d", i);
            ACCOUNT_STATE.put(st.customerId, st);
        }
    }

    private static AccountState pickAccount() {
        int idx = ThreadLocalRandom.current().nextInt(ACCOUNT_STATE.size());
        return ACCOUNT_STATE.values().stream().skip(idx).findFirst().orElseThrow();
    }

    private static void sendLedgerUpdate(KafkaProducer<String, String> p, AccountState st) throws Exception {
        // Small random drift; holds/authorizations will reduce available more often
        BigDecimal drift = rndMoney(-20, 20);
        st.current = st.current.add(drift);
        st.ledger = st.ledger.add(drift);
        st.available = st.available.add(drift);

        Map<String, Object> e = new LinkedHashMap<>();
        e.put("event_id", uuid());
        e.put("customer_id", st.customerId);
        e.put("account_id", st.accountId);
        e.put("available_balance", st.available.doubleValue());
        e.put("current_balance", st.current.doubleValue());
        e.put("ledger_balance", st.ledger.doubleValue());
        e.put("currency", st.currency);
        e.put("updated_at", Instant.now().toEpochMilli());

        send(p, T_LEDGER, st.customerId, e);
    }

    private static void sendAuthEvent(KafkaProducer<String, String> p, AccountState st) throws Exception {
        String[] merchants = {"UBER", "AMAZON", "DELTA", "STARBUCKS", "APPLE", "SHELL", "TARGET"};
        String merchant = merchants[ThreadLocalRandom.current().nextInt(merchants.length)];
        BigDecimal amount = rndMoney(5, 250);

        String status;
        int r = ThreadLocalRandom.current().nextInt(100);
        if (r < 75) status = "PENDING";
        else if (r < 90) status = "SETTLED";
        else status = "REVERSED";

        String authId = "AUTH-" + uuid().substring(0, 8);
        st.recentAuthIds.addFirst(authId);
        trim(st.recentAuthIds, 10);

        // Apply impact to available balance for pending auth
        if ("PENDING".equals(status)) st.available = st.available.subtract(amount);
        if ("REVERSED".equals(status)) st.available = st.available.add(amount);

        Instant now = Instant.now();
        Map<String, Object> e = new LinkedHashMap<>();
        e.put("event_id", uuid());
        e.put("customer_id", st.customerId);
        e.put("account_id", st.accountId);
        e.put("auth_id", authId);
        e.put("merchant", merchant);
        e.put("amount", amount.doubleValue());
        e.put("currency", st.currency);
        e.put("status", status);
        e.put("expected_settlement_at", now.plus(2, ChronoUnit.HOURS).toEpochMilli());
        e.put("created_at", now.toEpochMilli());

        send(p, T_AUTH, st.customerId, e);

        // Emit a notification sometimes
        if (ThreadLocalRandom.current().nextInt(100) < 20) {
            sendNotification(p, st, "AUTH_STATUS",
                    "Authorization " + authId + " at " + merchant + " is " + status + ".");
        }
    }

    private static void sendTransferEvent(KafkaProducer<String, String> p, AccountState st) throws Exception {
        String[] types = {"ACH", "WIRE", "INTERNAL"};
        String type = types[ThreadLocalRandom.current().nextInt(types.length)];
        BigDecimal amount = rndMoney(50, 5000);

        String transferId;
        boolean updateExisting = !st.recentTransferIds.isEmpty() && ThreadLocalRandom.current().nextInt(100) < 60;
        if (updateExisting) {
            transferId = st.recentTransferIds.peekFirst();
        } else {
            transferId = "TR-" + uuid().substring(0, 10);
            st.recentTransferIds.addFirst(transferId);
            trim(st.recentTransferIds, 10);
            // initial debit of available/current for outgoing transfer
            st.available = st.available.subtract(amount);
            st.current = st.current.subtract(amount);
        }

        String status;
        int r = ThreadLocalRandom.current().nextInt(100);
        if (r < 65) status = "PENDING";
        else if (r < 85) status = "COMPLETED";
        else if (r < 95) status = "FAILED";
        else status = "RETURNED";

        String failureReason = null;
        if ("FAILED".equals(status)) failureReason = "NETWORK_ERROR";
        if ("RETURNED".equals(status)) failureReason = "BENEFICIARY_REJECTED";

        Instant now = Instant.now();
        Map<String, Object> e = new LinkedHashMap<>();
        e.put("event_id", uuid());
        e.put("customer_id", st.customerId);
        e.put("account_id", st.accountId);
        e.put("transfer_id", transferId);
        e.put("type", type);
        e.put("amount", amount.doubleValue());
        e.put("currency", st.currency);
        e.put("status", status);
        e.put("failure_reason", failureReason);
        e.put("expected_eta", now.plus(90, ChronoUnit.MINUTES).toEpochMilli());
        e.put("tracking_ref", "BANKREF-" + uuid().substring(0, 8));
        e.put("initiated_at", now.minus(5, ChronoUnit.MINUTES).toEpochMilli());
        e.put("updated_at", now.toEpochMilli());

        send(p, T_TRANSFERS, st.customerId, e);

        // Notify the customer on status changes
        sendNotification(p, st, "TRANSFER_STATUS",
                "Transfer " + transferId + " is " + status + (failureReason != null ? " (" + failureReason + ")" : "") + ".");
    }

    private static void sendHoldEvent(KafkaProducer<String, String> p, AccountState st) throws Exception {
        boolean updateExisting = !st.recentHoldIds.isEmpty() && ThreadLocalRandom.current().nextInt(100) < 50;
        String holdId = updateExisting ? st.recentHoldIds.peekFirst() : "HOLD-" + uuid().substring(0, 10);

        if (!updateExisting) {
            st.recentHoldIds.addFirst(holdId);
            trim(st.recentHoldIds, 10);
        }

        String[] reasons = {"FRAUD_REVIEW", "KYC_REVIEW", "LIMIT_EXCEEDED", "DISPUTE_REVIEW"};
        String reason = reasons[ThreadLocalRandom.current().nextInt(reasons.length)];

        String status = ThreadLocalRandom.current().nextInt(100) < 70 ? "PLACED" : "RELEASED";
        Instant now = Instant.now();

        Map<String, Object> e = new LinkedHashMap<>();
        e.put("event_id", uuid());
        e.put("customer_id", st.customerId);
        e.put("account_id", st.accountId);
        e.put("hold_id", holdId);
        e.put("reason_code", reason);
        e.put("status", status);
        e.put("release_conditions", status.equals("PLACED") ? "Verify identity in-app" : "N/A");
        e.put("velocity_limit_per_hour", 5);
        e.put("created_at", now.minus(2, ChronoUnit.MINUTES).toEpochMilli());
        e.put("updated_at", now.toEpochMilli());

        send(p, T_HOLDS, st.customerId, e);

        sendNotification(p, st, "HOLD_STATUS",
                "Account hold " + holdId + " is " + status + " (" + reason + ").");
    }

    private static void sendDisputeEvent(KafkaProducer<String, String> p, AccountState st) throws Exception {
        boolean updateExisting = !st.recentDisputeIds.isEmpty() && ThreadLocalRandom.current().nextInt(100) < 55;
        String disputeId = updateExisting ? st.recentDisputeIds.peekFirst() : "DSP-" + uuid().substring(0, 10);

        if (!updateExisting) {
            st.recentDisputeIds.addFirst(disputeId);
            trim(st.recentDisputeIds, 10);
        }

        String stage;
        int r = ThreadLocalRandom.current().nextInt(100);
        if (r < 55) stage = "OPEN";
        else if (r < 80) stage = "INVESTIGATING";
        else if (r < 92) stage = "RESOLVED";
        else stage = "CLOSED";

        String provCredit = (stage.equals("OPEN") || stage.equals("INVESTIGATING")) ? "PENDING" : "FINAL";
        String nextAction = stage.equals("OPEN") ? "Upload receipt"
                : stage.equals("INVESTIGATING") ? "Await decision"
                : "None";

        String relatedAuth = st.recentAuthIds.isEmpty() ? null : st.recentAuthIds.peekFirst();

        Instant now = Instant.now();
        Map<String, Object> e = new LinkedHashMap<>();
        e.put("event_id", uuid());
        e.put("customer_id", st.customerId);
        e.put("account_id", st.accountId);
        e.put("dispute_id", disputeId);
        e.put("related_auth_id", relatedAuth);
        e.put("stage", stage);
        e.put("provisional_credit_status", provCredit);
        e.put("next_required_action", nextAction);
        e.put("created_at", now.minus(10, ChronoUnit.MINUTES).toEpochMilli());
        e.put("updated_at", now.toEpochMilli());

        send(p, T_DISPUTES, st.customerId, e);

        sendNotification(p, st, "DISPUTE_STATUS",
                "Dispute " + disputeId + " is " + stage + ". Next: " + nextAction + ".");
    }

    private static void sendNotification(KafkaProducer<String, String> p, AccountState st) throws Exception {
        String[] channels = {"IN_APP", "SMS", "EMAIL"};
        String channel = channels[ThreadLocalRandom.current().nextInt(channels.length)];

        Map<String, Object> e = new LinkedHashMap<>();
        e.put("event_id", uuid());
        e.put("customer_id", st.customerId);
        e.put("channel", channel);
        e.put("message_type", "GENERIC");
        e.put("message", "Account update available.");
        e.put("sent_at", Instant.now().toEpochMilli());

        send(p, T_NOTIFS, st.customerId, e);
    }

    private static void sendNotification(KafkaProducer<String, String> p, AccountState st, String type, String msg) throws Exception {
        Map<String, Object> e = new LinkedHashMap<>();
        e.put("event_id", uuid());
        e.put("customer_id", st.customerId);
        e.put("channel", "IN_APP");
        e.put("message_type", type);
        e.put("message", msg);
        e.put("sent_at", Instant.now().toEpochMilli());

        send(p, T_NOTIFS, st.customerId, e);
    }

    private static void send(KafkaProducer<String, String> p, String topic, String key, Map<String, Object> payload) throws Exception {
        String json = MAPPER.writeValueAsString(payload);
        ProducerRecord<String, String> rec = new ProducerRecord<>(topic, key, json);
        System.out.println("==> Sending to " + topic + ": " + json);
        p.send(rec, (md, ex) -> {
            if (ex != null) ex.printStackTrace();
        });
    }

    private static String uuid() { return UUID.randomUUID().toString(); }

    private static BigDecimal rndMoney(int min, int max) {
        double v = ThreadLocalRandom.current().nextDouble(min, max);
        return BigDecimal.valueOf(Math.round(v * 100.0) / 100.0);
    }

    private static void trim(Deque<String> dq, int max) {
        while (dq.size() > max) dq.removeLast();
    }

    private static String env(String k, String def) {
        String v = System.getenv(k);
        return (v == null || v.isBlank()) ? def : v;
    }

    /**
     * Checks if a Kafka topic exists, deletes it if it does, and then creates a new topic
     * with the same name and specified properties.
     *
     * @param adminClient       The Kafka AdminClient to perform operations.
     * @param topicName         The name of the topic to recreate.
     * @param numPartitions     The number of partitions for the new topic.
     * @param replicationFactor The replication factor for the new topic.
     * @param topicConfig       A Map of additional topic configurations (e.g., retention.ms).
     */
    public static void recreateTopic(AdminClient adminClient, String topicName, int numPartitions, short replicationFactor, Map<String, String> topicConfig) {
        System.out.println("Starting to recreate topic: " + topicName);

        try {
            // 1. Check if the topic exists and get its properties (if any)
            // We describe it to see if it's there.
            DescribeTopicsResult describeTopicsResult = adminClient.describeTopics(Collections.singleton(topicName));
            TopicDescription topicDescription = describeTopicsResult.values().get(topicName).get();

            System.out.println("Topic '" + topicName + "' found. Deleting it now...");

            // 2. If it exists, delete it
            DeleteTopicsResult deleteResult = adminClient.deleteTopics(Collections.singleton(topicName));
            // Wait for the deletion to complete
            deleteResult.all().get();

            System.out.println("Topic '" + topicName + "' deleted successfully.");

            // Note: Kafka deletion is asynchronous. A small delay might be needed
            // in some environments before recreation, though AdminClient.createTopics
            // is generally robust.
            Thread.sleep(1000); // Adding a brief pause just in case.

        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            System.err.println("Thread interrupted during topic recreation: " + e.getMessage());
            return;
        } catch (ExecutionException e) {
            // If the topic didn't exist, we get UnknownTopicOrPartitionException
            if (e.getCause() instanceof UnknownTopicOrPartitionException) {
                System.out.println("Topic '" + topicName + "' does not exist. Proceeding with creation.");
            } else {
                // Some other error occurred
                System.err.println("Error checking/deleting topic '" + topicName + "': " + e.getMessage());
                e.printStackTrace();
                return;
            }
        }

        // 3. Create a fresh topic
        try {
            System.out.println("Creating new topic '" + topicName + "' with " +
                    numPartitions + " partitions and replication factor " + replicationFactor);

            NewTopic newTopic = new NewTopic(topicName, numPartitions, replicationFactor);
            if (topicConfig != null && !topicConfig.isEmpty()) {
                newTopic.configs(topicConfig);
            }

            CreateTopicsResult createResult = adminClient.createTopics(Collections.singleton(newTopic));
            // Wait for the creation to complete
            createResult.all().get();

            System.out.println("Topic '" + topicName + "' created successfully.");

        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            System.err.println("Thread interrupted during topic creation: " + e.getMessage());
        } catch (ExecutionException e) {
            System.err.println("Error creating topic '" + topicName + "': " + e.getMessage());
            e.printStackTrace();
        }
    }
}
