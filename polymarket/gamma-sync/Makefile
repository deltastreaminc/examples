PYTHON ?= python3
PACKAGE_DIR := package
ZIP_FILE := gamma-sync.zip

# Shared Kafka secret ARN used by both stacks. Set this in the environment.
SECRET_ARN ?=
AWS_REGION ?= us-east-1

.PHONY: package repackage clean rebuild \
        deploy deploy-full deploy-recent \
        deploy-v2-full deploy-v2-recent \
        destroy destroy-full destroy-recent \
        destroy-v2-full destroy-v2-recent \
        smoke-kafka

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

# Full build: reinstall deps + copy handler + zip.
package:
	rm -rf $(PACKAGE_DIR)
	mkdir -p $(PACKAGE_DIR)
	$(PYTHON) -m pip install -r requirements.txt -t $(PACKAGE_DIR)
	cp lambda_function.py $(PACKAGE_DIR)/
	cd $(PACKAGE_DIR) && zip -r ../$(ZIP_FILE) .

# Fast repackage: only refreshes lambda_function.py in an existing package/.
# Use this after code-only changes to avoid reinstalling deps (much faster).
repackage:
	cp lambda_function.py $(PACKAGE_DIR)/
	rm -f $(ZIP_FILE)
	cd $(PACKAGE_DIR) && zip -qr ../$(ZIP_FILE) .

clean:
	rm -rf $(PACKAGE_DIR) $(ZIP_FILE)

rebuild: clean package

# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------

# Generic single-stack deploy (original behaviour, passes through env vars).
deploy: package
	chmod +x deploy_aws.sh
	./deploy_aws.sh

# Full-view stack: gamma-sync -> demo_pm_gamma
# createdAt full sweep + content_hash dedup. Continuous sub-minute cadence.
# Guarantees complete coverage of all ~49K open markets on every cycle.
deploy-full: package
	chmod +x deploy_aws.sh
	SECRET_ARN='$(SECRET_ARN)' \
	FUNCTION_NAME='gamma-sync' \
	ROLE_NAME='gamma-sync-lambda-role' \
	RULE_NAME='gamma-sync-schedule' \
	POLICY_NAME='gamma-sync-inline-policy' \
	SSM_CURSOR_KEY='/gamma/cursor' \
	KAFKA_TOPIC='demo_pm_gamma' \
	SYNC_ORDER_FIELD='createdAt' \
	SYNC_TIMESTAMP_FIELD='createdAt' \
	OPEN_ONLY='true' \
	LOOKBACK_SECONDS='0' \
	FULL_SWEEP='true' \
	DEDUP_MODE='content_hash' \
	HASH_FIELDS='metadata' \
	DEDUP='false' \
	CACHE_BUST='true' \
	MAX_PAGES_PER_RUN='0' \
	SUBMINUTE='true' \
	ITERATIONS='6' \
	WAIT_SECONDS='10' \
	LOCK_TABLE_NAME='gamma-sync-lock' \
	LOCK_ID='gamma-sync' \
	DISPATCH_FUNCTION_NAME='gamma-sync-dispatch' \
	DISPATCH_ROLE_NAME='gamma-sync-dispatch-role' \
	DISPATCH_POLICY_NAME='gamma-sync-dispatch-policy' \
	STATE_MACHINE_NAME='gamma-sync-subminute' \
	SFN_ROLE_NAME='gamma-sync-sfn-role' \
	SFN_POLICY_NAME='gamma-sync-sfn-policy' \
	EVENTS_ROLE_NAME='gamma-sync-events-role' \
	EVENTS_POLICY_NAME='gamma-sync-events-policy' \
	METRIC_NAMESPACE='GammaSync' \
	RESET_CURSOR='true' \
	CURSOR_INITIAL_VALUE='2020-01-01T00:00:00Z' \
	AWS_REGION='$(AWS_REGION)' \
	./deploy_aws.sh

