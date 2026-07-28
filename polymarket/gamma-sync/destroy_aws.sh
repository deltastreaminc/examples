#!/usr/bin/env bash
set -euo pipefail

FUNCTION_NAME="${FUNCTION_NAME:-gamma-sync}"
ROLE_NAME="${ROLE_NAME:-gamma-sync-lambda-role}"
RULE_NAME="${RULE_NAME:-gamma-sync-schedule}"
SG_NAME="${SG_NAME:-gamma-sync-lambda-sg}"
POLICY_NAME="${POLICY_NAME:-gamma-sync-inline-policy}"
SECRET_NAME="${SECRET_NAME:-gamma-sync-kafka-secret}"
SSM_CURSOR_KEY="${SSM_CURSOR_KEY:-/gamma/cursor}"

# Sub-minute stack (only removed when SUBMINUTE=true)
SUBMINUTE="${SUBMINUTE:-false}"
LOCK_TABLE_NAME="${LOCK_TABLE_NAME:-gamma-sync-lock}"
DISPATCH_FUNCTION_NAME="${DISPATCH_FUNCTION_NAME:-gamma-sync-dispatch}"
DISPATCH_ROLE_NAME="${DISPATCH_ROLE_NAME:-gamma-sync-dispatch-role}"
DISPATCH_POLICY_NAME="${DISPATCH_POLICY_NAME:-gamma-sync-dispatch-policy}"
STATE_MACHINE_NAME="${STATE_MACHINE_NAME:-gamma-sync-subminute}"
SFN_ROLE_NAME="${SFN_ROLE_NAME:-gamma-sync-sfn-role}"
SFN_POLICY_NAME="${SFN_POLICY_NAME:-gamma-sync-sfn-policy}"
EVENTS_ROLE_NAME="${EVENTS_ROLE_NAME:-gamma-sync-events-role}"
EVENTS_POLICY_NAME="${EVENTS_POLICY_NAME:-gamma-sync-events-policy}"

AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
if [[ -z "$AWS_REGION" ]]; then
  AWS_REGION="$(aws configure get region || true)"
fi
if [[ -z "$AWS_REGION" ]]; then
  AWS_REGION="us-east-1"
fi

usage() {
  cat <<'EOF'
Destroy Gamma Sync AWS resources created by deploy_aws.sh.

Optional environment variables:
  AWS_REGION   AWS region (default: us-east-1)
  FUNCTION_NAME
  ROLE_NAME
  RULE_NAME
  SG_NAME
  POLICY_NAME
  SECRET_NAME
  SECRET_ARN   Existing secret ARN (preferred over SECRET_NAME if set)
  SSM_CURSOR_KEY
  VPC_ID       Required to delete security group by name

Examples:
  make destroy

  AWS_REGION=us-east-1 FUNCTION_NAME=gamma-sync bash destroy_aws.sh
EOF
}

log() {
  printf '[destroy] %s\n' "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

require_cmd aws

SECRET_ID=""

log "Using region=$AWS_REGION"

FUNCTION_ARN="$(aws lambda get-function \
  --region "$AWS_REGION" \
  --function-name "$FUNCTION_NAME" \
  --query 'Configuration.FunctionArn' \
  --output text 2>/dev/null || true)"

RULE_ARN="$(aws events describe-rule \
  --region "$AWS_REGION" \
  --name "$RULE_NAME" \
  --query 'Arn' \
  --output text 2>/dev/null || true)"

if [[ -n "$RULE_ARN" && "$RULE_ARN" != "None" && -n "$FUNCTION_ARN" && "$FUNCTION_ARN" != "None" ]]; then
  log "Removing EventBridge target from rule $RULE_NAME"
  aws events remove-targets \
    --region "$AWS_REGION" \
    --rule "$RULE_NAME" \
    --ids "1" >/dev/null || true
fi

if [[ -n "$FUNCTION_ARN" && "$FUNCTION_ARN" != "None" ]]; then
  STATEMENT_ID="${RULE_NAME}-invoke"
  log "Removing Lambda invoke permission statement $STATEMENT_ID"
  aws lambda remove-permission \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" \
    --statement-id "$STATEMENT_ID" >/dev/null || true
fi

if [[ -n "$RULE_ARN" && "$RULE_ARN" != "None" ]]; then
  log "Deleting EventBridge rule $RULE_NAME"
  aws events delete-rule \
    --region "$AWS_REGION" \
    --name "$RULE_NAME" >/dev/null || true
fi

if [[ -n "$FUNCTION_ARN" && "$FUNCTION_ARN" != "None" ]]; then
  log "Deleting Lambda function $FUNCTION_NAME"
  aws lambda delete-function \
    --region "$AWS_REGION" \
    --function-name "$FUNCTION_NAME" >/dev/null || true
fi

log "Deleting SSM parameter $SSM_CURSOR_KEY"
aws ssm delete-parameter \
  --region "$AWS_REGION" \
  --name "$SSM_CURSOR_KEY" >/dev/null || true

# Only delete the secret if both SECRET_ARN and SECRET_NAME were explicitly
# provided (non-empty). When SECRET_ARN='' and SECRET_NAME='' are passed (as
# the v2 destroy targets do to protect the shared secret), skip deletion entirely.
if [[ -n "${SECRET_ARN:-}" || ( -n "${SECRET_NAME:-}" && "${SECRET_NAME:-}" != "gamma-sync-kafka-secret" ) ]]; then
  SECRET_ID="${SECRET_ARN:-$SECRET_NAME}"
  if [[ -n "$SECRET_ID" ]]; then
    log "Deleting secret $SECRET_ID"
    aws secretsmanager delete-secret \
      --region "$AWS_REGION" \
      --secret-id "$SECRET_ID" \
      --force-delete-without-recovery >/dev/null || true
  fi
else
  log "Skipping secret deletion (SECRET_ARN and SECRET_NAME are empty or default — shared secret preserved)"
fi

ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text 2>/dev/null || true)"
if [[ -n "$ROLE_ARN" && "$ROLE_ARN" != "None" ]]; then
  log "Deleting IAM inline policy $POLICY_NAME from role $ROLE_NAME"
  aws iam delete-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$POLICY_NAME" >/dev/null || true

  log "Deleting IAM inline policy ${POLICY_NAME}-ddb from role $ROLE_NAME (if present)"
  aws iam delete-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "${POLICY_NAME}-ddb" >/dev/null 2>&1 || true

  log "Detaching managed IAM policies from role $ROLE_NAME"
  aws iam detach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null || true
  aws iam detach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole >/dev/null || true

  log "Deleting IAM role $ROLE_NAME"
  aws iam delete-role --role-name "$ROLE_NAME" >/dev/null || true
