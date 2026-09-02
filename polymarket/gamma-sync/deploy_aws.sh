#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ZIP_PATH_DEFAULT="$SCRIPT_DIR/gamma-sync.zip"
PYTHON="${PYTHON:-python3}"

FUNCTION_NAME="${FUNCTION_NAME:-gamma-sync}"
ROLE_NAME="${ROLE_NAME:-gamma-sync-lambda-role}"
RULE_NAME="${RULE_NAME:-gamma-sync-schedule}"
SG_NAME="${SG_NAME:-gamma-sync-lambda-sg}"
POLICY_NAME="${POLICY_NAME:-gamma-sync-inline-policy}"
SECRET_NAME="${SECRET_NAME:-gamma-sync-kafka-secret}"
SSM_CURSOR_KEY="${SSM_CURSOR_KEY:-/gamma/cursor}"
CURSOR_INITIAL_VALUE="${CURSOR_INITIAL_VALUE:-2020-01-01T00:00:00Z}"
RESET_CURSOR="${RESET_CURSOR:-false}"
KAFKA_TOPIC="${KAFKA_TOPIC:-demo_pm_gamma}"
KAFKA_SASL_MECHANISM="${KAFKA_SASL_MECHANISM:-SCRAM-SHA-512}"
# Incremental sync mode. Defaults preserve v1 behavior (updatedAt, both passes).
# For the v2 net-new feed set SYNC_ORDER_FIELD=createdAt and OPEN_ONLY=true.
SYNC_ORDER_FIELD="${SYNC_ORDER_FIELD:-updatedAt}"
SYNC_TIMESTAMP_FIELD="${SYNC_TIMESTAMP_FIELD:-$SYNC_ORDER_FIELD}"
OPEN_ONLY="${OPEN_ONLY:-false}"
# Safety lookback seconds for createdAt/net-new mode (0 preserves v1 behavior).
LOOKBACK_SECONDS="${LOOKBACK_SECONDS:-0}"
# DEDUP mode: fast recent-updates worker skips re-publishing unchanged records
# using an in-memory conditionId->updatedAt cache (default false).
DEDUP="${DEDUP:-false}"
FULL_SWEEP="${FULL_SWEEP:-false}"
# DEDUP_MODE: off | first_seen | content_hash. Legacy DEDUP=true maps to first_seen.
DEDUP_MODE="${DEDUP_MODE:-off}"
# HASH_FIELDS: field set for content_hash mode. "metadata" uses the built-in
# metadata/state preset (excludes all price/volume fields).
HASH_FIELDS="${HASH_FIELDS:-metadata}"
# Cache-bust every Gamma request to avoid the 5-min Cloudflare CDN cache.
CACHE_BUST="${CACHE_BUST:-true}"
# Maximum pages scanned per run (0 = unlimited). Use 10 for the fast path.
MAX_PAGES_PER_RUN="${MAX_PAGES_PER_RUN:-0}"
SCHEDULE_EXPRESSION="${SCHEDULE_EXPRESSION:-rate(1 minute)}"
LAMBDA_TIMEOUT="${LAMBDA_TIMEOUT:-900}"
RESERVED_CONCURRENCY="${RESERVED_CONCURRENCY:-1}"
ZIP_PATH="${ZIP_PATH:-$ZIP_PATH_DEFAULT}"

# Sub-minute (Step Functions) cadence stack. Disabled by default so the
# standard 1-minute EventBridge -> Lambda deployment is unchanged.
SUBMINUTE="${SUBMINUTE:-false}"
ITERATIONS="${ITERATIONS:-6}"
WAIT_SECONDS="${WAIT_SECONDS:-10}"
LOCK_TTL_SECONDS="${LOCK_TTL_SECONDS:-960}"
LOCK_TABLE_NAME="${LOCK_TABLE_NAME:-gamma-sync-lock}"
LOCK_ID="${LOCK_ID:-gamma-sync}"
DISPATCH_FUNCTION_NAME="${DISPATCH_FUNCTION_NAME:-gamma-sync-dispatch}"
DISPATCH_ROLE_NAME="${DISPATCH_ROLE_NAME:-gamma-sync-dispatch-role}"
DISPATCH_POLICY_NAME="${DISPATCH_POLICY_NAME:-gamma-sync-dispatch-policy}"
STATE_MACHINE_NAME="${STATE_MACHINE_NAME:-gamma-sync-subminute}"
SFN_ROLE_NAME="${SFN_ROLE_NAME:-gamma-sync-sfn-role}"
SFN_POLICY_NAME="${SFN_POLICY_NAME:-gamma-sync-sfn-policy}"
EVENTS_ROLE_NAME="${EVENTS_ROLE_NAME:-gamma-sync-events-role}"
EVENTS_POLICY_NAME="${EVENTS_POLICY_NAME:-gamma-sync-events-policy}"
METRIC_NAMESPACE="${METRIC_NAMESPACE:-GammaSync}"
DISPATCH_ZIP="${DISPATCH_ZIP:-$SCRIPT_DIR/gamma-sync-dispatch.zip}"
ASL_TEMPLATE="${ASL_TEMPLATE:-$SCRIPT_DIR/statemachine.asl.json}"

AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
if [[ -z "$AWS_REGION" ]]; then
  AWS_REGION="$(aws configure get region || true)"
fi
if [[ -z "$AWS_REGION" ]]; then
  AWS_REGION="us-east-1"
fi

usage() {
  cat <<'EOF'
Automate Gamma Sync Lambda deployment in AWS.

Required environment variables:
  Either:
    SECRET_ARN              Existing Secrets Manager secret ARN containing
                            bootstrap_servers/username/password
  Or:
    KAFKA_BOOTSTRAP_SERVERS Kafka bootstrap servers string
    KAFKA_USERNAME          Kafka SASL username
    KAFKA_PASSWORD          Kafka SASL password

Optional environment variables:
  AWS_REGION              AWS region (default: us-east-1)
  FUNCTION_NAME           Lambda function name (default: gamma-sync)
  ROLE_NAME               IAM role name (default: gamma-sync-lambda-role)
  RULE_NAME               EventBridge rule name (default: gamma-sync-schedule)
  SG_NAME                 Security group name (default: gamma-sync-lambda-sg)
  SECRET_NAME             Secrets Manager secret name (default: gamma-sync-kafka-secret)
  SECRET_ARN              Existing secret ARN. If set without Kafka env vars,
                          the script reuses the secret as-is.
  POLICY_NAME             IAM inline policy name (default: gamma-sync-inline-policy)
  SSM_CURSOR_KEY          SSM cursor parameter key (default: /gamma/cursor)
  CURSOR_INITIAL_VALUE    Initial cursor value (default: 2020-01-01T00:00:00Z)
  RESET_CURSOR            Overwrite existing cursor when true (default: false)
  KAFKA_TOPIC             Kafka topic env var (default: demo_pm_gamma)
  KAFKA_SASL_MECHANISM    Kafka SASL mechanism (default: SCRAM-SHA-512)
  SCHEDULE_EXPRESSION     EventBridge rate/cron expression (default: rate(1 minute))
  LAMBDA_TIMEOUT          Lambda timeout in seconds (default: 900)
  RESERVED_CONCURRENCY    Lambda reserved concurrency (default: 1)
  ZIP_PATH                Lambda zip path (default: ./gamma-sync.zip)
  VPC_ID                  VPC where Lambda runs (optional)
  SUBNET_IDS              Comma-separated subnet IDs (required if VPC_ID is set)

Sub-minute cadence (Step Functions) options:
  SUBMINUTE               Enable ~10s cadence stack when 'true' (default: false)
  ITERATIONS              Dispatches per minute (default: 6)
  WAIT_SECONDS            Seconds between dispatches (default: 10)
  LOCK_TTL_SECONDS        DynamoDB lock lease seconds (default: 960)
  LOCK_TABLE_NAME         DynamoDB lock table name (default: gamma-sync-lock)
  LOCK_ID                 Lock item id (default: gamma-sync)
  DISPATCH_FUNCTION_NAME  Dispatcher Lambda name (default: gamma-sync-dispatch)
  STATE_MACHINE_NAME      State machine name (default: gamma-sync-subminute)
  METRIC_NAMESPACE        CloudWatch metric namespace (default: GammaSync)

Examples:
  make package
  KAFKA_BOOTSTRAP_SERVERS='broker:9092' KAFKA_USERNAME='user' KAFKA_PASSWORD='pass' \
  ./deploy_aws.sh

  # Optional VPC mode
  VPC_ID=vpc-123 SUBNET_IDS=subnet-a,subnet-b \
  KAFKA_BOOTSTRAP_SERVERS='broker:9092' KAFKA_USERNAME='user' KAFKA_PASSWORD='pass' \
  ./deploy_aws.sh
EOF
}

log() {
  printf '[deploy] %s\n' "$1"
}

retry_create_function() {
  local attempt=1
  local max_attempts=10
  local delay_seconds=6
  local output

  while true; do
    set +e
    output="$($@ 2>&1)"
    local exit_code=$?
    set -e

    if [[ $exit_code -eq 0 ]]; then
      return 0
    fi

    if [[ "$output" == *"The role defined for the function cannot be assumed by Lambda"* && $attempt -lt $max_attempts ]]; then
      log "IAM role propagation delay (attempt $attempt/$max_attempts); retrying in ${delay_seconds}s"
      sleep "$delay_seconds"
      attempt=$((attempt + 1))
      continue
    fi

    echo "$output" >&2
    return $exit_code
  done
}