# Fast new-market stack: gamma-sync-recent -> demo_pm_gamma
# createdAt DESC, first_seen dedup, LOOKBACK=180s to cover Gamma visibility delay.
# Sub-minute ~3s cadence for sub-minute new-market latency.
deploy-recent: package
	chmod +x deploy_aws.sh
	SECRET_ARN='$(SECRET_ARN)' \
	FUNCTION_NAME='gamma-sync-recent' \
	ROLE_NAME='gamma-sync-recent-lambda-role' \
	RULE_NAME='gamma-sync-recent-schedule' \
	POLICY_NAME='gamma-sync-recent-inline-policy' \
	SSM_CURSOR_KEY='/gamma/recent/cursor' \
	KAFKA_TOPIC='demo_pm_gamma' \
	SYNC_ORDER_FIELD='createdAt' \
	SYNC_TIMESTAMP_FIELD='createdAt' \
	OPEN_ONLY='true' \
	LOOKBACK_SECONDS='180' \
	DEDUP='true' \
	DEDUP_MODE='first_seen' \
	CACHE_BUST='true' \
	MAX_PAGES_PER_RUN='10' \
	SUBMINUTE='true' \
	ITERATIONS='20' \
	WAIT_SECONDS='3' \
	LOCK_TABLE_NAME='gamma-sync-recent-lock' \
	LOCK_ID='gamma-sync-recent' \
	DISPATCH_FUNCTION_NAME='gamma-sync-recent-dispatch' \
	DISPATCH_ROLE_NAME='gamma-sync-recent-dispatch-role' \
	DISPATCH_POLICY_NAME='gamma-sync-recent-dispatch-policy' \
	STATE_MACHINE_NAME='gamma-sync-recent-subminute' \
	SFN_ROLE_NAME='gamma-sync-recent-sfn-role' \
	SFN_POLICY_NAME='gamma-sync-recent-sfn-policy' \
	EVENTS_ROLE_NAME='gamma-sync-recent-events-role' \
	EVENTS_POLICY_NAME='gamma-sync-recent-events-policy' \
	METRIC_NAMESPACE='GammaSyncRecent' \
	RESET_CURSOR='true' \
	CURSOR_INITIAL_VALUE="$$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
	AWS_REGION='$(AWS_REGION)' \
	./deploy_aws.sh

# ---------------------------------------------------------------------------
# Destroy
# ---------------------------------------------------------------------------

# Generic single-stack destroy (original behaviour).
destroy:
	chmod +x destroy_aws.sh
	./destroy_aws.sh

# Tear down full-view stack (gamma-sync).
destroy-full:
	chmod +x destroy_aws.sh
	SUBMINUTE='true' \
	FUNCTION_NAME='gamma-sync' \
	ROLE_NAME='gamma-sync-lambda-role' \
	RULE_NAME='gamma-sync-schedule' \
	POLICY_NAME='gamma-sync-inline-policy' \
	LOCK_TABLE_NAME='gamma-sync-lock' \
	DISPATCH_FUNCTION_NAME='gamma-sync-dispatch' \
	DISPATCH_ROLE_NAME='gamma-sync-dispatch-role' \
	STATE_MACHINE_NAME='gamma-sync-subminute' \
	SFN_ROLE_NAME='gamma-sync-sfn-role' \
	EVENTS_ROLE_NAME='gamma-sync-events-role' \
	SSM_CURSOR_KEY='/gamma/cursor' \
	SECRET_ARN='$(SECRET_ARN)' \
	AWS_REGION='$(AWS_REGION)' \
	./destroy_aws.sh

# Tear down fast new-market stack (gamma-sync-recent).
# SECRET_ARN / SECRET_NAME are deliberately empty so the shared Kafka secret
# used by gamma-sync is NOT deleted.
destroy-recent:
	chmod +x destroy_aws.sh
	SUBMINUTE='true' \
	FUNCTION_NAME='gamma-sync-recent' \
	ROLE_NAME='gamma-sync-recent-lambda-role' \
	RULE_NAME='gamma-sync-recent-schedule' \
	POLICY_NAME='gamma-sync-recent-inline-policy' \
	LOCK_TABLE_NAME='gamma-sync-recent-lock' \
	DISPATCH_FUNCTION_NAME='gamma-sync-recent-dispatch' \
	DISPATCH_ROLE_NAME='gamma-sync-recent-dispatch-role' \
	DISPATCH_POLICY_NAME='gamma-sync-recent-dispatch-policy' \
	STATE_MACHINE_NAME='gamma-sync-recent-subminute' \
	SFN_ROLE_NAME='gamma-sync-recent-sfn-role' \
	SFN_POLICY_NAME='gamma-sync-recent-sfn-policy' \
	EVENTS_ROLE_NAME='gamma-sync-recent-events-role' \
	EVENTS_POLICY_NAME='gamma-sync-recent-events-policy' \
	SSM_CURSOR_KEY='/gamma/recent/cursor' \
	SECRET_ARN='' \
	SECRET_NAME='' \
	AWS_REGION='$(AWS_REGION)' \
	./destroy_aws.sh

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

