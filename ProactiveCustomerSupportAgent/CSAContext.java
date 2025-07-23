package io.deltastream.datagen.random.csa;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public class CSAContext {
    public String window_start;
    public  String window_end;
    public String userId;
    public String page_visited_list;
    public int distinctPagesVisited10m;
    public int itemsAddedToCart10m;
    public String chat_message_list;

    // A constructor to map from the API response array
    public CSAContext(Object[] row) {
        this.window_start = (String) row[0];
        this.window_end = (String) row[1];
        this.userId = (String) row[2];
        this.page_visited_list = (String) row[3];
        // Note the potential type difference from the API (e.g., Long to int)
        this.distinctPagesVisited10m = Integer.valueOf((String)row[4]);
        this.itemsAddedToCart10m = Integer.valueOf((String)row[5]);
        this.chat_message_list = (String) row[6];
    }
    // Default constructor for Jackson
    public CSAContext() {}

    // Getters and Setters
    public String getWindow_start() { return window_start; }
    public void setWindow_start(String window_start) { this.window_start = window_start; }
    public String getWindow_end() { return window_end; }
    public void setWindow_end(String window_end) { this.window_end = window_end; }
    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }
    public String getPage_visited_list() { return page_visited_list; }
    public void setPage_visited_list(String page_visited_list) { this.page_visited_list = page_visited_list; }
    public int getDistinctPagesVisited10m() { return distinctPagesVisited10m; }
    public void setDistinctPagesVisited10m(int distinctPagesVisited10m) { this.distinctPagesVisited10m = distinctPagesVisited10m; }
    public int getItemsAddedToCart10m() { return itemsAddedToCart10m; }
    public void setItemsAddedToCart10m(int itemsAddedToCart10m) { this.itemsAddedToCart10m = itemsAddedToCart10m; }
    public String getChat_message_list() { return chat_message_list; }
    public void setChat_message_list(String chat_message_list) { this.chat_message_list = chat_message_list; }

}