# Retry an AWS command that can transiently fail while a freshly-created IAM
# role propagates (used for Step Functions state machine and role-dependent
# calls). Retries on common IAM propagation error substrings.
retry_role_dependent() {
  local attempt=1
  local max_attempts=10
  local delay_seconds=6
  local output

  while true; do
    set +e
    output="$("$@" 2>&1)"
    local exit_code=$?
    set -e

    if [[ $exit_code -eq 0 ]]; then
      [[ -n "$output" ]] && echo "$output"
      return 0
    fi

    if [[ ( "$output" == *"cannot be assumed"* \
      || "$output" == *"not authorized to perform: iam:PassRole"* \
      || "$output" == *"AccessDeniedException"* \
      || "$output" == *"is not authorized"* ) && $attempt -lt $max_attempts ]]; then
      log "IAM role propagation delay (attempt $attempt/$max_attempts); retrying in ${delay_seconds}s"
      sleep "$delay_seconds"
      attempt=$((attempt + 1))
      continue
    fi

    echo "$output" >&2
    return $exit_code
  done
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: $name" >&2
    exit 1
  fi
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

require_cmd aws
require_cmd "$PYTHON"

REUSE_EXISTING_SECRET="false"
if [[ -n "${SECRET_ARN:-}" ]]; then
  if [[ -z "${KAFKA_BOOTSTRAP_SERVERS:-}" && -z "${KAFKA_USERNAME:-}" && -z "${KAFKA_PASSWORD:-}" ]]; then
    REUSE_EXISTING_SECRET="true"
  else
    require_env KAFKA_BOOTSTRAP_SERVERS
    require_env KAFKA_USERNAME
    require_env KAFKA_PASSWORD
  fi
else
  require_env KAFKA_BOOTSTRAP_SERVERS
  require_env KAFKA_USERNAME
  require_env KAFKA_PASSWORD
fi

USE_VPC="false"
if [[ -n "${VPC_ID:-}" ]]; then
  USE_VPC="true"
  require_env SUBNET_IDS
fi

if [[ ! -f "$ZIP_PATH" ]]; then
  echo "Lambda zip not found at: $ZIP_PATH" >&2
  echo "Run 'make package' in gamma-sync first, or set ZIP_PATH." >&2
  exit 1
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "$AWS_REGION")"
if [[ -z "$ACCOUNT_ID" || "$ACCOUNT_ID" == "None" ]]; then
  echo "Unable to resolve AWS account ID." >&2
  exit 1
fi

log "Using region=$AWS_REGION account=$ACCOUNT_ID"

if [[ "$REUSE_EXISTING_SECRET" == "true" ]]; then
  log "Reusing existing secret ARN without modification"
  aws secretsmanager describe-secret \
    --region "$AWS_REGION" \
    --secret-id "$SECRET_ARN" >/dev/null
else
  SECRET_PAYLOAD="$($PYTHON -c 'import json, os; print(json.dumps({"bootstrap_servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"], "username": os.environ["KAFKA_USERNAME"], "password": os.environ["KAFKA_PASSWORD"]}))')"

  if [[ -n "${SECRET_ARN:-}" ]]; then
    log "Updating existing secret ARN"
    aws secretsmanager put-secret-value \
      --region "$AWS_REGION" \
      --secret-id "$SECRET_ARN" \
      --secret-string "$SECRET_PAYLOAD" >/dev/null
  else
    EXISTING_SECRET_ARN="$(aws secretsmanager describe-secret \
      --region "$AWS_REGION" \
      --secret-id "$SECRET_NAME" \
      --query ARN --output text 2>/dev/null || true)"

    if [[ -n "$EXISTING_SECRET_ARN" && "$EXISTING_SECRET_ARN" != "None" ]]; then
      log "Updating existing secret name=$SECRET_NAME"
      aws secretsmanager put-secret-value \
        --region "$AWS_REGION" \
        --secret-id "$SECRET_NAME" \
        --secret-string "$SECRET_PAYLOAD" >/dev/null
      SECRET_ARN="$EXISTING_SECRET_ARN"
    else
      log "Creating secret name=$SECRET_NAME"
      SECRET_ARN="$(aws secretsmanager create-secret \
        --region "$AWS_REGION" \
        --name "$SECRET_NAME" \
        --secret-string "$SECRET_PAYLOAD" \
        --query ARN --output text)"
    fi
  fi
fi

log "Secret ARN: $SECRET_ARN"

EXISTING_CURSOR_VALUE="$(aws ssm get-parameter \
  --region "$AWS_REGION" \
  --name "$SSM_CURSOR_KEY" \
  --query 'Parameter.Value' \
  --output text 2>/dev/null || true)"

if [[ "$RESET_CURSOR" == "true" ]]; then
  log "Resetting SSM cursor $SSM_CURSOR_KEY to $CURSOR_INITIAL_VALUE"
  aws ssm put-parameter \
    --region "$AWS_REGION" \
    --name "$SSM_CURSOR_KEY" \
    --type String \
    --value "$CURSOR_INITIAL_VALUE" \
    --overwrite >/dev/null
