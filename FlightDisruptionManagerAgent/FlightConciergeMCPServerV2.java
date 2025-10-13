package io.deltastream.datagen.random.flight;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.*;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.*;

/**
 * Minimal MCP server over HTTP (single /mcp endpoint).
 * Implements: initialize, tools/list, tools/call (get_passenger_context)
 *
 * Run:
 *   DS_STATEMENTS_URL=https://api-XXXX.deltastream.io/v2/statements \
 *   DS_AUTH_TOKEN=*** \
 *   PORT=8080 java io.deltastream.datagen.random.flight.FlightConciergeMCPServer
 *
 * Test with MCP Inspector or Agent Builder using your ngrok URL ending in /mcp
 */
public class FlightConciergeMCPServerV2 {
    private static final ObjectMapper M = new ObjectMapper();
    private static final HttpClient HTTP = HttpClient.newHttpClient();

    private static final String PROTOCOL_VERSION = "2024-11-05"; // negotiated version (spec example)
    private static final String SERVER_NAME = "FlightConcierge-MCP";
    private static final String SERVER_VERSION = "0.1.0";

    // Env-configured secrets/urls
    private static final String DS_STATEMENTS_URL = "https://api-{Your ORG custom URL}.deltastream.io/v2/statements";
    private static final String DS_AUTH_TOKEN     = "YOUR DELTASTREAM TOKEN";

    public static void main(String[] args) throws IOException {
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8080"));
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", port), 0);
        server.createContext("/mcp", new McpHandler());
        server.setExecutor(null);
        System.out.println("[MCP] Listening on : " + port + "  (POST /mcp)");
        server.start();
    }

    static class McpHandler implements HttpHandler {
        @Override public void handle(HttpExchange ex) throws IOException {
            // Basic CORS for Agent Builder (browser)
            Headers h = ex.getResponseHeaders();
            h.add("Access-Control-Allow-Origin", "*"); // lock this down to your builder origin in prod
            h.add("Access-Control-Allow-Headers", "Content-Type, Authorization, MCP-Protocol-Version, Mcp-Session-Id");
            h.add("Access-Control-Allow-Methods", "POST, OPTIONS");
            h.set("Vary", "Origin");
            if ("OPTIONS".equalsIgnoreCase(ex.getRequestMethod())) {
                send(ex, 204, "");
                return;
            }
            if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
                sendJson(ex, 405, error(null, -32600, "Only POST is supported"));
                return;
            }

            // when sending JSON:
            ex.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");

            // Read JSON-RPC request
            JsonNode root;
            try (InputStream is = ex.getRequestBody()) {
                root = M.readTree(is);
            } catch (Exception e) {
                sendJson(ex, 400, error(null, -32700, "Invalid JSON"));
                return;
            }

            List<JsonNode> requests = new ArrayList<>();
            if (root.isArray()) {
                root.forEach(requests::add);
            } else {
                requests.add(root);
            }

            // process each request and collect responses (batch replies are allowed)
            List<Object> responses = new ArrayList<>();
            for (JsonNode req : requests) {
                Object resp = handleOne(ex, req);   // returns a map for success/error, or null for notifications
                if (resp != null) responses.add(resp);
            }

            // Send one object or an array depending on input
            if (root.isArray()) {
                sendJson(ex, 200, responses);
            } else {
                sendJson(ex, 200, responses.isEmpty() ? Map.of() : responses.get(0));
            }
        }

        private Object handleOne(HttpExchange ex, JsonNode req) throws IOException {
            String jsonrpc = text(req, "jsonrpc");
            String method  = text(req, "method");
            JsonNode id    = req.get("id");
            JsonNode params = req.path("params");

            if (!"2.0".equals(jsonrpc) || method == null) {
                return error(id, -32600, "Invalid JSON-RPC envelope");
            }

            try {
                switch (method) {
                    case "initialize" -> {
                        String negotiated = PROTOCOL_VERSION; // simple negotiation
                        Map<String,Object> result = map(
                                "protocolVersion", negotiated,
                                "capabilities", map("tools", map("listChanged", true)),
                                "serverInfo", map("name", SERVER_NAME, "title", "DeltaStream Flight Concierge MCP", "version", SERVER_VERSION)
                        );
                        return ok(id, result);
                    }
                    case "tools/list" -> {
                        Map<String,Object> tool = map(
                                "name", "get_passenger_context",
                                "description", "Fetch disruption context for a passenger_id from DeltaStream.",
                                "inputSchema", map(
                                        "type", "object",
                                        "properties", map(
                                                "passenger_id", map("type","string","description","Passenger ID like PASS-2451")
                                        ),
                                        "required", List.of("passenger_id"),
                                        "additionalProperties", false
                                )
                        );
                        return ok(id, map("tools", List.of(tool), "nextCursor", null));
                    }
                    case "tools/call" -> {
                        String name = params.path("name").asText();
                        JsonNode args = params.path("arguments");
                        if (!"get_passenger_context".equals(name)) return error(id, -32601, "Unknown tool: " + name);

                        String passengerId = args.path("passenger_id").asText(null);
                        if (passengerId == null || passengerId.isBlank()) return error(id, -32602, "passenger_id is required");

                        Map<String,Object> dsResult = queryDeltaStream(passengerId);
                        Map<String,Object> toolResult = map(
                                "content", List.of(map("type","text","text", M.writeValueAsString(dsResult))),
                                "structuredContent", dsResult,
                                "isError", false
                        );
                        return ok(id, toolResult);
                    }
                    // Some clients send notifications you can safely ignore:
                    case "notifications/initialized", "notifications/cancelled" -> {
                        return null; // notifications have no id/response
                    }
                    default -> {
                        return error(id, -32601, "Method not found: " + method);
                    }
                }
            } catch (Exception e) {
                e.printStackTrace();
                return error(id, -32603, "Internal error: " + e.getMessage());
            }
        }


