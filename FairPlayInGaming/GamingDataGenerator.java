package io.deltastream.datagen.random.gaming;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.serialization.StringSerializer;

import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Properties;
import java.util.Random;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class GamingDataGenerator {

    private static final String KAFKA_BOOTSTRAP_SERVERS = "YOUR_KAFKA_BOOTSTRAP_SERVERS:9092";
    private static final String KAFKA_API_KEY = "YOUR KAFKA_API_KEY ";
    private static final String KAFKA_API_SECRET = "YOUR KAFKA_API_SECRET";
    private static final String ACTIONS_TOPIC = "player_actions_kafka";
    private static final String HISTORY_TOPIC = "player_history_kafka"; // New topic for historical data
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Random RAND = new Random();
    private static final List<String> PLAYER_IDS = Arrays.asList(
            "Player-A-111", "Player-B-222", "Player-C-333", "Player-D-444", "Cheater-007"
    );
    private static final String CHEATER_ID = "Cheater-007";
    private static final List<String> WEAPONS = Arrays.asList("Rifle", "Pistol", "Sniper", "SMG");

    public static void main(String[] args) {
        System.out.println("Starting Gaming Data Generator...");
        System.out.println("Connecting to Kafka Broker at: " + KAFKA_BOOTSTRAP_SERVERS);

        Properties props = new Properties();
        props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA_BOOTSTRAP_SERVERS);
        props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put("security.protocol", "SASL_SSL");
        props.put("sasl.mechanism", "PLAIN");
        props.put("sasl.jaas.config", "org.apache.kafka.common.security.plain.PlainLoginModule required username=\"" + KAFKA_API_KEY + "\" password=\"" + KAFKA_API_SECRET + "\";");


        KafkaProducer<String, String> producer = new KafkaProducer<>(props);

        // Publish initial historical data for all players
        publishInitialPlayerHistory(producer);

        // Schedule the cheater to perform a cheat action periodically
        ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor();
        scheduler.scheduleAtFixedRate(() -> generateCheatSequence(producer, "match-1"), 5, 15, TimeUnit.SECONDS);

        // Main loop for generating normal player actions
        while (true) {
            try {
                String playerId = PLAYER_IDS.get(RAND.nextInt(PLAYER_IDS.size()));
                // Ensure cheater only generates cheat actions via the scheduler
                if (!playerId.equals(CHEATER_ID)) {
                    generateNormalAction(producer, playerId, "match-1");
                }
                Thread.sleep(50 + RAND.nextInt(100)); // Normal actions happen frequently
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            System.out.println("Shutting down...");
            producer.close();
            scheduler.shutdown();
        }));
    }

    private static void publishInitialPlayerHistory(KafkaProducer<String, String> producer) {
        System.out.println("Publishing initial player history...");
        for (String playerId : PLAYER_IDS) {
            try {
                ObjectNode history = MAPPER.createObjectNode();
                history.put("player_id", playerId);
                history.put("update_timestamp", Instant.now().toEpochMilli());

                if (playerId.equals(CHEATER_ID)) {
                    // Give the cheater a history of being a poor player
                    history.put("total_matches_played", 50);
                    history.put("historical_headshot_rate", 0.05); // 5%
                    history.put("historical_accuracy", 0.18);     // 18%
                } else {
                    // Give normal players respectable histories
                    history.put("total_matches_played", 200 + RAND.nextInt(1000));
                    history.put("historical_headshot_rate", 0.20 + (RAND.nextDouble() * 0.15)); // 20-35%
                    history.put("historical_accuracy", 0.40 + (RAND.nextDouble() * 0.20)); // 40-60%
                }
                String jsonHistory = MAPPER.writeValueAsString(history);
                producer.send(new ProducerRecord<>(HISTORY_TOPIC, playerId, jsonHistory));
                System.out.println("Published history for " + playerId + " : " + jsonHistory);
            } catch (Exception e) {
                e.printStackTrace();
            }
        }
    }


    private static void generateCheatSequence(KafkaProducer<String, String> producer, String matchId) {
        System.out.println("!!! Generating CHEAT sequence for " + CHEATER_ID + " !!!");
        String targetId = PLAYER_IDS.get(RAND.nextInt(PLAYER_IDS.size() -1)); // Target someone else
        String weapon = "Sniper";

        // 1. Normal AIM action
        sendAction(producer, matchId, CHEATER_ID, "AIM", weapon, targetId, false, 200 + RAND.nextInt(100));

        // 2. IMMEDIATE, inhumanly fast LOCK_ON_TARGET
        sendAction(producer, matchId, CHEATER_ID, "LOCK_ON_TARGET", weapon, targetId, false, RAND.nextInt(20)); // < 20ms reaction

        // 3. IMMEDIATE FIRE with guaranteed headshot
        sendAction(producer, matchId, CHEATER_ID, "FIRE", weapon, targetId, true, 0);
    }

    private static void generateNormalAction(KafkaProducer<String, String> producer, String playerId, String matchId) {
        String actionType = RAND.nextBoolean() ? "AIM" : "FIRE";
        String weapon = WEAPONS.get(RAND.nextInt(WEAPONS.size()));
        String targetId = PLAYER_IDS.get(RAND.nextInt(PLAYER_IDS.size()));
        boolean isHeadshot = actionType.equals("FIRE") && RAND.nextDouble() < 0.15; // 15% headshot chance for normal players
        int reactionTime = 150 + RAND.nextInt(150); // Normal human reaction times

        sendAction(producer, matchId, playerId, actionType, weapon, targetId, isHeadshot, reactionTime);
    }

    private static void sendAction(KafkaProducer<String, String> producer, String matchId, String playerId,
                                   String actionType, String weapon, String targetId, boolean isHeadshot, int reactionTimeMs) {
        try {
            ObjectNode action = MAPPER.createObjectNode();
            action.put("match_id", matchId);
            action.put("player_id", playerId);
            action.put("event_timestamp", Instant.now().toEpochMilli());
            action.put("action_type", actionType);
            action.put("weapon", weapon);
            action.put("target_id", targetId);
            action.put("is_headshot", isHeadshot);
            action.put("reaction_time_ms", reactionTimeMs);

            String jsonAction = MAPPER.writeValueAsString(action);
            producer.send(new ProducerRecord<>(ACTIONS_TOPIC, playerId, jsonAction));
            System.out.println("Sent action: " + jsonAction);
            if ("LOCK_ON_TARGET".equals(actionType)) {
                System.out.println(String.format(">>> Sent suspicious action: %s", jsonAction));
            }

        } catch (Exception e) {
            e.printStackTrace();
        }
    }
}
