package io.deltastream.datagen.random.csa;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.LocalTime;

public class ProactiveAgent {

    // Configuration for the agent
    private static final String MCP_SERVER_BASE_URL = "http://localhost:4567/context/";
    private static final String USER_TO_MONITOR = "user_123";
    private static final int CHECK_INTERVAL_SECONDS = 10;

    private static final HttpClient httpClient = HttpClient.newHttpClient();
    private static final ObjectMapper objectMapper = new ObjectMapper();

    public static void main(String[] args) {
        System.out.println("🚀 Proactive Agent started. Monitoring user: " + USER_TO_MONITOR);
        System.out.println("---------------------------------------------------------");

        // The main agent loop, runs forever
        while (true) {
            try {
                System.out.println("[" + LocalTime.now().withNano(0) + "] Checking user context...");
                decideNextAction(USER_TO_MONITOR);
                Thread.sleep(CHECK_INTERVAL_SECONDS * 1000);
            } catch (InterruptedException e) {
                System.err.println("Agent loop interrupted.");
                Thread.currentThread().interrupt();
                break;
            } catch (Exception e) {
                System.err.println("An error occurred in the agent loop: " + e.getMessage());
            }
        }
    }

    /**
     * The core logic of the agent. It fetches context and decides whether to act.
     * @param userId The user to check.
     */
    public static void decideNextAction(String userId) {
        // 1. Call the MCP Server to get the user's real-time context
        CSAContext currentUserContext = callMcpServer(userId);

        if (currentUserContext == null) {
            System.out.println(" -> No context found for user. No action taken.");
            return;
        }

        System.out.println(" -> Fetched Context: " + currentUserContext);

        // 2. Use the context to reason about the user's intent
        boolean isStuck = currentUserContext.distinctPagesVisited10m >= 5 &&
                currentUserContext.itemsAddedToCart10m == 0;

        boolean isHesitatingAtCheckout = currentUserContext.page_visited_list.endsWith("/checkout") &&
                currentUserContext.chat_message_list == null;

        // 3. Take a proactive action if a condition is met
        if (isStuck) {
            System.out.println(" -> Condition met: User appears to be stuck.");
            sendProactiveChatMessage(userId, "Having trouble finding what you're looking for? I can help!");
        } else if (isHesitatingAtCheckout) {
            System.out.println(" -> Condition met: User is hesitating at checkout.");
            offerDiscount(userId, "10_PERCENT_OFF");
        } else {
            System.out.println(" -> Conditions not met. No action taken.");
        }
    }

    /**
     * Fetches the real-time context for a given user from our MCP Server.
     * @param userId The user ID to query.
     * @return A Context object, or null if not found or an error occurs.
     */
    private static CSAContext callMcpServer(String userId) {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(MCP_SERVER_BASE_URL + userId))
                    .GET()
                    .build();

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());

            if (response.statusCode() == 200) {
                return objectMapper.readValue(response.body(), CSAContext.class);
            } else {
                return null; // User context might not exist yet
            }
        } catch (Exception e) {
            System.err.println(" -> Error calling MCP Server: " + e.getMessage());
            return null;
        }
    }

    // --- Placeholder Action Methods ---

    /**
     * Simulates sending a proactive chat message to the user.
     */
    private static void sendProactiveChatMessage(String userId, String message) {
        System.out.println("   🔥 ACTION: Sending proactive chat to " + userId + ": '" + message + "'");
    }

    /**
     * Simulates offering a discount to the user.
     */
    private static void offerDiscount(String userId, String discountCode) {
        System.out.println("   🔥 ACTION: Offering discount " + discountCode + " to " + userId);
    }

}

