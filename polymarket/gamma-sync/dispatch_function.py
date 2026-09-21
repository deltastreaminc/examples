"""Sub-minute dispatcher for gamma-sync.

Invoked by a Step Functions state machine every ~10 seconds. Implements the
"attempt every 10s, skip if a prior run is still active, never queue" contract
using a DynamoDB conditional lock:

- Acquire the lock if it is free (no item) or its lease has expired.
- On acquire: asynchronously invoke gamma-sync with {lock_id, owner} so the
  worker can release the lock when it finishes.
- On contention: return "skipped_busy" without invoking anything.

gamma-sync (the worker) releases the lock in a finally block. The lease
(expires_at) is only crash-recovery: if a worker dies without releasing, the
next attempt after the lease window can re-acquire.
"""

import os
import time
import uuid

import boto3

LOCK_TABLE = os.environ["LOCK_TABLE"]
TARGET_FUNCTION = os.environ["TARGET_FUNCTION"]
LOCK_ID = os.environ.get("LOCK_ID", "gamma-sync")
LOCK_TTL_SECONDS = int(os.environ.get("LOCK_TTL_SECONDS", "960"))
METRIC_NAMESPACE = os.environ.get("METRIC_NAMESPACE", "GammaSync")

dynamodb = boto3.client("dynamodb")
lambda_client = boto3.client("lambda")
cloudwatch = boto3.client("cloudwatch")


def _emit(metric_name: str) -> None:
    try:
        cloudwatch.put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[
                {
                    "MetricName": metric_name,
                    "Value": 1,
                    "Unit": "Count",
                    "Dimensions": [{"Name": "LockId", "Value": LOCK_ID}],
                }
            ],
        )
    except Exception as exc:  # pragma: no cover - metrics are best effort
        print(f"Metric emit failed metric={metric_name}: {exc}")


def _try_acquire(owner: str, now: int) -> bool:
    """Acquire the lock if free or lease-expired. Returns True on success."""
    expires_at = now + LOCK_TTL_SECONDS
    try:
        dynamodb.update_item(
            TableName=LOCK_TABLE,
            Key={"lock_id": {"S": LOCK_ID}},
            UpdateExpression="SET #o = :owner, acquired_at = :now, expires_at = :exp",
            ConditionExpression="attribute_not_exists(lock_id) OR expires_at < :now",
            ExpressionAttributeNames={"#o": "owner"},
            ExpressionAttributeValues={
                ":owner": {"S": owner},
                ":now": {"N": str(now)},
                ":exp": {"N": str(expires_at)},
            },
        )
        return True
    except dynamodb.exceptions.ConditionalCheckFailedException:
        return False


def handler(event, context):
    now = int(time.time())
    owner = str(uuid.uuid4())

    if not _try_acquire(owner, now):
        _emit("skipped_busy")
        print(f"skipped_busy lock_id={LOCK_ID}")
        return {"status": "skipped_busy", "lock_id": LOCK_ID}

    try:
        lambda_client.invoke(
            FunctionName=TARGET_FUNCTION,
            InvocationType="Event",
            Payload=(
                '{"lock_id": "%s", "owner": "%s"}' % (LOCK_ID, owner)
            ).encode("utf-8"),
        )
    except Exception as exc:
        # Could not hand off the run; release the lock so we do not block the
        # next attempt, and surface the failure.
        _emit("acquire_error")
        try:
            dynamodb.delete_item(
                TableName=LOCK_TABLE,
                Key={"lock_id": {"S": LOCK_ID}},
                ConditionExpression="#o = :owner",
                ExpressionAttributeNames={"#o": "owner"},
                ExpressionAttributeValues={":owner": {"S": owner}},
            )
        except Exception:
            pass
        print(f"invoke_failed lock_id={LOCK_ID}: {exc}")
        raise

    _emit("invoked")
    print(f"invoked target={TARGET_FUNCTION} lock_id={LOCK_ID} owner={owner}")
    return {"status": "invoked", "lock_id": LOCK_ID, "owner": owner}
