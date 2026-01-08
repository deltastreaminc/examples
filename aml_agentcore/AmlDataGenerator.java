package io.deltastream.datagen.random.aml;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.CreateTopicsResult;
import org.apache.kafka.clients.admin.DeleteTopicsResult;
import org.apache.kafka.clients.admin.DescribeTopicsResult;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.admin.TopicDescription;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.config.TopicConfig;
import org.apache.kafka.common.errors.UnknownTopicOrPartitionException;
import org.apache.kafka.common.serialization.StringSerializer;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

public class AmlDataGenerator {

    private static final String KAFKA_BOOTSTRAP_SERVERS = "Your Kafka Bootstrap url";
    private static final String KAFKA_API_KEY = "Kafka key";
    private static final String KAFKA_API_SECRET = "Kafka Secret";

    // Kafka topics – must match your DeltaStream DDL
    private static final String TOPIC_TRANSACTIONS = "transactions";
    private static final String TOPIC_CUSTOMERS = "customers";
    private static final String TOPIC_KYC_RESULTS = "kyc_results";
    private static final String TOPIC_SANCTIONS_MATCHES = "sanctions_matches";

    private static final ObjectMapper MAPPER = new ObjectMapper();

    // Some country sets to align with "high risk"/"normal" behavior in rules
    private static final List<String> LOW_RISK_COUNTRIES = List.of("US", "GB", "DE", "FR", "CA");
    private static final List<String> HIGH_RISK_COUNTRIES = List.of("IQ", "KP", "SY", "AF", "RU", "UA"); // example list
    private static final List<String> MERCHANT_CATEGORIES = List.of(
            "GROCERY", "RESTAURANT", "ELECTRONICS", "TRAVEL", "GAMBLING", "LUXURY", "CASH"
    );
    private static final List<String> CHANNELS = List.of("WEB", "MOBILE", "POS", "ATM");

