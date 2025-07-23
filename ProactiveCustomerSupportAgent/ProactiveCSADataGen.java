package io.deltastream.datagen.random.csa;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.serialization.StringSerializer;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Properties;
import java.util.Random;

public class ProactiveCSADataGen {

    private static final String KAFKA_BROKER = "YOUR_KAFKA_BROKER_ADDRESS";
    private static final ObjectMapper objectMapper = new ObjectMapper();
    private static final Random random = new Random();
    private static final String KAFKA_TOPIC_PAGEVIEWS = "csa_pageviews";
    private static final String KAFKA_TOPIC_CART_UPDATES = "csa_cart_updates";
    private static final String KAFKA_TOPIC_CHAT_MESSAGES = "csa_chat_messages";
    private static DateTimeFormatter customFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS");

    public static void main(String[] args) {
        Properties props = new Properties();
        props.put("bootstrap.servers", KAFKA_BROKER);
        props.put("key.serializer", StringSerializer.class.getName());
        props.put("value.serializer", StringSerializer.class.getName());
        KafkaProducer<String, String> producer = new KafkaProducer<>(props);

        // Simulate activity for two users
        String[] userIds = {"user_123", "user_456", "user_223", "user_356", "user_163", "user_466", "user_823", "user_856"};
        String[] pages = {"/products/A1", "/products/B2", "/checkout", "/support"};
        String[] cartActions = {"ADD", "REMOVE"};
        String[] chatMessages = {"is this in stock?", "how do I return an item?", "thanks for the help!"};

        while (true) {
            try {
                String userId = userIds[random.nextInt(userIds.length)];
                String eventTime = Instant.now().atZone(ZoneOffset.UTC).format(customFormatter) + "Z";

                // Send a page view
                ObjectNode pageView = objectMapper.createObjectNode();
                pageView.put("event_timestamp", eventTime);
                pageView.put("user_id", userId);
                pageView.put("page", pages[random.nextInt(pages.length)]);
                producer.send(new ProducerRecord<>(KAFKA_TOPIC_PAGEVIEWS, userId, pageView.toString()));
                System.out.println("Sent page_view: " + pageView.toString());

                // Occasionally send a cart update
                if (random.nextDouble() < 0.3) {
                    ObjectNode cartUpdate = objectMapper.createObjectNode();
                    cartUpdate.put("event_timestamp", eventTime);
                    cartUpdate.put("user_id", userId);
                    cartUpdate.put("cart_action", cartActions[random.nextInt(cartActions.length)]);
                    cartUpdate.put("item_id", "SKU" + random.nextInt(100));
                    producer.send(new ProducerRecord<>(KAFKA_TOPIC_CART_UPDATES, userId, cartUpdate.toString()));
                    System.out.println("Sent cart_update: " + cartUpdate.toString());
                }

                // Occasionally send a chat message
                if (random.nextDouble() < 0.15) {
                    ObjectNode chatMessage = objectMapper.createObjectNode();
                    chatMessage.put("event_timestamp", eventTime);
                    chatMessage.put("user_id", userId);
                    chatMessage.put("message", chatMessages[random.nextInt(chatMessages.length)]);
                    producer.send(new ProducerRecord<>(KAFKA_TOPIC_CHAT_MESSAGES, userId, chatMessage.toString()));
                    System.out.println("Sent chat_message: " + chatMessage.toString());
                }
                Thread.sleep((long)(Math.random() * 1000));
            } catch (Exception e) {
                e.printStackTrace();
            }
        }

    }
}