elif [[ -n "$EXISTING_CURSOR_VALUE" && "$EXISTING_CURSOR_VALUE" != "None" ]]; then
  log "Keeping existing SSM cursor $SSM_CURSOR_KEY at $EXISTING_CURSOR_VALUE"
else
  log "Creating SSM cursor $SSM_CURSOR_KEY at $CURSOR_INITIAL_VALUE"
  aws ssm put-parameter \
    --region "$AWS_REGION" \
    --name "$SSM_CURSOR_KEY" \
    --type String \
    --value "$CURSOR_INITIAL_VALUE" >/dev/null
fi

ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text 2>/dev/null || true)"

if [[ -z "$ROLE_ARN" || "$ROLE_ARN" == "None" ]]; then
  log "Creating IAM role $ROLE_NAME"
  TRUST_DOC_FILE="$(mktemp)"
  cat >"$TRUST_DOC_FILE" <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$TRUST_DOC_FILE" >/dev/null
  rm -f "$TRUST_DOC_FILE"
  ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)"
fi

log "Ensuring managed IAM policies are attached"
aws iam attach-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null

if [[ "$USE_VPC" == "true" ]]; then
  aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole >/dev/null
fi

INLINE_POLICY_FILE="$(mktemp)"
cat >"$INLINE_POLICY_FILE" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SSMCursor",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:PutParameter"
      ],
      "Resource": "arn:aws:ssm:$AWS_REGION:$ACCOUNT_ID:parameter${SSM_CURSOR_KEY}"
    },
    {
      "Sid": "SecretsManagerKafka",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "$SECRET_ARN"
    }
  ]
}
EOF
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "file://$INLINE_POLICY_FILE" >/dev/null
rm -f "$INLINE_POLICY_FILE"

# Worker Lambda environment. LOCK_TABLE is only added in sub-minute mode so the
# worker knows to release the DynamoDB lock the dispatcher acquired for it.
LOCK_TABLE_ARN="arn:aws:dynamodb:$AWS_REGION:$ACCOUNT_ID:table/$LOCK_TABLE_NAME"
ENV_KV="SSM_CURSOR_KEY=$SSM_CURSOR_KEY,KAFKA_SECRET_ARN=$SECRET_ARN,KAFKA_TOPIC=$KAFKA_TOPIC,KAFKA_SASL_MECHANISM=$KAFKA_SASL_MECHANISM,METRIC_NAMESPACE=$METRIC_NAMESPACE,SYNC_ORDER_FIELD=$SYNC_ORDER_FIELD,SYNC_TIMESTAMP_FIELD=$SYNC_TIMESTAMP_FIELD,OPEN_ONLY=$OPEN_ONLY,LOOKBACK_SECONDS=$LOOKBACK_SECONDS,DEDUP=$DEDUP,DEDUP_MODE=$DEDUP_MODE,HASH_FIELDS=$HASH_FIELDS,FULL_SWEEP=$FULL_SWEEP,CACHE_BUST=$CACHE_BUST,MAX_PAGES_PER_RUN=$MAX_PAGES_PER_RUN"

if [[ "$SUBMINUTE" == "true" ]]; then
  ENV_KV="$ENV_KV,LOCK_TABLE=$LOCK_TABLE_NAME"

  log "Ensuring DynamoDB lock table $LOCK_TABLE_NAME"
  if ! aws dynamodb describe-table --region "$AWS_REGION" --table-name "$LOCK_TABLE_NAME" >/dev/null 2>&1; then
    log "Creating DynamoDB table $LOCK_TABLE_NAME"
    aws dynamodb create-table \
      --region "$AWS_REGION" \
      --table-name "$LOCK_TABLE_NAME" \
      --attribute-definitions AttributeName=lock_id,AttributeType=S \
      --key-schema AttributeName=lock_id,KeyType=HASH \
      --billing-mode PAY_PER_REQUEST >/dev/null
    aws dynamodb wait table-exists --region "$AWS_REGION" --table-name "$LOCK_TABLE_NAME"
  fi
  log "Ensuring TTL on $LOCK_TABLE_NAME (expires_at)"
  aws dynamodb update-time-to-live \
    --region "$AWS_REGION" \
    --table-name "$LOCK_TABLE_NAME" \
    --time-to-live-specification "Enabled=true,AttributeName=expires_at" >/dev/null 2>&1 || true

  log "Granting worker role $ROLE_NAME DeleteItem on $LOCK_TABLE_NAME"
  WORKER_DDB_POLICY_FILE="$(mktemp)"
  cat >"$WORKER_DDB_POLICY_FILE" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GammaLockRelease",
      "Effect": "Allow",
      "Action": ["dynamodb:DeleteItem"],
      "Resource": "$LOCK_TABLE_ARN"
    },
    {
      "Sid": "GammaRunMetrics",
      "Effect": "Allow",
      "Action": ["cloudwatch:PutMetricData"],
      "Resource": "*"
    }
  ]
}
EOF
  aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "${POLICY_NAME}-ddb" \
    --policy-document "file://$WORKER_DDB_POLICY_FILE" >/dev/null
  rm -f "$WORKER_DDB_POLICY_FILE"