    public static void main(String[] args) throws Exception {
        String bootstrapServers = Optional.ofNullable(System.getenv("KAFKA_BOOTSTRAP_SERVERS"))
                .orElse("localhost:9092");

        int numCustomers = Integer.parseInt(
                Optional.ofNullable(System.getenv("GEN_NUM_CUSTOMERS")).orElse("100")
        );

        long txnIntervalMillis = Long.parseLong(
                Optional.ofNullable(System.getenv("GEN_TXN_INTERVAL_MS")).orElse("500")
        );

        Properties props = new Properties();
        props.put(ProducerConfig.CLIENT_ID_CONFIG, "aml-demo-generator");
        props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA_BOOTSTRAP_SERVERS);
        props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.ACKS_CONFIG, "all");
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

            recreateTopic(adminClient, TOPIC_TRANSACTIONS, 1, (short) 3, new HashMap<>());
            recreateTopic(adminClient, TOPIC_CUSTOMERS, 1, (short) 3, new HashMap<>());
            recreateTopic(adminClient, TOPIC_KYC_RESULTS, 1, (short) 3, new HashMap<>());
            recreateTopic(adminClient, TOPIC_SANCTIONS_MATCHES, 1, (short) 3, new HashMap<>());
        } catch (Exception e) {
            System.err.println("Failed to initialize AdminClient: " + e.getMessage());
            e.printStackTrace();
        }

        try (KafkaProducer<String, String> producer = new KafkaProducer<>(props)) {

            System.out.println("=== Generating customers, KYC, and sanctions data ===");
            List<Customer> customers = generateCustomers(numCustomers);
            sendCustomers(customers, producer);
            sendInitialKycResults(customers, producer);
            sendInitialSanctionsMatches(customers, producer);

            System.out.println("=== Starting continuous transaction generation ===");
            runTransactionLoop(customers, producer, txnIntervalMillis);
        }
    }

    // ----------------------------
    // Domain models & generators
    // ----------------------------

    private record Customer(
            String customerId,
            String fullName,
            LocalDate dateOfBirth,
            String residencyCountry,
            String riskSegment,   // LOW/MEDIUM/HIGH
            boolean pepFlag,
            String kycStatus      // PENDING/PASSED/FAILED
    ) {}

    private static List<Customer> generateCustomers(int num) {
        List<Customer> customers = new ArrayList<>(num);
        Random random = new Random();

        for (int i = 0; i < num; i++) {
            String id = "CUST-" + (1000 + i);
            String name = randomName(random);
            LocalDate dob = LocalDate.now().minusYears(18 + random.nextInt(50))
                    .minusDays(random.nextInt(365));
            String country;
            String riskSegment;
            boolean pep;
            String kycStatus;

            // Rough distribution: 70% low, 20% medium, 10% high
            double r = random.nextDouble();
            if (r < 0.7) {
                country = getRandom(LOW_RISK_COUNTRIES, random);
                riskSegment = "LOW";
                pep = false;
            } else if (r < 0.9) {
                country = getRandom(LOW_RISK_COUNTRIES, random);
                riskSegment = "MEDIUM";
                pep = random.nextDouble() < 0.05;
            } else {
                // high risk segment more likely from "high risk" countries
                country = getRandom(HIGH_RISK_COUNTRIES, random);
                riskSegment = "HIGH";
                pep = random.nextDouble() < 0.15;
            }

            // Most have passed KYC, some pending/failed
            double k = random.nextDouble();
            if (k < 0.75) kycStatus = "PASSED";
            else if (k < 0.95) kycStatus = "PENDING";
            else kycStatus = "FAILED";

            customers.add(new Customer(id, name, dob, country, riskSegment, pep, kycStatus));
        }

        // Make a handful of "interesting" customers for obvious high-risk patterns
        // e.g., 3 very risky PEPs with high-risk countries
        for (int i = 0; i < Math.min(3, customers.size()); i++) {
            Customer base = customers.get(i);
            customers.set(i, new Customer(
                    base.customerId(),
                    base.fullName(),
                    base.dateOfBirth(),
                    getRandom(HIGH_RISK_COUNTRIES, new Random()),
                    "HIGH",
                    true,
                    "PASSED"
            ));
        }

        return customers;
    }

    private static void sendCustomers(List<Customer> customers, KafkaProducer<String, String> producer) throws Exception {
        Instant now = Instant.now();
        for (Customer c : customers) {
            ObjectNode root = MAPPER.createObjectNode();
            root.put("customer_id", c.customerId());
            root.put("full_name", c.fullName());
            root.put("date_of_birth", c.dateOfBirth().toString());
            root.put("residency_country", c.residencyCountry());
            root.put("risk_segment", c.riskSegment());
            root.put("pep_flag", c.pepFlag());
            root.put("kyc_status", c.kycStatus());
            root.put("created_at", now.minus(randomBetween(1, 365), ChronoUnit.DAYS).toEpochMilli());
            root.put("updated_at", now.toEpochMilli());

            String json = MAPPER.writeValueAsString(root);
            producer.send(new ProducerRecord<>(TOPIC_CUSTOMERS, c.customerId(), json));
            System.out.println("Sent customer: " + json);
        }
        producer.flush();
        System.out.printf("Sent %d customer records to topic %s%n", customers.size(), TOPIC_CUSTOMERS);
    }

    private static void sendInitialKycResults(List<Customer> customers, KafkaProducer<String, String> producer) throws Exception {
        Instant now = Instant.now();
        Random random = new Random();
        int count = 0;

        for (Customer c : customers) {
            // Not everyone has detailed KYC result – but many do
            if (random.nextDouble() < 0.8) {
                ObjectNode root = MAPPER.createObjectNode();
                root.put("event_id", UUID.randomUUID().toString());
                root.put("customer_id", c.customerId());
                root.put("provider", "KYC_PROVIDER_X");
                root.put("check_type", randomCheckType(random));

                // Align with customer's riskSegment roughly
                String status;
                String riskLevel;
                if ("HIGH".equals(c.riskSegment()) || c.pepFlag()) {
                    status = "PASSED"; // they passed but flagged as high risk
                    riskLevel = "HIGH";
                } else if ("MEDIUM".equals(c.riskSegment())) {
                    status = "PASSED";
                    riskLevel = "MEDIUM";
                } else {
                    status = c.kycStatus();
                    riskLevel = "LOW";
                }

                root.put("status", status);
                root.put("risk_level", riskLevel);

                ObjectNode reasons = MAPPER.createObjectNode();
                if ("HIGH".equals(riskLevel)) {
                    reasons.put("pep_flag", c.pepFlag());
                    reasons.put("risk_segment", c.riskSegment());
                    reasons.put("note", "Customer has high AML risk factors");
                } else if ("MEDIUM".equals(riskLevel)) {
                    reasons.put("note", "Customer has moderate AML risk indicators");
                } else {
                    reasons.put("note", "Standard risk profile");
                }
                root.set("reasons", reasons);

                root.put("completed_at", now.minus(randomBetween(1, 90), ChronoUnit.DAYS).toEpochMilli());

                String json = MAPPER.writeValueAsString(root);
                producer.send(new ProducerRecord<>(TOPIC_KYC_RESULTS, c.customerId(), json));
                System.out.println("Sent KYC result: " + json);
                count++;
            }
        }
        producer.flush();
        System.out.printf("Sent %d KYC results to topic %s%n", count, TOPIC_KYC_RESULTS);
    }

    private static void sendInitialSanctionsMatches(List<Customer> customers, KafkaProducer<String, String> producer) throws Exception {
        Instant now = Instant.now();
        Random random = new Random();
        int count = 0;

        // Pick a small subset to have sanctions matches
        List<Customer> shuffled = new ArrayList<>(customers);
        Collections.shuffle(shuffled, random);
        List<Customer> flagged = shuffled.stream()
                .filter(c -> c.pepFlag() || "HIGH".equals(c.riskSegment()))
                .limit(5)
                .collect(Collectors.toList());

        for (Customer c : flagged) {
            ObjectNode root = MAPPER.createObjectNode();
            root.put("match_id", UUID.randomUUID().toString());
            root.put("customer_id", c.customerId());
            root.put("list_type", random.nextBoolean() ? "OFAC" : "LOCAL");
            root.put("entity_id", "ENT-" + (10000 + random.nextInt(90000)));
            root.put("matched_name", c.fullName() + " (alias)");
            root.put("match_score", 0.6 + random.nextDouble() * 0.4); // 0.6-1.0

            // Some are still potential, some confirmed, some dismissed
            String status;
            double s = random.nextDouble();
            if (s < 0.5) status = "POTENTIAL";
            else if (s < 0.8) status = "CONFIRMED";
            else status = "DISMISSED";

            root.put("status", status);
            root.put("reviewed_by", "analyst-" + (1 + random.nextInt(5)));
            root.put("reviewed_at", now.minus(randomBetween(1, 30), ChronoUnit.DAYS).toEpochMilli());

            String json = MAPPER.writeValueAsString(root);
            producer.send(new ProducerRecord<>(TOPIC_SANCTIONS_MATCHES, c.customerId(), json));
            System.out.println("Sent sanctions match: " + json);
            count++;
        }

        producer.flush();
        System.out.printf("Sent %d sanctions match records to topic %s%n", count, TOPIC_SANCTIONS_MATCHES);
    }

    private static void runTransactionLoop(List<Customer> customers,
                                           KafkaProducer<String, String> producer,
                                           long intervalMillis) throws Exception {
        Random random = new Random();

        // Choose a few "scenario" customers for more aggressive behavior
        List<Customer> structuringCustomers = pickRandom(customers, 3, random);
        List<Customer> highValueWireCustomers = pickRandom(customers, 3, random);

        long counter = 0;
        while (true) {
            Customer c = randomCustomer(customers, random);
            Instant ts = Instant.now();

            // Choose scenario
            double scenario = random.nextDouble();
            ObjectNode txn = MAPPER.createObjectNode();

            double amount;
            String country = c.residencyCountry();
            String merchantCategory;
            String channel;

            if (structuringCustomers.contains(c) && scenario < 0.5) {
                // Structuring: many small transactions, often cash/gambling
                amount = 800 + random.nextInt(1200); // around 1k
                merchantCategory = random.nextBoolean() ? "CASH" : "GAMBLING";
                channel = random.nextBoolean() ? "ATM" : "POS";
            } else if (highValueWireCustomers.contains(c) && scenario < 0.4) {
                // High-value: large international wires to high-risk countries
                amount = 15000 + random.nextInt(30000); // 15k-45k
                merchantCategory = "LUXURY";
                country = getRandom(HIGH_RISK_COUNTRIES, random);
                channel = "WEB";
            } else {
                // Normal behavior
                amount = 20 + random.nextInt(500);      // 20-520
                merchantCategory = getRandom(MERCHANT_CATEGORIES, random);
                channel = getRandom(CHANNELS, random);

                // Occasionally send to another country (if customer is low-risk)
                if (random.nextDouble() < 0.1) {
                    country = getRandom(LOW_RISK_COUNTRIES, random);
                }
            }

            String transactionId = "TX-" + (100000 + counter++);
            String accountId = "ACC-" + (10000 + random.nextInt(90000));
            String direction = random.nextBoolean() ? "DEBIT" : "CREDIT";

            txn.put("transaction_id", transactionId);
            txn.put("account_id", accountId);
            txn.put("customer_id", c.customerId());
            txn.put("amount", amount);
            txn.put("currency", "USD");
            txn.put("direction", direction);
            txn.put("counterparty_iban", "DE" + (1000000000L + random.nextInt(1_000_000_000)));
            txn.put("counterparty_name", "Counterparty " + random.nextInt(1000));
            txn.put("merchant_category", merchantCategory);
            txn.put("country_code", country);
            txn.put("channel", channel);
            txn.put("tx_timestamp", ts.toEpochMilli());

            String json = MAPPER.writeValueAsString(txn);
            producer.send(new ProducerRecord<>(TOPIC_TRANSACTIONS, c.customerId(), json));
            System.out.println("Sent transaction: " + json);

            if (counter % 100 == 0) {
                System.out.printf("Generated %d transactions...%n", counter);
            }

            TimeUnit.MILLISECONDS.sleep(intervalMillis);
        }
    }

    // ----------------------------
    // Helper methods
    // ----------------------------

    private static String randomName(Random random) {
        String[] firstNames = {"John", "Jane", "Alex", "Maria", "Ahmed", "Li", "Sara", "David", "Fatima", "Ivan"};
        String[] lastNames = {"Smith", "Doe", "Johnson", "Lee", "Garcia", "Khan", "Patel", "Kim", "Brown", "Ivanov"};
        return firstNames[random.nextInt(firstNames.length)] + " " +
                lastNames[random.nextInt(lastNames.length)];
    }

    private static String randomCheckType(Random random) {
        double v = random.nextDouble();
        if (v < 0.6) return "ONBOARDING";
        else if (v < 0.9) return "PERIODIC";
        else return "TRIGGERED";
    }

    private static long randomBetween(int minDays, int maxDays) {
        return ThreadLocalRandom.current().nextLong(minDays, maxDays + 1L);
    }

    private static <T> T getRandom(List<T> list, Random random) {
        return list.get(random.nextInt(list.size()));
    }

    private static Customer randomCustomer(List<Customer> customers, Random random) {
        return customers.get(random.nextInt(customers.size()));
    }

    private static List<Customer> pickRandom(List<Customer> customers, int n, Random random) {
        List<Customer> list = new ArrayList<>(customers);
        Collections.shuffle(list, random);
        return list.subList(0, Math.min(n, list.size()));
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
