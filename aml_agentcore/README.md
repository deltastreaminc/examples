# AWS Bedrock AgentCore with DeltaStream MCP Integration - AML Use Case

This guide walks through setting up an AWS Bedrock AgentCore agent integrated with DeltaStream via the Model Context Protocol (MCP) for Anti-Money Laundering (AML) transaction monitoring.

## Overview

This integration demonstrates how to build a proactive GenAI agent that monitors financial transactions in real-time for AML compliance using streaming data. The agent leverages DeltaStream's real-time data processing to access fresh, actionable context through MCP, enabling it to detect suspicious patterns and high-risk transactions as they occur.

**Key Components:**
- **Data Generator**: Simulates real-time financial transactions, customer profiles, KYC results, and sanctions matches
- **Apache Kafka**: Message bus for live event streams
- **DeltaStream**: Real-time context engine processing and materializing streaming data
- **MCP Server**: Bridge exposing DeltaStream's materialized views to the agent
- **Bedrock AgentCore**: Scalable agent deployment and management platform
- **Go HTTP Server**: Sample web application to interact with the deployed agent

## Prerequisites

- AWS Account with Bedrock AgentCore access
- DeltaStream account and organization
- Python 3.x and `uv` package manager
- Go 1.x (for the sample HTTP application)
- AWS credentials configured (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
- Java (JDK 17 or later) for running the data generator
- Access to an Apache Kafka cluster (e.g., Confluent Cloud, AWS MSK)

## Setup Steps

### 0. Set Up Data Generator and DeltaStream Relations

Before creating the agent, set up the real-time data pipeline and DeltaStream relations.

#### Create Kafka Topics

Create the following topics in your Kafka cluster:
- `transactions`
- `customers`
- `kyc_results`
- `sanctions_matches`

#### Launch Data Generator

The data generator simulates real-time financial transactions and related customer data for AML monitoring.

1. Navigate to the data generator directory:

```bash
cd aml_agentcore/datagen
```

2. Configure your Kafka connection details in [AmlDataGenerator.java](datagen/AmlDataGenerator.java):
   - Update `KAFKA_BOOTSTRAP_SERVERS` with your Kafka broker URL
   - Update `KAFKA_API_KEY` and `KAFKA_API_SECRET` with your credentials

3. Compile and run:

```bash
# Compile
javac -cp ".:*" AmlDataGenerator.java

# Run
java -cp ".:*" AmlDataGenerator
```

The generator will simulate:
- Financial transactions (transfers, purchases, ATM withdrawals)
- Customer profile updates
- KYC verification results
- Sanctions screening matches

#### Create DeltaStream Relations

The complete SQL pipeline is available in [aml_deltastream_context.sql](aml_deltastream_context.sql). Execute these statements in your DeltaStream environment to create the AML data pipeline.

**Key components of the pipeline:**

1. **Base Streams and Changelogs**:
   - `transactions_stream` - Real-time transaction events
   - `customers_cl` - Customer profile changelog
   - `kyc_results_cl` - KYC verification results changelog
   - `sanctions_matches_cl` - Sanctions screening results changelog

2. **Enrichment Pipeline**:
   - Join transactions with customer data
   - Add recent transaction statistics (1-hour window)
   - Enrich with KYC results
   - Add sanctions screening information

3. **Materialized View**:
   - `aml_alerts_mv` - Real-time AML alerts for high-risk transactions

The materialized view `aml_alerts_mv` identifies suspicious transactions based on:
- High transaction amounts (>$10,000)
- Politically Exposed Persons (PEP) flag
- High KYC risk levels
- Potential or confirmed sanctions matches
- Elevated transaction frequency

Execute the SQL file:

```bash
# In your DeltaStream SQL editor or CLI
source aml_deltastream_context.sql
```

### 1. Create the Agent

Follow the AWS Bedrock AgentCore starter guide: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-get-started-toolkit.html

```bash
# Create and activate virtual environment
uv venv
source .venv/bin/activate

# Install the starter toolkit
uv pip install bedrock-agentcore-starter-toolkit

# Create a new agent
agentcore create
# Follow prompts: set [agentname] and accept defaults

# Navigate to agent directory
cd [agentname]

# Launch agent locally for testing
agentcore dev

# Test the agent
agentcore invoke --dev '{"prompt": "tell me a joke"}'
```

### 2. Configure DeltaStream

#### Verify Materialized Views

Ensure the materialized views created in Step 0 are active and processing data:
- `aml_alerts_mv` - Contains real-time AML alerts for high-risk transactions
- Any additional materialized views you want to expose via MCP

#### Generate API Token

Create an API token with read permissions on the materialized views you want to expose:

- Follow the [DeltaStream API Token documentation](https://docs.deltastream.io/reference/sql-syntax/ddl/create-api_token)
- Save the following for the next step:
  - `organization_id`
  - `api_token`

### 3. Create OAuth Client in AWS

Configure an OAuth client in Amazon Bedrock AgentCore:

1. Navigate to **Amazon Bedrock AgentCore > Identity > Add OAuth client / API Key**
2. See the [AWS OAuth client documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-add-oauth-client-custom.html)
3. Select **Create custom provider**
4. Choose **Manual configuration**
5. Configure with the following values:
   - **Client ID**: Your DeltaStream `organization_id`
   - **Client Secret**: Your DeltaStream `api_token`
     - ⚠️ **Important**: Watch for leading/trailing spaces when copying the token
   - **Issuer**: `https://deltastream.io`
   - **Authorization endpoint**: Your DeltaStream API OAuth identity endpoint
   - **Token endpoint**: Your DeltaStream API OAuth token endpoint

### 4. Create Gateway

Set up a gateway that references the OAuth client:

1. Navigate to **Amazon Bedrock AgentCore > Gateways > Create gateway**
2. Leave defaults as-is
3. Configure the **Target**:
   - **MCP endpoint**: `https://[your-deltastream-api-host]/mcp/v1`
   - **OAuth client**: Select the client created in step 3
4. **Save** and note the **Gateway resource URL**
5. Click **View invocation code** and save the **Token URL** (e.g., `https://********.auth.us-east-2.amazoncognito.com/oauth2/token`)

### 5. Get Cognito Client Credentials

Retrieve the client ID and secret for agent-to-gateway communication:

1. Navigate to **AWS Cognito > my-user-pool-***
2. Go to **App clients > my-client-***
3. Copy the **client-id** and **client-secret**

### 6. Update Agent Configuration

Update the agent configuration in [agent/src/main.py](agent/src/main.py) with the values collected from previous steps:

```python
CLIENT_ID = "your-cognito-client-id"
CLIENT_SECRET = "your-cognito-client-secret"
TOKEN_URL = "your-cognito-token-url"
gatewayUrl = "your-gateway-resource-url"
```

The agent is configured to:
- Connect to DeltaStream via MCP gateway
- Use OAuth2 client credentials flow for authentication
- Access materialized views (including `aml_alerts_mv`)
- Execute code via Bedrock AgentCore Code Interpreter

### 7. Deploy the Agent

```bash
agentcore deploy
```

Save the **agent ARN** returned after deployment.

## Running the Go HTTP Sample Application

A sample Go HTTP application is provided in [gohttp/](gohttp/) to interact with the deployed agent via a web interface.

### Prerequisites

- AWS environment variables set:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
- Go modules initialized

### Steps

1. Navigate to the Go application directory:

```bash
cd aml_agentcore/gohttp
```

2. Update [main.go](gohttp/main.go) with your agent ARN:

```go
const agentArn = "your-agent-arn-here"
```

3. Install dependencies and run:

```bash
go mod download
go run main.go
```

4. Open your browser to [http://localhost:8081/](http://localhost:8081/)

The application provides a web interface to:
- Submit prompts to the agent
- View streaming responses
- Interact with AML alerts and transaction data through the agent

## Project Structure

```
aml_agentcore/
├── README.md                          # This file
├── aml_deltastream_context.sql        # DeltaStream SQL pipeline definition
├── datagen/
│   └── AmlDataGenerator.java          # Java data generator for Kafka
├── agent/
│   └── src/
│       └── main.py                    # Bedrock AgentCore agent implementation
└── gohttp/
    ├── main.go                        # Go HTTP server for web interface
    ├── go.mod                         # Go module definition
    └── go.sum                         # Go dependencies
```

## Use Case: Real-Time AML Monitoring

This example demonstrates how to build an AI agent that can:

1. **Monitor transactions in real-time** as they flow through Kafka
2. **Access enriched context** from DeltaStream materialized views including:
   - Customer risk profiles
   - KYC verification status
   - Sanctions screening results
   - Recent transaction patterns and statistics
3. **Query AML alerts** for high-risk transactions based on multiple factors
4. **Provide intelligent responses** about transaction risk and compliance

Example agent queries:
- "Show me the latest high-risk transactions"
- "What AML alerts have been triggered in the last hour?"
- "Analyze transactions from high-risk countries"
- "Which customers have potential sanctions matches?"

## Troubleshooting

- **OAuth Client Issues**: Double-check for leading/trailing spaces in the client secret when copying from DeltaStream
- **Gateway Connection**: Verify the MCP endpoint URL matches your DeltaStream API host
- **AWS Credentials**: Ensure your AWS credentials have appropriate permissions for Bedrock AgentCore
- **Data Generator**: Verify Kafka connectivity and topic creation before running the generator
- **Materialized Views**: Check that views are actively processing data in DeltaStream console

## Resources

- [AWS Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/)
- [DeltaStream API Token Documentation](https://docs.deltastream.io/reference/sql-syntax/ddl/create-api_token)
- [OAuth Client Setup Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-add-oauth-client-custom.html)
- [DeltaStream Examples Repository](https://github.com/deltastreaminc/examples)
- [Model Context Protocol (MCP) Documentation](https://modelcontextprotocol.io/)