fi

SG_ID=""
if [[ "$USE_VPC" == "true" ]]; then
  SG_ID="$(aws ec2 describe-security-groups \
    --region "$AWS_REGION" \
    --filters Name=group-name,Values="$SG_NAME" Name=vpc-id,Values="$VPC_ID" \
    --query 'SecurityGroups[0].GroupId' --output text)"

  if [[ -z "$SG_ID" || "$SG_ID" == "None" ]]; then
    log "Creating security group $SG_NAME"
    SG_ID="$(aws ec2 create-security-group \
      --region "$AWS_REGION" \
      --group-name "$SG_NAME" \
      --description "Security group for $FUNCTION_NAME Lambda" \
      --vpc-id "$VPC_ID" \
      --query GroupId --output text)"
  fi

  log "Security group ID: $SG_ID"
else
  log "VPC not set; Lambda will run outside VPC"
fi

FUNCTION_ARN="$(aws lambda get-function \
  --region "$AWS_REGION" \
  --function-name "$FUNCTION_NAME" \
  --query 'Configuration.FunctionArn' \
  --output text 2>/dev/null || true)"

if [[ -z "$FUNCTION_ARN" || "$FUNCTION_ARN" == "None" ]]; then
  log "Creating Lambda function $FUNCTION_NAME"
  if [[ "$USE_VPC" == "true" ]]; then
    retry_create_function aws lambda create-function \
      --region "$AWS_REGION" \
      --function-name "$FUNCTION_NAME" \
      --runtime python3.12 \
      --architectures x86_64 \
      --role "$ROLE_ARN" \
      --handler lambda_function.handler \
      --zip-file "fileb://$ZIP_PATH" \
      --timeout "$LAMBDA_TIMEOUT" \
      --memory-size 256 \
      --vpc-config "SubnetIds=$SUBNET_IDS,SecurityGroupIds=$SG_ID" \
      --environment "Variables={$ENV_KV}" >/dev/null
  else
    retry_create_function aws lambda create-function \
      --region "$AWS_REGION" \
      --function-name "$FUNCTION_NAME" \
      --runtime python3.12 \
      --architectures x86_64 \
      --role "$ROLE_ARN" \
      --handler lambda_function.handler \
      --zip-file "fileb://$ZIP_PATH" \
      --timeout "$LAMBDA_TIMEOUT" \
      --memory-size 256 \
      --environment "Variables={$ENV_KV}" >/dev/null
  fi
else
  log "Updating Lambda code for $FUNCTION_NAME"
  aws lambda update-function-code \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_PATH" >/dev/null

  aws lambda wait function-updated-v2 \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME"

  log "Updating Lambda configuration for $FUNCTION_NAME"
  if [[ "$USE_VPC" == "true" ]]; then
    aws lambda update-function-configuration \
      --region "$AWS_REGION" \
      --function-name "$FUNCTION_NAME" \
      --role "$ROLE_ARN" \
      --timeout "$LAMBDA_TIMEOUT" \
      --memory-size 256 \
      --vpc-config "SubnetIds=$SUBNET_IDS,SecurityGroupIds=$SG_ID" \
      --environment "Variables={$ENV_KV}" >/dev/null
  else
    aws lambda update-function-configuration \
      --region "$AWS_REGION" \
      --function-name "$FUNCTION_NAME" \
      --role "$ROLE_ARN" \
      --timeout "$LAMBDA_TIMEOUT" \
      --memory-size 256 \
      --environment "Variables={$ENV_KV}" >/dev/null

    aws lambda wait function-updated-v2 \
      --region "$AWS_REGION" \
      --function-name "$FUNCTION_NAME"

    # Explicitly remove VPC config when deploying non-VPC mode.
    aws lambda update-function-configuration \
      --region "$AWS_REGION" \
      --function-name "$FUNCTION_NAME" \
      --vpc-config SubnetIds=[],SecurityGroupIds=[] >/dev/null
  fi
fi

aws lambda wait function-active-v2 \
  --region "$AWS_REGION" \
  --function-name "$FUNCTION_NAME"

if [[ -n "$RESERVED_CONCURRENCY" ]]; then
  log "Setting reserved concurrency for $FUNCTION_NAME to $RESERVED_CONCURRENCY"
  aws lambda put-function-concurrency \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" \
    --reserved-concurrent-executions "$RESERVED_CONCURRENCY" >/dev/null
fi

