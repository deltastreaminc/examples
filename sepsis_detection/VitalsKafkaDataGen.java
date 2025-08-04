import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.serialization.StringSerializer;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.*;


public class VitalsKafkaDataGen {

    // --- Configuration ---
    private static final String KAFKA_BROKER = "bootstrap_url";
    private static final String KAFKA_TOPIC = "bio_vitals";
    private static final int NUM_PATIENTS = 10; // Number of patients to simulate
    private static final int DATA_INTERVAL_SECONDS = 5; // How often to send data

    // --- Patient Simulation Setup ---
    private static final List<String> patientIds = new ArrayList<>();
    private static final Map<String, Vitals> patientStates = new HashMap<>();
    private static final List<String> atRiskPatients = new ArrayList<>();
    private static final Random random = new Random();
    private static final ObjectMapper objectMapper = new ObjectMapper();

    private static DateTimeFormatter customFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS");


    // Inner class to represent the vitals data (POJO)
    static class Vitals {
        public String patient_id;
        public String event_timestamp;
        public int heart_rate_bpm;
        public int respiratory_rate_rpm;
        public double skin_temp_c;
        public String activity_level;

        // Default constructor for initial state
        public Vitals(String patient_id, int hr, int rr, double temp) {
            this.patient_id = patient_id;
            this.heart_rate_bpm = hr;
            this.respiratory_rate_rpm = rr;
            this.skin_temp_c = temp;
        }

        // Copy constructor
        public Vitals(Vitals other) {
            this.patient_id = other.patient_id;
            this.event_timestamp = other.event_timestamp;
            this.heart_rate_bpm = other.heart_rate_bpm;
            this.respiratory_rate_rpm = other.respiratory_rate_rpm;
            this.skin_temp_c = other.skin_temp_c;
            this.activity_level = other.activity_level;
        }
    }

    public static void main(String[] args) {
        // Initialize patient data
        for (int i = 0; i < NUM_PATIENTS; i++) {
            String id = "PID-" + (1000 + i);
            patientIds.add(id);
            patientStates.put(id, new Vitals(id, 75, 16, 37.0));
        }

        // Designate five random patients as at-risk
        Collections.shuffle(patientIds);
        atRiskPatients.add(patientIds.get(0));
        atRiskPatients.add(patientIds.get(1));
        System.out.println("Simulating " + NUM_PATIENTS + " patients. At-risk patients: " + atRiskPatients);

        // Create Kafka Producer
        try (KafkaProducer<String, String> producer = createKafkaProducer()) {
            System.out.println("Successfully connected to Kafka.");

            // Add a shutdown hook to close the producer gracefully
            Runtime.getRuntime().addShutdownHook(new Thread(producer::close));

            while (true) {
                for (String patientId : patientIds) {
                    Vitals vitalsData = generateVitals(patientId);
                    String vitalsJson = objectMapper.writeValueAsString(vitalsData);

                    System.out.println("Sending data for " + patientId + ": " + vitalsJson);

                    // Send data to Kafka
                    ProducerRecord<String, String> record = new ProducerRecord<>(KAFKA_TOPIC, patientId, vitalsJson);
                    producer.send(record);
                }
                // Flush messages to ensure they are sent
                producer.flush();
                System.out.println("--- Batch sent. Waiting " + DATA_INTERVAL_SECONDS + " seconds. ---");
                Thread.sleep(DATA_INTERVAL_SECONDS * 1000);
            }
        } catch (Exception e) {
            System.err.println("An error occurred: " + e.getMessage());
            e.printStackTrace();
        }
    }

    private static KafkaProducer<String, String> createKafkaProducer() {
        Properties props = new Properties();
        props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA_BROKER);
        props.put(ProducerConfig.CLIENT_ID_CONFIG, "bio-vitals-producer-java");
        props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        return new KafkaProducer<>(props);
    }

    private static Vitals generateVitals(String patientId) {
        Vitals currentState = new Vitals(patientStates.get(patientId)); // Work on a copy

        if (atRiskPatients.contains(patientId) && random.nextDouble() < 0.15) { // 15% chance to worsen
            currentState.heart_rate_bpm += random.nextInt(3) + 1; // 1 to 3
            currentState.respiratory_rate_rpm += 1;
            currentState.skin_temp_c += (random.nextDouble() * 0.1) + 0.1; // 0.1 to 0.2
        } else {
            // Normal fluctuations
            currentState.heart_rate_bpm += random.nextInt(5) - 2; // -2 to 2
            currentState.respiratory_rate_rpm += random.nextInt(3) - 1; // -1, 0, or 1
            currentState.skin_temp_c += (random.nextDouble() * 0.2) - 0.1; // -0.1 to 0.1
        }

        // Clamp values to realistic ranges
        currentState.heart_rate_bpm = Math.max(60, Math.min(140, currentState.heart_rate_bpm));
        currentState.respiratory_rate_rpm = Math.max(12, Math.min(30, currentState.respiratory_rate_rpm));
        currentState.skin_temp_c = Math.round(Math.max(36.0, Math.min(40.0, currentState.skin_temp_c)) * 100.0) / 100.0;

        // Set timestamp and activity level
        currentState.event_timestamp = Instant.now().atZone(ZoneOffset.UTC).format(customFormatter) + "Z";
        currentState.activity_level = "REST";

        // Update the state for the next iteration
        patientStates.put(patientId, new Vitals(currentState));

        return currentState;
    }
}

