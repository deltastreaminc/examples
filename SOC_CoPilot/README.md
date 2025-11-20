This example is an end to end simplified SOC Copilot agent with Real-Time context provided by DeltaStream. Follow these steps to build and run the agent:

1. Start the sampe data generator: Update CyberSecurityEventGenerator.java with your Kafka URL and key/secret and run it. This will generate events into Kafla topics that will be consumed by DeltaStream to build the real-time context for the agant.

2. Assuming you have added your Kafka cluster as a store in DeltaStream, run the SQL statements in SOC_CoPilot.sql file to build the real-time context for the agent.

3. Follow the instructions here to create API token for your real-time context: https://docs.deltastream.io/how-do-i.../expose-a-materialized-view-over-mcp

4. Go to OpenAI Agent Builder environment and start a new project. Give a name to your agent, here we used `CyberSecurityAgent1`. Then add the real-time context as an MCP Server Tool to your agent. Pres `+` button next to Tools and then pres `+ Server` button on the dialog to configure DeltaStream's Real-Time Context MCP server. Use the URL and API Token from step 3.

5. Write the instructions for the agent. Here is an example:

You are a senior Security Operations Center (SOC) analyst.
You have access to a real-time security context materialized view
named security_risk_context_mv provided by DeltaStream.

The view contains:
- window_start, window_end
- user_id, src_ip
- failed_logins_5m
- total_auth_events_5m
- mfa_success_count_5m
- total_bytes_sent_5m
- high_critical_alerts_5m
- total_ids_alerts_5m
- risk_score_5m

Always:
- Use the MCP tool "query_security_risk_context" to fetch the latest context
  for any user_id or src_ip the user mentions.
- Explain your reasoning in clear analyst-style language.
- When risk_score_5m is high (> 30), provide specific, actionable recommendations
  (e.g., block IP, reset credentials, require step-up auth, open an incident).
- If the user asks for a summary (e.g., "what is notable in the last 10 minutes?"),
  query the view without filters and sort by highest risk_score_5m, then summarize the top 5 entities.


Once you set up your agent, run it. Try the following example questions to test your SOC CoPilot agent:

- “Explain the current risk for alice.”
- “List top 5 highest-risk IPs right now.”
- “Why did risk spike for 10.0.0.25 in the last few minutes?”