smoke-kafka: package
	PYTHONPATH="$(PACKAGE_DIR)" $(PYTHON) smoke_test_kafka.py

# ---------------------------------------------------------------------------
# V2 parallel pipeline (createdAt full-sweep backbone + createdAt recent)
# Writes to demo_pm_gamma_v2. Runs beside the existing demo_pm_gamma pipeline.
# ---------------------------------------------------------------------------

# V2 backbone: gamma-sync-v2 -> demo_pm_gamma_v2
# createdAt full sweep + content_hash dedup. Continuous sub-minute cadence.
# First invocation backfills all ~49K open markets; subsequent sweeps are cheap
# (content_hash skips unchanged markets). Reuses orphaned gamma-sync-v2-* IAM roles.
deploy-v2-full: package
	chmod +x deploy_aws.sh
	SECRET_ARN='$(SECRET_ARN)' \
	FUNCTION_NAME='gamma-sync-v2' \
	ROLE_NAME='gamma-sync-v2-lambda-role' \
	RULE_NAME='gamma-sync-v2-schedule' \
	POLICY_NAME='gamma-sync-v2-inline-policy' \
	SSM_CURSOR_KEY='/gamma/v2/cursor' \
	KAFKA_TOPIC='demo_pm_gamma_v2' \
	SYNC_ORDER_FIELD='createdAt' \
	SYNC_TIMESTAMP_FIELD='createdAt' \
	OPEN_ONLY='true' \
	LOOKBACK_SECONDS='0' \
	FULL_SWEEP='true' \
	DEDUP_MODE='content_hash' \
	HASH_FIELDS='metadata' \
	DEDUP='false' \
	CACHE_BUST='true' \
	MAX_PAGES_PER_RUN='0' \
	SUBMINUTE='true' \
	ITERATIONS='6' \
	WAIT_SECONDS='10' \
	LOCK_TABLE_NAME='gamma-sync-v2-lock' \
	LOCK_ID='gamma-sync-v2' \
	DISPATCH_FUNCTION_NAME='gamma-sync-v2-dispatch' \
	DISPATCH_ROLE_NAME='gamma-sync-v2-dispatch-role' \
	DISPATCH_POLICY_NAME='gamma-sync-v2-dispatch-policy' \
	STATE_MACHINE_NAME='gamma-sync-v2-subminute' \
	SFN_ROLE_NAME='gamma-sync-v2-sfn-role' \
	SFN_POLICY_NAME='gamma-sync-v2-sfn-policy' \
	EVENTS_ROLE_NAME='gamma-sync-v2-events-role' \
	EVENTS_POLICY_NAME='gamma-sync-v2-events-policy' \
	METRIC_NAMESPACE='GammaSyncV2' \
	RESET_CURSOR='true' \
	CURSOR_INITIAL_VALUE='2020-01-01T00:00:00Z' \
	AWS_REGION='$(AWS_REGION)' \
	./deploy_aws.sh

