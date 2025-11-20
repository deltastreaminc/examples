package io.deltastream.datagen.random.cybersecurity1;

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

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.time.Instant;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Random;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;

public class CyberSecurityEventGenerator {

    // --- Configuration: Point this to your Kafka broker ---
    private static final String KAFKA_BOOTSTRAP_SERVERS = "your kafka bootstrap url:9092";
    private static final String KAFKA_API_KEY = "Your Kafka API Key";
    private static final String KAFKA_API_SECRET = "Your Kafka API Secret";

    private static final String AUTH_TOPIC   = "cyber_auth_events";
    private static final String FLOW_TOPIC   = "cyber_network_flows";
    private static final String IDS_TOPIC    = "cyber_ids_alerts";

    private final KafkaProducer<String, String> producer;
    private final ObjectMapper mapper = new ObjectMapper();
    private final Random random = new Random();

    private final List<String> users = List.of("alice", "bob", "carol", "dave");
    private final List<String> locations = List.of("US-CA", "US-NY", "DE-BE", "IN-KA");
    private final List<String> ips = List.of("10.0.0.25", "10.0.0.26", "10.0.1.10", "192.168.1.5");
    private final List<String> idsSignatures = List.of(
            "Brute force login",
            "Port scan",
            "Data exfiltration",
            "Suspicious DNS query"
    );
    private final List<String> severities = List.of("LOW", "MEDIUM", "HIGH", "CRITICAL");

    public CyberSecurityEventGenerator() {
        Properties props = new Properties();
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

            recreateTopic(adminClient, AUTH_TOPIC, 1, (short) 3, new HashMap<>());
            recreateTopic(adminClient, FLOW_TOPIC, 1, (short) 3, new HashMap<>());
            recreateTopic(adminClient, IDS_TOPIC, 1, (short) 3, new HashMap<>());
        } catch (Exception e) {
            System.err.println("Failed to initialize AdminClient: " + e.getMessage());
            e.printStackTrace();
        }

        this.producer = new KafkaProducer<>(props);
    }

    private ObjectNode baseEvent() {
        ObjectNode node = mapper.createObjectNode();
        node.put("event_timestamp", System.currentTimeMillis());
        return node;
    }

    private void sendAuthEvent() {
        ObjectNode event = baseEvent();
        String user = users.get(random.nextInt(users.size()));
        String srcIp = ips.get(random.nextInt(ips.size()));

        boolean isFailure = random.nextDouble() < 0.35; // 35% fail rate
        boolean mfaUsed = !isFailure && random.nextDouble() < 0.7;

        event.put("user_id", user);
        event.put("src_ip", srcIp);
        event.put("location", locations.get(random.nextInt(locations.size())));
        event.put("device_id", "device-" + random.nextInt(1000));
        event.put("outcome", isFailure ? "FAIL" : "SUCCESS");
        event.put("mfa_used", mfaUsed);
        event.put("ts", System.currentTimeMillis());

        String key = user;
        producer.send(new ProducerRecord<>(AUTH_TOPIC, key, event.toString()));
        System.out.println("Sent auth event: " + event.toString());
    }

    private void sendNetworkFlow() {
        ObjectNode event = baseEvent();
        String srcIp = ips.get(random.nextInt(ips.size()));

        event.put("src_ip", srcIp);
        event.put("dest_ip", "198.51.100." + (10 + random.nextInt(20)));
        event.put("dest_port", randomDestPort());
        event.put("protocol", "TCP");
        event.put("bytes_sent", 500 + random.nextInt(200_000));
        event.put("ts", System.currentTimeMillis());

        String key = srcIp;
        producer.send(new ProducerRecord<>(FLOW_TOPIC, key, event.toString()));
        System.out.println("Sent network flow: " + event.toString());
    }

    private void sendIdsAlert() {
        // Only emit sometimes so alerts are rarer
        if (random.nextDouble() > 0.15) return;

        ObjectNode event = baseEvent();
        String srcIp = ips.get(random.nextInt(ips.size()));

        event.put("src_ip", srcIp);
        event.put("signature", idsSignatures.get(random.nextInt(idsSignatures.size())));
        event.put("severity", severities.get(random.nextInt(severities.size())));
        event.put("ts", System.currentTimeMillis());

        String key = srcIp;
        producer.send(new ProducerRecord<>(IDS_TOPIC, key, event.toString()));
        System.out.println("Sent IDS alert: " + event.toString());
    }

    private int randomDestPort() {
        double r = random.nextDouble();
        if (r < 0.1) return 22;     // ssh
        if (r < 0.2) return 3389;   // rdp
        if (r < 0.5) return 443;    // https
        if (r < 0.7) return 53;     // dns
        return 1024 + random.nextInt(50000);
    }

    public void run() throws InterruptedException {
        while (true) {
            sendAuthEvent();
            sendNetworkFlow();
            sendIdsAlert();
            // small sleep to simulate streaming
            TimeUnit.MILLISECONDS.sleep(300);
        }
    }

    public static void main(String[] args) throws Exception {
        CyberSecurityEventGenerator generator = new CyberSecurityEventGenerator();
        generator.run();
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