fi

if [[ -n "${VPC_ID:-}" ]]; then
  SG_ID="$(aws ec2 describe-security-groups \
    --region "$AWS_REGION" \
    --filters Name=group-name,Values="$SG_NAME" Name=vpc-id,Values="$VPC_ID" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"

  if [[ -n "$SG_ID" && "$SG_ID" != "None" ]]; then
    log "Deleting security group $SG_NAME ($SG_ID)"
    aws ec2 delete-security-group \
      --region "$AWS_REGION" \
      --group-id "$SG_ID" >/dev/null || true
  fi
else
  log "VPC_ID not set; skipping security group deletion"
fi

if [[ "$SUBMINUTE" == "true" ]]; then
  log "SUBMINUTE mode: tearing down dispatcher + Step Functions stack"

  STATE_MACHINE_ARN="$(aws stepfunctions list-state-machines \
    --region "$AWS_REGION" \
    --query "stateMachines[?name=='$STATE_MACHINE_NAME'].stateMachineArn | [0]" \
    --output text 2>/dev/null || true)"
  if [[ -n "$STATE_MACHINE_ARN" && "$STATE_MACHINE_ARN" != "None" ]]; then
    log "Deleting state machine $STATE_MACHINE_NAME"
    aws stepfunctions delete-state-machine \
      --region "$AWS_REGION" \
      --state-machine-arn "$STATE_MACHINE_ARN" >/dev/null || true
  fi

  log "Deleting dispatcher Lambda $DISPATCH_FUNCTION_NAME"
  aws lambda delete-function \
    --region "$AWS_REGION" \
    --function-name "$DISPATCH_FUNCTION_NAME" >/dev/null 2>&1 || true

  for r in "$DISPATCH_ROLE_NAME:$DISPATCH_POLICY_NAME" "$SFN_ROLE_NAME:$SFN_POLICY_NAME" "$EVENTS_ROLE_NAME:$EVENTS_POLICY_NAME"; do
    rn="${r%%:*}"
    pn="${r##*:}"
    if aws iam get-role --role-name "$rn" >/dev/null 2>&1; then
      log "Deleting inline policy $pn from role $rn"
      aws iam delete-role-policy --role-name "$rn" --policy-name "$pn" >/dev/null 2>&1 || true
      log "Detaching managed policies from role $rn"
      aws iam detach-role-policy --role-name "$rn" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null 2>&1 || true
      log "Deleting role $rn"
      aws iam delete-role --role-name "$rn" >/dev/null 2>&1 || true
    fi
  done

  log "Deleting DynamoDB lock table $LOCK_TABLE_NAME"
  aws dynamodb delete-table \
    --region "$AWS_REGION" \
    --table-name "$LOCK_TABLE_NAME" >/dev/null 2>&1 || true
fi

cat <<EOF

Destroy complete.

Region:          $AWS_REGION
Function:        $FUNCTION_NAME
Rule:            $RULE_NAME
Role:            $ROLE_NAME
Secret:          $SECRET_ID
SSM Cursor Key:  $SSM_CURSOR_KEY

EOF
