# Connector Hub Setup Guide

This guide walks through configuring OCI Service Connector Hub to route OCI Logging events into OCI Streaming topics. You will create two service connectors — one for audit logs, one for function/service logs.

No code required. This is all OCI Console configuration.

**Time to complete:** ~15 minutes

---

## Before you start

You need:
- An OCI Streaming stream pool already created (the bootstrap server and pool OCID should be in your `.env`)
- Two empty topics created in your stream pool:
  - One for audit events (e.g. `oci-audit-raw`)
  - One for function/service logs (e.g. `oci-logging-raw`)
- OCI Logging enabled with at least one log group containing audit logs

---

## Connector 1: Audit Logs → OCI Streaming

### Navigate to Connector Hub
1. Open the OCI Console
2. In the top-left hamburger menu, go to **Observability & Management → Service Connectors**
3. Click **Create Service Connector**

### Configure the source
4. **Connector name:** `oci-audit-to-streaming` (or your preference)
5. **Description:** Routes OCI audit logs to Kafka topic for real-time processing
6. **Source:** Select **Logging**
7. Under **Configure source**, click **Add log**
8. Select your **Compartment**
9. **Log group:** Select `_Audit` (the built-in audit log group) or your custom audit log group
10. **Log:** Leave blank to capture all logs in the group, or select a specific log
11. Repeat **Add log** for any additional compartments you want to include

> **Tip:** To capture audit events across your entire tenancy, add the `_Audit` log group from each compartment you want to monitor. You can add multiple log sources to a single connector.

### Configure the target
12. **Target:** Select **Streaming**
13. **Stream:** Select your stream pool
14. **Topic name:** Enter the audit topic name from your `.env` (e.g. `oci-audit-raw`)
15. Leave **Batch size** and **Batch time** at defaults

### Review and create
16. Click **Create**
17. The connector will move to **Active** status within a minute or two
18. Verify by checking the **Metrics** tab — you should see events flowing once there is audit activity in the tenancy

---

## Connector 2: Function Logs → OCI Streaming

### Create a second connector
1. Return to **Service Connectors** and click **Create Service Connector**

### Configure the source
2. **Connector name:** `oci-functions-to-streaming`
3. **Description:** Routes OCI Functions invocation logs to Kafka topic for real-time processing
4. **Source:** Select **Logging**
5. Under **Configure source**, click **Add log**
6. Select your **Compartment**
7. **Log group:** Select the log group associated with your Functions application
8. **Log:** Select the specific function application log, or leave blank for all logs in the group

> **Note:** OCI Functions logs are found under the log group you enabled when creating your Functions application. If you haven't enabled logging on your application, go to **Functions → Applications → your application → Logs** and enable it first.

### Configure the target
9. **Target:** Select **Streaming**
10. **Stream:** Select the same stream pool
11. **Topic name:** Enter the logging topic name from your `.env` (e.g. `oci-logging-raw`)

### Review and create
12. Click **Create** and wait for **Active** status

---

## Verifying events are flowing

Once both connectors are active, you can verify events are arriving in your topics using the OCI Streaming console:

1. Go to **Streaming → Stream Pools → your pool → Streams**
2. Click on your audit topic
3. Click **Load Messages**
4. You should see JSON CloudEvent objects with `type` values like `com.oraclecloud.audit.*`

If you don't see messages, generate some activity (e.g. navigate around the OCI Console — each page load often generates audit events) and check again after 30–60 seconds.

---

## Connector Hub event format

OCI Connector Hub delivers events as JSON CloudEvents. Here is an example audit event to help you understand the structure:

```json
{
  "specversion": "1.0",
  "id": "abc123",
  "time": "2025-01-15T14:07:32.000Z",
  "type": "com.oraclecloud.identitycontrolplane.updatepolicy",
  "source": "identity",
  "oracle": {
    "tenantid": "ocid1.tenancy.oc1...",
    "compartmentid": "ocid1.compartment.oc1...",
    "loggroupid": "ocid1.loggroup.oc1...",
    "ingestedtime": "2025-01-15T14:07:33.000Z"
  },
  "data": {
    "eventName": "UpdatePolicy",
    "identity": {
      "principalName": "svc-deploy@example.com",
      "principalId": "ocid1.user.oc1...",
      "ipAddress": "10.0.0.1"
    },
    "request": {
      "action": "PUT",
      "path": "/20160918/policies/ocid1.policy.oc1...",
      "id": "trace123/span456"
    },
    "response": {
      "status": "200"
    },
    "resourceId": "ocid1.policy.oc1..."
  }
}
```

This structure is what `02_raw_streams.sql` is designed to parse. The DeltaStream schema maps directly to this CloudEvent envelope.

---

## Troubleshooting

**Connector stuck in "Creating" state**
- Check that your target topic exists in the stream pool before creating the connector
- Verify the topic name matches exactly (case-sensitive)

**Connector active but no messages arriving**
- Generate some OCI activity to trigger audit events
- For function logs, invoke a function to generate invocation events
- Check the connector Metrics tab for any error counts

**Messages arriving but wrong format**
- Verify you selected "Logging" as the source, not "Audit" directly
- The DeltaStream raw stream schemas expect the full CloudEvent envelope