# V2 recent: gamma-sync-v2-recent -> demo_pm_gamma_v2
# createdAt DESC, first_seen dedup, LOOKBACK=180s to cover Gamma visibility delay.
# Sub-minute ~3s cadence for sub-minute new-market latency.
deploy-v2-recent: package
	chmod +x deploy_aws.sh
	SECRET_ARN='$(SECRET_ARN)' \
	FUNCTION_NAME='gamma-sync-v2-recent' \
	ROLE_NAME='gamma-sync-v2-recent-lambda-role' \
	RULE_NAME='gamma-sync-v2-recent-schedule' \
	POLICY_NAME='gamma-sync-v2-recent-inline-policy' \
	SSM_CURSOR_KEY='/gamma/v2/recent/cursor' \
	KAFKA_TOPIC='demo_pm_gamma_v2' \
	SYNC_ORDER_FIELD='createdAt' \
	SYNC_TIMESTAMP_FIELD='createdAt' \
	OPEN_ONLY='true' \
	LOOKBACK_SECONDS='180' \
	DEDUP='true' \
	DEDUP_MODE='first_seen' \
	CACHE_BUST='true' \
	MAX_PAGES_PER_RUN='10' \
	SUBMINUTE='true' \
	ITERATIONS='20' \
	WAIT_SECONDS='3' \
	LOCK_TABLE_NAME='gamma-sync-v2-recent-lock' \
	LOCK_ID='gamma-sync-v2-recent' \
	DISPATCH_FUNCTION_NAME='gamma-sync-v2-recent-dispatch' \
	DISPATCH_ROLE_NAME='gamma-sync-v2-recent-dispatch-role' \
	DISPATCH_POLICY_NAME='gamma-sync-v2-recent-dispatch-policy' \
	STATE_MACHINE_NAME='gamma-sync-v2-recent-subminute' \
	SFN_ROLE_NAME='gamma-sync-v2-recent-sfn-role' \
	SFN_POLICY_NAME='gamma-sync-v2-recent-sfn-policy' \
	EVENTS_ROLE_NAME='gamma-sync-v2-recent-events-role' \
	EVENTS_POLICY_NAME='gamma-sync-v2-recent-events-policy' \
	METRIC_NAMESPACE='GammaSyncV2Recent' \
	RESET_CURSOR='true' \
	CURSOR_INITIAL_VALUE="$$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
	AWS_REGION='$(AWS_REGION)' \
	./deploy_aws.sh

# Tear down V2 backbone (gamma-sync-v2). Does NOT delete the shared Kafka secret.
destroy-v2-full:
	chmod +x destroy_aws.sh
	SUBMINUTE='true' \
	FUNCTION_NAME='gamma-sync-v2' \
	ROLE_NAME='gamma-sync-v2-lambda-role' \
	RULE_NAME='gamma-sync-v2-schedule' \
	POLICY_NAME='gamma-sync-v2-inline-policy' \
	LOCK_TABLE_NAME='gamma-sync-v2-lock' \
	DISPATCH_FUNCTION_NAME='gamma-sync-v2-dispatch' \
	DISPATCH_ROLE_NAME='gamma-sync-v2-dispatch-role' \
	DISPATCH_POLICY_NAME='gamma-sync-v2-dispatch-policy' \
	STATE_MACHINE_NAME='gamma-sync-v2-subminute' \
	SFN_ROLE_NAME='gamma-sync-v2-sfn-role' \
	EVENTS_ROLE_NAME='gamma-sync-v2-events-role' \
	SSM_CURSOR_KEY='/gamma/v2/cursor' \
	SECRET_ARN='' \
	SECRET_NAME='' \
	AWS_REGION='$(AWS_REGION)' \
	./destroy_aws.sh

# Tear down V2 recent (gamma-sync-v2-recent). Does NOT delete the shared Kafka secret.
destroy-v2-recent:
	chmod +x destroy_aws.sh
	SUBMINUTE='true' \
	FUNCTION_NAME='gamma-sync-v2-recent' \
	ROLE_NAME='gamma-sync-v2-recent-lambda-role' \
	RULE_NAME='gamma-sync-v2-recent-schedule' \
	POLICY_NAME='gamma-sync-v2-recent-inline-policy' \
	LOCK_TABLE_NAME='gamma-sync-v2-recent-lock' \
	DISPATCH_FUNCTION_NAME='gamma-sync-v2-recent-dispatch' \
	DISPATCH_ROLE_NAME='gamma-sync-v2-recent-dispatch-role' \
	DISPATCH_POLICY_NAME='gamma-sync-v2-recent-dispatch-policy' \
	STATE_MACHINE_NAME='gamma-sync-v2-recent-subminute' \
	SFN_ROLE_NAME='gamma-sync-v2-recent-sfn-role' \
	SFN_POLICY_NAME='gamma-sync-v2-recent-sfn-policy' \
	EVENTS_ROLE_NAME='gamma-sync-v2-recent-events-role' \
	EVENTS_POLICY_NAME='gamma-sync-v2-recent-events-policy' \
	SSM_CURSOR_KEY='/gamma/v2/recent/cursor' \
	SECRET_ARN='' \
	SECRET_NAME='' \
	AWS_REGION='$(AWS_REGION)' \
	./destroy_aws.sh
