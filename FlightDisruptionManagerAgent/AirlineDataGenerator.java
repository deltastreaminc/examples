package io.deltastream.datagen.random.flight;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.serialization.StringSerializer;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Properties;
import java.util.Random;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

public class AirlineDataGenerator {

    // --- Configuration: Point this to your Kafka broker ---
    private static final String KAFKA_BOOTSTRAP_SERVERS = "YOUR_KAFKA_BROKER_URL";
    private static final String KAFKA_API_KEY = "YOUR KAFKA API KEY";
    private static final String KAFKA_API_SECRET = "YOUR KAFKA SECRET";

    // --- Kafka Topics ---
    private static final String FLIGHT_EVENTS_TOPIC = "flight_events";
    private static final String BOOKING_EVENTS_TOPIC = "booking_events";
    private static final String CUSTOMER_PROFILES_TOPIC = "customer_profiles";

    // --- Sample Data ---
    private static final String[] AIRPORTS = {"SFO", "JFK", "LAX", "ORD", "ATL", "DFW"};
    private static final String[] FLIGHT_STATUSES = {"SCHEDULED", "DELAYED", "BOARDING", "DEPARTED", "ARRIVED"};
    private static final String[] LOYALTY_TIERS = {"PLATINUM", "GOLD", "SILVER", "BRONZE"};
    private static final String[] FIRST_NAMES = {"John", "Jane", "Peter", "Mary", "David", "Sarah"};
    private static final String[] LAST_NAMES = {"Smith", "Doe", "Jones", "Williams", "Brown", "Davis"};

    private static DateTimeFormatter customFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS");
    private static final Random random = new Random();
    private static final ObjectMapper objectMapper = new ObjectMapper();

    public static void main(String[] args) throws InterruptedException, JsonProcessingException {
        Properties props = new Properties();
        props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA_BOOTSTRAP_SERVERS);
        props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put("security.protocol", "SASL_SSL");
        props.put("sasl.mechanism", "PLAIN");
        props.put("sasl.jaas.config", "org.apache.kafka.common.security.plain.PlainLoginModule required username=\"" + KAFKA_API_KEY + "\" password=\"" + KAFKA_API_SECRET + "\";");


        KafkaProducer<String, String> producer = new KafkaProducer<>(props);
        System.out.println("Starting Airline Data Generator...");

        // Generate some initial customer profiles
        generateInitialCustomers(producer);

        Thread.sleep(1000);
        int flightCounter = 100;

        // Main simulation loop
        while (true) {
            String flightId = "UA" + (flightCounter++);
            String origin = AIRPORTS[random.nextInt(AIRPORTS.length)];
            String destination;
            do {
                destination = AIRPORTS[random.nextInt(AIRPORTS.length)];
            } while (origin.equals(destination));

            System.out.println("\n--- Simulating Flight: " + flightId + " ---");

            // 1. Announce the new flight
            ObjectNode flightEvent = createFlightEvent(flightId, "SCHEDULED", origin, destination);
            producer.send(new ProducerRecord<>(FLIGHT_EVENTS_TOPIC, flightId, objectMapper.writeValueAsString(flightEvent)));
            System.out.println("Sent: " + flightEvent);
            TimeUnit.SECONDS.sleep(1);

            // 2. Book some passengers for this flight
            int numPassengers = 5 + random.nextInt(10);
            for (int i = 0; i < numPassengers; i++) {
                String passengerId = "PASS-" + (1000 + random.nextInt(9000));
                ObjectNode bookingEvent = createBookingEvent(flightId, passengerId);
                producer.send(new ProducerRecord<>(BOOKING_EVENTS_TOPIC, flightId, objectMapper.writeValueAsString(bookingEvent)));
                System.out.println("Sent: " + bookingEvent);
                TimeUnit.MILLISECONDS.sleep(200);
            }

            // 3. Simulate a potential disruption (25% chance of cancellation)
            if (random.nextDouble() < 0.25) {
                System.out.println("!!! DISRUPTION ALERT: CANCELLING FLIGHT " + flightId + " !!!");
                ObjectNode cancelledEvent = createFlightEvent(flightId, "CANCELED", origin, destination);
                producer.send(new ProducerRecord<>(FLIGHT_EVENTS_TOPIC, flightId, objectMapper.writeValueAsString(cancelledEvent)));
                System.out.println("Sent: " + cancelledEvent);
            } else {
                ObjectNode delayedEvent = createFlightEvent(flightId, "DELAYED", origin, destination);
                producer.send(new ProducerRecord<>(FLIGHT_EVENTS_TOPIC, flightId, objectMapper.writeValueAsString(delayedEvent)));
                System.out.println("Sent: " + delayedEvent);
            }

            TimeUnit.SECONDS.sleep(5); // Wait before simulating the next flight
        }
    }

    private static void generateInitialCustomers(KafkaProducer<String, String> producer) throws JsonProcessingException {
        System.out.println("--- Generating Initial Customer Profiles ---");
        for (int i = 1000; i < 9999; i++) {
            String passengerId = "PASS-" + i;//+ (1000 + random.nextInt(9000));
            ObjectNode customerProfile = objectMapper.createObjectNode();
            customerProfile.put("passenger_id", passengerId);
            customerProfile.put("first_name", FIRST_NAMES[random.nextInt(FIRST_NAMES.length)]);
            customerProfile.put("last_name", LAST_NAMES[random.nextInt(LAST_NAMES.length)]);
            customerProfile.put("loyalty_tier", LOYALTY_TIERS[random.nextInt(LOYALTY_TIERS.length)]);
            customerProfile.put("update_timestamp", Instant.now().atZone(ZoneOffset.UTC).format(customFormatter) + "Z");

            ObjectNode prefs = objectMapper.createObjectNode();
            prefs.put("seating", random.nextBoolean() ? "AISLE" : "WINDOW");
            customerProfile.set("preferences", prefs);

            producer.send(new ProducerRecord<>(CUSTOMER_PROFILES_TOPIC, passengerId, objectMapper.writeValueAsString(customerProfile)));
        }
        producer.flush();
        System.out.println("Customer profiles sent.");
    }

    private static ObjectNode createFlightEvent(String flightId, String status, String origin, String destination) {
        ObjectNode event = objectMapper.createObjectNode();
        event.put("flight_id", flightId);
        event.put("flight_status", status);
        event.put("origin", origin);
        event.put("destination", destination);
        event.put("scheduled_departure", Instant.now().plusSeconds(3600).atZone(ZoneOffset.UTC).format(customFormatter) + "Z");
        event.put("event_timestamp", Instant.now().atZone(ZoneOffset.UTC).format(customFormatter) + "Z");

        return event;
    }

    private static ObjectNode createBookingEvent(String flightId, String passengerId) {
        ObjectNode event = objectMapper.createObjectNode();
        event.put("booking_id", UUID.randomUUID().toString());
        event.put("flight_id", flightId);
        event.put("passenger_id", passengerId);
        event.put("seat", (1 + random.nextInt(30)) + (new String[]{"A", "B", "C", "D", "E", "F"})[random.nextInt(6)]);
        event.put("booking_timestamp", Instant.now().atZone(ZoneOffset.UTC).format(customFormatter) + "Z");
        return event;
    }
}