        // --- DeltaStream bridge (reuses your logic, but safer & env-based) ---
        private Map<String,Object> queryDeltaStream(String passengerId) throws IOException, BadGateway, InterruptedException {
            if (DS_STATEMENTS_URL.isBlank() || DS_AUTH_TOKEN.isBlank()) {
                throw new BadGateway("DS_STATEMENTS_URL or DS_AUTH_TOKEN not set");
            }
            String sql = "SELECT * FROM flightdb.public.disrupted_premium_passengers WHERE passenger_id = ?;";
            // very basic paramization: let DS handle prepared statements if supported;
            // fall back to safe quoted string
            sql = sql.replace("?", "'" + passengerId.replace("'", "''") + "'");

            Map<String, String> body = Map.of("statement", sql);
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(DS_STATEMENTS_URL))
                    .header("Authorization", "Bearer " + DS_AUTH_TOKEN)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(M.writeValueAsString(body)))
                    .build();

            HttpResponse<String> resp = HTTP.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) {
                throw new BadGateway("HTTP " + resp.statusCode() + " from DeltaStream");
            }
            return formatDeltaStream(resp.body());
        }

        // Parse DS response into a structured object { rows: [...], rowCount: N, columns: [...] }
        private Map<String,Object> formatDeltaStream(String dsJson) throws IOException {
            JsonNode root = M.readTree(dsJson);
            JsonNode cols = root.path("metadata").path("columns");
            JsonNode data = root.path("data");

            List<String> columnNames = new ArrayList<>();
            for (JsonNode c : cols) columnNames.add(c.path("name").asText());

            List<Map<String,Object>> rows = new ArrayList<>();
            for (JsonNode row : data) {
                Map<String,Object> m = new LinkedHashMap<>();
                for (int i = 0; i < columnNames.size(); i++) {
                    m.put(columnNames.get(i), i < row.size() ? M.convertValue(row.get(i), Object.class) : null);
                }
                rows.add(m);
            }
            return map(
                    "columns", columnNames,
                    "rowCount", rows.size(),
                    "rows", rows
            );
        }

        // --- small utils ---
        private static String text(JsonNode node, String field) { return node.has(field) ? node.get(field).asText() : null; }
        private static Map<String,Object> map(Object... kv) {
            Map<String,Object> m = new LinkedHashMap<>();
            for (int i=0; i<kv.length; i+=2) m.put((String) kv[i], kv[i+1]);
            return m;
        }
        private static byte[] bytes(Object o) throws IOException { return (o instanceof String s) ? s.getBytes(StandardCharsets.UTF_8) : M.writeValueAsBytes(o); }
        private static void send(HttpExchange ex, int status, String body) throws IOException {
            ex.sendResponseHeaders(status, body.getBytes(StandardCharsets.UTF_8).length);
            try (OutputStream os = ex.getResponseBody()) { os.write(body.getBytes(StandardCharsets.UTF_8)); }
        }
        private static void sendJson(HttpExchange ex, int status, Object body) throws IOException {
            ex.getResponseHeaders().set("Content-Type", "application/json");
            send(ex, status, new String(bytes(body), StandardCharsets.UTF_8));
        }
        private static Map<String,Object> ok(JsonNode id, Object result) { return Map.of("jsonrpc","2.0","id", id==null?null:id, "result", result); }
        private static Map<String,Object> error(JsonNode id, int code, String msg) {
            return Map.of("jsonrpc","2.0","id", id==null?null:id, "error", Map.of("code", code, "message", msg));
        }
        private static Map<String,Object> toolError(JsonNode id, String msg) {
            return Map.of("jsonrpc","2.0","id", id==null?null:id, "result", Map.of(
                    "content", List.of(Map.of("type","text","text", msg)),
                    "isError", true
            ));
        }
        static class BadGateway extends Exception { public BadGateway(String m){ super(m);} }
    }
}