if [[ "$SUBMINUTE" == "true" ]]; then
  # In sub-minute mode we must never build an async backlog on the worker.
  # Drop throttled async events quickly instead of retrying them for hours.
  log "Configuring async invoke policy for $FUNCTION_NAME (max age 60s, no retries)"
  aws lambda put-function-event-invoke-config \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" \
    --maximum-event-age-in-seconds 60 \
    --maximum-retry-attempts 0 >/dev/null
else
  # Restore default async behavior when not using the sub-minute dispatcher.
  aws lambda delete-function-event-invoke-config \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" >/dev/null 2>&1 || true
fi

FUNCTION_ARN="$(aws lambda get-function \
  --region "$AWS_REGION" \
  --function-name "$FUNCTION_NAME" \
  --query 'Configuration.FunctionArn' \
  --output text)"

if [[ -z "$SG_ID" ]]; then
  SG_ID="n/a (Lambda outside VPC)"
fi

STATE_MACHINE_ARN=""

if [[ "$SUBMINUTE" == "true" ]]; then
  log "SUBMINUTE mode: provisioning dispatcher + Step Functions stack"

  # --- Dispatcher IAM role ---
  DISPATCH_ROLE_ARN="$(aws iam get-role --role-name "$DISPATCH_ROLE_NAME" --query 'Role.Arn' --output text 2>/dev/null || true)"
  if [[ -z "$DISPATCH_ROLE_ARN" || "$DISPATCH_ROLE_ARN" == "None" ]]; then
    log "Creating IAM role $DISPATCH_ROLE_NAME"
    DISPATCH_TRUST_FILE="$(mktemp)"
    cat >"$DISPATCH_TRUST_FILE" <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}
  ]
}
EOF
    aws iam create-role \
      --role-name "$DISPATCH_ROLE_NAME" \
      --assume-role-policy-document "file://$DISPATCH_TRUST_FILE" >/dev/null
    rm -f "$DISPATCH_TRUST_FILE"
    DISPATCH_ROLE_ARN="$(aws iam get-role --role-name "$DISPATCH_ROLE_NAME" --query 'Role.Arn' --output text)"
  fi
  aws iam attach-role-policy \
    --role-name "$DISPATCH_ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null

  DISPATCH_POLICY_FILE="$(mktemp)"
  cat >"$DISPATCH_POLICY_FILE" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Lock",
      "Effect": "Allow",
      "Action": ["dynamodb:UpdateItem", "dynamodb:GetItem", "dynamodb:DeleteItem"],
      "Resource": "$LOCK_TABLE_ARN"
    },
    {
      "Sid": "InvokeWorker",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "$FUNCTION_ARN"
    },
    {
      "Sid": "Metrics",
      "Effect": "Allow",
      "Action": "cloudwatch:PutMetricData",
      "Resource": "*"
    }
  ]
}
EOF
  aws iam put-role-policy \
    --role-name "$DISPATCH_ROLE_NAME" \
    --policy-name "$DISPATCH_POLICY_NAME" \
    --policy-document "file://$DISPATCH_POLICY_FILE" >/dev/null
  rm -f "$DISPATCH_POLICY_FILE"

  # --- Dispatcher Lambda (boto3-only; no external deps) ---
  log "Packaging dispatcher $DISPATCH_FUNCTION_NAME"
  rm -f "$DISPATCH_ZIP"
  (cd "$SCRIPT_DIR" && zip -q -j "$DISPATCH_ZIP" dispatch_function.py)

  DISPATCH_ENV="LOCK_TABLE=$LOCK_TABLE_NAME,TARGET_FUNCTION=$FUNCTION_NAME,LOCK_ID=$LOCK_ID,LOCK_TTL_SECONDS=$LOCK_TTL_SECONDS,METRIC_NAMESPACE=$METRIC_NAMESPACE"

  DISPATCH_ARN="$(aws lambda get-function \
    --region "$AWS_REGION" \
    --function-name "$DISPATCH_FUNCTION_NAME" \
    --query 'Configuration.FunctionArn' \
    --output text 2>/dev/null || true)"

  if [[ -z "$DISPATCH_ARN" || "$DISPATCH_ARN" == "None" ]]; then
    log "Creating dispatcher Lambda $DISPATCH_FUNCTION_NAME"
    retry_create_function aws lambda create-function \
      --region "$AWS_REGION" \
      --function-name "$DISPATCH_FUNCTION_NAME" \
      --runtime python3.12 \
      --architectures x86_64 \
      --role "$DISPATCH_ROLE_ARN" \
      --handler dispatch_function.handler \
      --zip-file "fileb://$DISPATCH_ZIP" \
      --timeout 15 \
      --memory-size 128 \
      --environment "Variables={$DISPATCH_ENV}" >/dev/null
  else
    log "Updating dispatcher Lambda $DISPATCH_FUNCTION_NAME"
    aws lambda update-function-code \
      --region "$AWS_REGION" \
      --function-name "$DISPATCH_FUNCTION_NAME" \
      --zip-file "fileb://$DISPATCH_ZIP" >/dev/null
    aws lambda wait function-updated-v2 \
      --region "$AWS_REGION" \
      --function-name "$DISPATCH_FUNCTION_NAME"
    aws lambda update-function-configuration \
      --region "$AWS_REGION" \
      --function-name "$DISPATCH_FUNCTION_NAME" \
      --role "$DISPATCH_ROLE_ARN" \
      --handler dispatch_function.handler \
      --timeout 15 \
      --memory-size 128 \
      --environment "Variables={$DISPATCH_ENV}" >/dev/null
  fi

  aws lambda wait function-active-v2 \
    --region "$AWS_REGION" \
    --function-name "$DISPATCH_FUNCTION_NAME"

  DISPATCH_ARN="$(aws lambda get-function \
    --region "$AWS_REGION" \
    --function-name "$DISPATCH_FUNCTION_NAME" \
    --query 'Configuration.FunctionArn' \
    --output text)"

  # --- Step Functions role ---
  SFN_ROLE_ARN="$(aws iam get-role --role-name "$SFN_ROLE_NAME" --query 'Role.Arn' --output text 2>/dev/null || true)"
  if [[ -z "$SFN_ROLE_ARN" || "$SFN_ROLE_ARN" == "None" ]]; then
    log "Creating IAM role $SFN_ROLE_NAME"
    SFN_TRUST_FILE="$(mktemp)"
    cat >"$SFN_TRUST_FILE" <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Principal": {"Service": "states.amazonaws.com"}, "Action": "sts:AssumeRole"}
  ]
}
EOF
    aws iam create-role \
      --role-name "$SFN_ROLE_NAME" \
      --assume-role-policy-document "file://$SFN_TRUST_FILE" >/dev/null
    rm -f "$SFN_TRUST_FILE"
    SFN_ROLE_ARN="$(aws iam get-role --role-name "$SFN_ROLE_NAME" --query 'Role.Arn' --output text)"
  fi
  SFN_POLICY_FILE="$(mktemp)"
  cat >"$SFN_POLICY_FILE" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeDispatcher",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "$DISPATCH_ARN"
    }
  ]
}
EOF
  aws iam put-role-policy \
    --role-name "$SFN_ROLE_NAME" \
    --policy-name "$SFN_POLICY_NAME" \
    --policy-document "file://$SFN_POLICY_FILE" >/dev/null
  rm -f "$SFN_POLICY_FILE"

  # --- State machine definition ---
  ASL_RENDERED="$(mktemp)"
  sed \
    -e "s|__DISPATCHER_ARN__|$DISPATCH_ARN|g" \
    -e "s|__ITERATIONS__|$ITERATIONS|g" \
    -e "s|__WAIT_SECONDS__|$WAIT_SECONDS|g" \
    "$ASL_TEMPLATE" >"$ASL_RENDERED"

  STATE_MACHINE_ARN="$(aws stepfunctions list-state-machines \
    --region "$AWS_REGION" \
    --query "stateMachines[?name=='$STATE_MACHINE_NAME'].stateMachineArn | [0]" \
    --output text 2>/dev/null || true)"

  if [[ -z "$STATE_MACHINE_ARN" || "$STATE_MACHINE_ARN" == "None" ]]; then
    log "Creating state machine $STATE_MACHINE_NAME"
    STATE_MACHINE_ARN="$(retry_role_dependent aws stepfunctions create-state-machine \
      --region "$AWS_REGION" \
      --name "$STATE_MACHINE_NAME" \
      --type STANDARD \
      --role-arn "$SFN_ROLE_ARN" \
      --definition "file://$ASL_RENDERED" \
      --query 'stateMachineArn' \
      --output text)"
  else
    log "Updating state machine $STATE_MACHINE_NAME"
    retry_role_dependent aws stepfunctions update-state-machine \
      --region "$AWS_REGION" \
      --state-machine-arn "$STATE_MACHINE_ARN" \
      --role-arn "$SFN_ROLE_ARN" \
      --definition "file://$ASL_RENDERED" >/dev/null
  fi
  rm -f "$ASL_RENDERED"

  # --- EventBridge role to start the state machine ---
  EVENTS_ROLE_ARN="$(aws iam get-role --role-name "$EVENTS_ROLE_NAME" --query 'Role.Arn' --output text 2>/dev/null || true)"
  if [[ -z "$EVENTS_ROLE_ARN" || "$EVENTS_ROLE_ARN" == "None" ]]; then
    log "Creating IAM role $EVENTS_ROLE_NAME"
    EVENTS_TRUST_FILE="$(mktemp)"
    cat >"$EVENTS_TRUST_FILE" <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Principal": {"Service": "events.amazonaws.com"}, "Action": "sts:AssumeRole"}
  ]
}
EOF
    aws iam create-role \
      --role-name "$EVENTS_ROLE_NAME" \
      --assume-role-policy-document "file://$EVENTS_TRUST_FILE" >/dev/null
    rm -f "$EVENTS_TRUST_FILE"
    EVENTS_ROLE_ARN="$(aws iam get-role --role-name "$EVENTS_ROLE_NAME" --query 'Role.Arn' --output text)"
  fi
  EVENTS_POLICY_FILE="$(mktemp)"
  cat >"$EVENTS_POLICY_FILE" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "StartStateMachine",
      "Effect": "Allow",
      "Action": "states:StartExecution",
      "Resource": "$STATE_MACHINE_ARN"
    }
  ]
}
EOF
  aws iam put-role-policy \
    --role-name "$EVENTS_ROLE_NAME" \
    --policy-name "$EVENTS_POLICY_NAME" \
    --policy-document "file://$EVENTS_POLICY_FILE" >/dev/null
  rm -f "$EVENTS_POLICY_FILE"

  log "Creating/updating EventBridge rule $RULE_NAME -> state machine"
  RULE_ARN="$(aws events put-rule \
    --region "$AWS_REGION" \
    --name "$RULE_NAME" \
    --schedule-expression "$SCHEDULE_EXPRESSION" \
    --state ENABLED \
    --query 'RuleArn' \
    --output text)"

  retry_role_dependent aws events put-targets \
    --region "$AWS_REGION" \
    --rule "$RULE_NAME" \
    --targets "Id=1,Arn=$STATE_MACHINE_ARN,RoleArn=$EVENTS_ROLE_ARN" >/dev/null
