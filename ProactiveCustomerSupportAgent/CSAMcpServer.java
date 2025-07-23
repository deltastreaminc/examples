package io.deltastream.datagen.random.csa;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import static spark.Spark.*;

public class CSAMcpServer {

    // --- REPLACE WITH YOUR DELTASTREAM REST API CREDENTIALS ---
    private static final String DS_API_URL = "https://api-kap822.deltastream.io/v2";
    private static final String DS_SECRET_TOKEN = "Your DeltaStream Secret Token Here";
    private static final String DS_DATABASE = "csa";
    private static final String DS_SCHEMA = "public"; // e.g., "PUBLIC"
    // ----------------------------------------------------

    private static final HttpClient httpClient = HttpClient.newHttpClient();
    private static final ObjectMapper objectMapper = new ObjectMapper();

    public static void main(String[] args) {

        port(4567); // Server will run on http://localhost:4567

        // Define the API endpoint: GET /context/:userId
        get("/context/:userId", (req, res) -> {
            String userId = req.params(":userId");
            res.type("application/json");

            // 1. Construct the JSON payload for the DeltaStream API request
            ObjectNode payload = objectMapper.createObjectNode();
            payload.put("organization", "Your DeltaStream Organization ID Here");
            payload.put("role", "sysadmin");
            payload.put("database", DS_DATABASE);
            payload.put("schema", DS_SCHEMA);
            // Use a parameterized query to prevent SQL injection
            payload.put("statement", "SELECT * FROM live_customer_context_view WHERE user_id = '" + userId + "' ORDER BY window_end DESC LIMIT 1;");

            // 2. Build the HTTP request with the Authorization header
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(DS_API_URL + "/statements"))
                    .header("Authorization", "Bearer " + DS_SECRET_TOKEN)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(payload.toString()))
                    .build();

            try {
                // 3. Send the request and get the response
                HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());

                if (response.statusCode() == 200) {
                    // 4. Parse the JSON response from DeltaStream
                    JsonNode responseJson = objectMapper.readTree(response.body());
                    JsonNode dataNode = responseJson.at("/data/0");

                    if (dataNode.isArray() && !dataNode.isEmpty()) {
                        // The data is an array of arrays. Get the first row.
                        Object[] row = objectMapper.convertValue(dataNode, Object[].class);
                        CSAContext context = new CSAContext(row);

                        // Convert the Context object to a JSON string and return it
                        return objectMapper.writeValueAsString(context);
                    } else {
                        res.status(404);
                        return "{\"error\": \"Context not found for user: " + userId + "\"}";
                    }
                } else {
                    System.err.println("Error from DeltaStream API: " + response.body());
                    res.status(response.statusCode());
                    return response.body();
                }

            } catch (Exception e) {
                e.printStackTrace();
                res.status(500);
                return "{\"error\": \"Failed to process request: " + e.getMessage() + "\"}";
            }
        });
    }

}


