
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.Producer;
import org.apache.kafka.clients.producer.ProducerRecord;

import java.util.Properties;
import java.util.Random;
import java.util.UUID;
import java.util.List;
import java.util.Arrays;

public class MediaInteractionSimulator {

    // --- Configuration ---
    // IMPORTANT: Change this to your Kafka broker address
    private static final String KAFKA_BROKER = "KAFKA_BOOTSTRAP_URL";
    private static final String TOPIC_NAME = "user_interaction_stream";
    private static final String CONTENT_METADATA_TOPIC = "content_metadata";

    // ---------------------

    private static final Random random = new Random();
    private static final ObjectMapper objectMapper = new ObjectMapper(); // Re-use ObjectMapper for efficiency

    // Sample data to make the simulation realistic
    private static final List<String> USERS = Arrays.asList(
            "alex_4b3c", "ben_f9a1", "chloe_d2e5", "david_9c8f");

    private static final List<Content> CONTENT_CATALOG = Arrays.asList(
            new Content("tt8760708", "The Last of Us", "Drama"),
            new Content("tt1190634", "The Boys", "Action"),
            new Content("tt0264235", "Curb Your Enthusiasm", "Comedy"),
            new Content("tt13821990", "Hacks", "Comedy"),
            new Content("tt0113101", "The Fugitive", "Action"),
            new Content("tt0110357", "The Lion King", "Animation"),
            new Content("tt7286456", "Joker", "Drama"),
            new Content("tt15398776", "Oppenheimer", "Drama"),
            new Content("tt1517268", "Barbie", "Comedy")
    );


    private static final List<String> SEARCH_QUERIES = Arrays.asList(
            "new mystery movies", "90s comedies", "best sci-fi shows", "oscar winners", "what to watch tonight");


    public static void main(String[] args) throws InterruptedException {
        Properties props = new Properties();
        props.put("bootstrap.servers", KAFKA_BROKER);
        props.put("key.serializer", "org.apache.kafka.common.serialization.StringSerializer");
        props.put("value.serializer", "org.apache.kafka.common.serialization.StringSerializer");


        try (Producer<String, String> producer = new KafkaProducer<>(props)) {
            System.out.println("Starting Media Interaction Simulator...");

            // Publish the entire content catalog once at the start
            publishContentMetadata(producer);

            System.out.println("Publishing to topic: " + TOPIC_NAME);
            System.out.println("Press Ctrl+C to stop.");


            while (true) {
                // Simulate a user taking an action every 1-3 seconds
                Thread.sleep(random.nextInt(2000) + 1000);
                generateAndSendEvent(producer);
            }
        }
    }

    private static void publishContentMetadata(Producer<String, String> producer) {
        System.out.println("Publishing content catalog to topic: " + CONTENT_METADATA_TOPIC);
        for (Content content : CONTENT_CATALOG) {
            ObjectNode contentJson = objectMapper.createObjectNode();
            contentJson.put("ts_long", System.currentTimeMillis());
            contentJson.put("content_id", content.id);
            contentJson.put("title", content.title);
            contentJson.put("genres", content.genres);
            try {
                String payload = objectMapper.writeValueAsString(contentJson);
                // Use content_id as the key for compaction
                ProducerRecord<String, String> record = new ProducerRecord<>(CONTENT_METADATA_TOPIC, content.id, payload);
                producer.send(record);
            } catch (JsonProcessingException e) {
                System.err.println("Error serializing content metadata: " + e.getMessage());
            }
        }
        System.out.println("Finished publishing content catalog.");
    }

    private static void generateAndSendEvent(Producer<String, String> producer) {
        String user = USERS.get(random.nextInt(USERS.size()));
        // Use Jackson's ObjectNode to build the JSON object
        ObjectNode event = objectMapper.createObjectNode();
        event.put("user_id", user);
        event.put("event_ts_long", System.currentTimeMillis()); // Renamed for clarity in DeltaStream

        int eventType = random.nextInt(100);

        // Simulate a distribution of event types
        if (eventType < 5) { // 5% chance of a search
            event.put("event_type", "search");
            event.put("search_query", SEARCH_QUERIES.get(random.nextInt(SEARCH_QUERIES.size())));
        } else if (eventType < 35) { // 30% chance of viewing details
            event.put("event_type", "view_details");
            event.put("content_id", CONTENT_CATALOG.get(random.nextInt(CONTENT_CATALOG.size())).id);
            event.put("duration_ms", random.nextInt(10000) + 2000); // viewed for 2-12 seconds
        } else if (eventType < 70) { // 35% chance of a hover
            event.put("event_type", "hover");
            event.put("content_id", CONTENT_CATALOG.get(random.nextInt(CONTENT_CATALOG.size())).id);
            event.put("duration_ms", random.nextInt(3000) + 500); // hovered for 0.5-3.5 seconds
        } else { // 30% chance of a play event
            event.put("event_type", "play");
            event.put("content_id", CONTENT_CATALOG.get(random.nextInt(CONTENT_CATALOG.size())).id);
        }

        try {
            String eventPayload = objectMapper.writeValueAsString(event);
            ProducerRecord<String, String> record = new ProducerRecord<>(TOPIC_NAME, user, eventPayload);

            producer.send(record, (metadata, exception) -> {
                if (exception != null) {
                    System.err.println("Error publishing record: " + exception.getMessage());
                } else {
                    System.out.println("Published event: " + eventPayload);
                }
            });
        } catch (JsonProcessingException e) {
            System.err.println("Error serializing event to JSON: " + e.getMessage());
        }
    }

    // Simple inner class to hold content metadata
    private static class Content {
        String id;
        String title;
        String genres;

        Content(String id, String title, String genres) {
            this.id = id;
            this.title = title;
            this.genres = genres;
        }
    }
}