else
  log "Creating/updating EventBridge rule $RULE_NAME -> Lambda"
  RULE_ARN="$(aws events put-rule \
    --region "$AWS_REGION" \
    --name "$RULE_NAME" \
    --schedule-expression "$SCHEDULE_EXPRESSION" \
    --state ENABLED \
    --query 'RuleArn' \
    --output text)"

  aws events put-targets \
    --region "$AWS_REGION" \
    --rule "$RULE_NAME" \
    --targets "Id"="1","Arn"="$FUNCTION_ARN" >/dev/null

  STATEMENT_ID="${RULE_NAME}-invoke"
  set +e
  aws lambda add-permission \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" \
    --statement-id "$STATEMENT_ID" \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn "$RULE_ARN" >/dev/null 2>&1
  ADD_PERMISSION_EXIT=$?
  set -e
  if [[ $ADD_PERMISSION_EXIT -ne 0 ]]; then
    log "Lambda invoke permission already exists or could not be added automatically"
  fi
fi

if [[ "$SUBMINUTE" == "true" ]]; then
  cat <<EOF

Deployment complete (SUBMINUTE mode).

Function:        $FUNCTION_NAME
Function ARN:    $FUNCTION_ARN
Dispatcher:      $DISPATCH_FUNCTION_NAME
State machine:   $STATE_MACHINE_ARN
Lock table:      $LOCK_TABLE_NAME (TTL: expires_at, lease ${LOCK_TTL_SECONDS}s)
Cadence:         $ITERATIONS dispatches/min, ${WAIT_SECONDS}s apart
Region:          $AWS_REGION
Role:            $ROLE_NAME
Security Group:  $SG_ID
Timeout:         $LAMBDA_TIMEOUT
Concurrency:     $RESERVED_CONCURRENCY
Rule:            $RULE_NAME -> state machine
Schedule:        $SCHEDULE_EXPRESSION
Secret ARN:      $SECRET_ARN
SSM Cursor Key:  $SSM_CURSOR_KEY
Kafka Topic:     $KAFKA_TOPIC
SASL Mechanism:  $KAFKA_SASL_MECHANISM

