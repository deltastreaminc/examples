import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.Producer;
import org.apache.kafka.clients.producer.ProducerRecord;

import java.util.Properties;
import java.util.Random;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class DeFiEventGenerator {

    // --- Kafka Configuration ---
    private static final String KAFKA_BOOTSTRAP_SERVERS = "Kafka broker url";
    private static final String TRANSACTIONS_TOPIC = "onchain_transactions";
    private static final String PRICES_TOPIC = "dex_prices";
    private static final String MEMPOOL_TOPIC = "mempool_data";

    private static final Producer<String, String> producer;
    private static final ObjectMapper mapper = new ObjectMapper();
    private static final Random random = new Random();
    private static long currentBlock = 18000000;

    // --- DeFi Simulation Constants ---
    private static final String FLASH_LOAN_PROVIDER = "0xA9754f1D6516a24A413148Db4534A4684344C1fE"; // Simulated Aave Pool
    private static final String DEX_ROUTER = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"; // Simulated Uniswap V2 Router

    static {
        Properties props = new Properties();
        props.put("bootstrap.servers", KAFKA_BOOTSTRAP_SERVERS);
        props.put("key.serializer", "org.apache.kafka.common.serialization.StringSerializer");
        props.put("value.serializer", "org.apache.kafka.common.serialization.StringSerializer");

        producer = new KafkaProducer<>(props);
    }

    public static void main(String[] args) {
        ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(2);
        // Generate normal background traffic every 5 seconds
        scheduler.scheduleAtFixedRate(DeFiEventGenerator::generateNormalTraffic, 0, 5, TimeUnit.SECONDS);
        // Trigger a coordinated flash loan attack every 2 minutes
        scheduler.scheduleAtFixedRate(DeFiEventGenerator::generateFlashLoanAttack, 0, 2, TimeUnit.MINUTES);
        System.out.println("Started generating real-time on-chain data...");
    }

    /**
     * Generates a sequence of correlated events simulating a flash loan attack.
     */
    public static void generateFlashLoanAttack() {
        try {
            String attackerAddress = "0x" + UUID.randomUUID().toString().replace("-", "");//.substring(0, 40);
            long eventTime = System.currentTimeMillis();
            currentBlock++;

            System.out.println("\n\n🚨 --- SIMULATING FLASH LOAN ATTACK by " + attackerAddress + " at block " + currentBlock + " --- 🚨\n");

            // 1. Attacker takes a massive flash loan of 50M DAI
            ObjectNode loanTx = createTransaction(
                    FLASH_LOAN_PROVIDER, attackerAddress, "DAI", 50_000_000, currentBlock, eventTime);
            sendMessage(TRANSACTIONS_TOPIC, attackerAddress, mapper.writeValueAsString(loanTx));
            System.out.println("1. Attacker takes 50M DAI flash loan.");
            Thread.sleep(1000);

            // 2. Attacker uses the DAI to manipulate a low-liquidity pool on a DEX
            ObjectNode swapTx = createTransaction(
                    attackerAddress, DEX_ROUTER, "DAI", 50_000_000, currentBlock, eventTime + 100);
            sendMessage(TRANSACTIONS_TOPIC, attackerAddress, mapper.writeValueAsString(swapTx));
            System.out.println("2. Attacker swaps DAI for WETH, causing price slippage.");
            Thread.sleep(1000);

            // 3. The price of WETH/DAI on the DEX plummets due to the large trade
            ObjectNode priceUpdate = mapper.createObjectNode();
            priceUpdate.put("event_timestamp", eventTime + 200);
            priceUpdate.put("token_pair", "WETH/DAI");
            priceUpdate.put("price", 1850.75); // Price drops from a normal ~2300
            sendMessage(PRICES_TOPIC, "WETH/DAI", mapper.writeValueAsString(priceUpdate));
            System.out.println("3. DEX price oracle for WETH/DAI reports anomalous drop.");
            Thread.sleep(1000);

            // 4. A huge gas spike is observed in the mempool
            ObjectNode gasSpike = mapper.createObjectNode();
            gasSpike.put("event_timestamp", eventTime + 300);
            gasSpike.put("block_number", currentBlock);
            gasSpike.put("avg_gas_price_gwei", 250); // Spike from normal ~30 Gwei
            sendMessage(MEMPOOL_TOPIC, String.valueOf(currentBlock), mapper.writeValueAsString(gasSpike));
            System.out.println("4. Mempool shows massive gas spike.");
            Thread.sleep(1000);

            // 5. Attacker repays the flash loan in the same block
            ObjectNode repayTx = createTransaction(
                    attackerAddress, FLASH_LOAN_PROVIDER, "DAI", 50_000_000.1, currentBlock, eventTime + 500); // Repay with small fee
            sendMessage(TRANSACTIONS_TOPIC, attackerAddress, mapper.writeValueAsString(repayTx));
            System.out.println("5. Attacker repays the 50M DAI flash loan.");

        } catch (Exception e) {
            Thread.currentThread().interrupt();
            e.printStackTrace();
        }
    }

    public static void generateNormalTraffic() {
        try {
            currentBlock++;
            long eventTime = System.currentTimeMillis();
            // Normal trade
            sendMessage(TRANSACTIONS_TOPIC, "normal_trade", mapper.writeValueAsString(
                    createTransaction("0xUserA", "0xUserB", "USDC", 1000, currentBlock, eventTime)));
            // Normal price update
            ObjectNode priceUpdate = mapper.createObjectNode();
            priceUpdate.put("event_timestamp", eventTime);
            priceUpdate.put("token_pair", "WETH/DAI");
            priceUpdate.put("price", 2300.0 + (random.nextDouble() * 10 - 5));
            priceUpdate.put("join_helper", "A");
            sendMessage(PRICES_TOPIC, "WETH/DAI", mapper.writeValueAsString(priceUpdate));
            // Normal gas price
            ObjectNode gasUpdate = mapper.createObjectNode();
            gasUpdate.put("event_timestamp", eventTime);
            gasUpdate.put("block_number", currentBlock);
            gasUpdate.put("avg_gas_price_gwei", 30 + random.nextInt(10));
            sendMessage(MEMPOOL_TOPIC, String.valueOf(currentBlock), mapper.writeValueAsString(gasUpdate));

            System.out.print("."); // Progress indicator
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private static ObjectNode createTransaction(String from, String to, String token, double amount, long block, long ts) {
        ObjectNode tx = mapper.createObjectNode();
        tx.put("tx_hash", "0x" + UUID.randomUUID().toString().replace("-", ""));
        tx.put("block_number", block);
        tx.put("event_timestamp", ts);
        tx.put("from_address", from);
        tx.put("to_address", to);
        tx.put("tx_token", token);
        tx.put("tx_amount", amount);
        return tx;
    }

    private static void sendMessage(String topic, String key, String value) {
        System.out.println("Sending to " + topic + ": " + value);
        producer.send(new ProducerRecord<>(topic, key, value));
        producer.flush();
    }
}