Observe cadence:
  aws cloudwatch get-metric-statistics --namespace $METRIC_NAMESPACE \\
    --metric-name invoked --start-time "\$(date -u -v-15M +%Y-%m-%dT%H:%M:%SZ)" \\
    --end-time "\$(date -u +%Y-%m-%dT%H:%M:%SZ)" --period 60 --statistics Sum \\
    --dimensions Name=LockId,Value=$LOCK_ID --region $AWS_REGION

EOF
else
  cat <<EOF

Deployment complete.

Function:        $FUNCTION_NAME
Function ARN:    $FUNCTION_ARN
Region:          $AWS_REGION
Role:            $ROLE_NAME
Security Group:  $SG_ID
Timeout:         $LAMBDA_TIMEOUT
Concurrency:     $RESERVED_CONCURRENCY
Rule:            $RULE_NAME
Schedule:        $SCHEDULE_EXPRESSION
Secret ARN:      $SECRET_ARN
SSM Cursor Key:  $SSM_CURSOR_KEY
Kafka Topic:     $KAFKA_TOPIC
SASL Mechanism:  $KAFKA_SASL_MECHANISM

Next check:
  aws lambda invoke --region "$AWS_REGION" --function-name "$FUNCTION_NAME" --payload '{}' /tmp/gamma-sync-test.json

EOF
fi
