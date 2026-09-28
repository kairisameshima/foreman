import logging
import time
from datetime import datetime
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import EndpointConnectionError

from foreman.errors import NotFoundError
from foreman.models import Entry, Sprint, SprintStatus, WorkItem, iso_timestamp

logger = logging.getLogger(__name__)

GSI_NAME = "gsi1"
META_SK = "META"
SPRINT_GSI_PK = "SPRINT"
ENTRY_PREFIX = "ENTRY#"
ITEM_PREFIX = "ITEM#"
SPRINT_PREFIX = "SPRINT#"
CONNECT_ATTEMPTS = 30
CONNECT_RETRY_SECONDS = 1.0


def _entry_sort_key(entry: Entry) -> str:
    return f"{ENTRY_PREFIX}{iso_timestamp(entry.created_at)}#{entry.entry_id}"


class DynamoStore:
    def __init__(self, table_name: str, endpoint_url: str) -> None:
        self._table_name = table_name
        self._resource = boto3.resource("dynamodb", endpoint_url=endpoint_url)
        self._table = self._resource.Table(table_name)

    def ensure_table(self) -> None:
        client = self._resource.meta.client
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                client.describe_table(TableName=self._table_name)
                return
            except client.exceptions.ResourceNotFoundException:
                break
            except EndpointConnectionError:
                if attempt == CONNECT_ATTEMPTS:
                    raise
                logger.info("DynamoDB not reachable yet, retrying (%d)", attempt)
                time.sleep(CONNECT_RETRY_SECONDS)
        client.create_table(
            TableName=self._table_name,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "gsi1pk", "AttributeType": "S"},
                {"AttributeName": "gsi1sk", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": GSI_NAME,
                    "KeySchema": [
                        {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                        {"AttributeName": "gsi1sk", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        client.get_waiter("table_exists").wait(TableName=self._table_name)
        logger.info("Created DynamoDB table %s", self._table_name)

    def put_sprint(self, sprint: Sprint) -> None:
        self._table.put_item(
            Item={
                **sprint.model_dump(mode="json"),
                "pk": f"{SPRINT_PREFIX}{sprint.sprint_id}",
                "sk": META_SK,
                "gsi1pk": SPRINT_GSI_PK,
                "gsi1sk": f"{sprint.start_date.isoformat()}#{sprint.sprint_id}",
                "entity_type": "sprint",
            }
        )

    def get_sprint(self, sprint_id: str) -> Sprint:
        response = self._table.get_item(Key={"pk": f"{SPRINT_PREFIX}{sprint_id}", "sk": META_SK})
        if "Item" not in response:
            raise NotFoundError(f"sprint {sprint_id} not found")
        return Sprint.model_validate(response["Item"])

    def list_sprints(self) -> list[Sprint]:
        records = self._query_all(
            IndexName=GSI_NAME,
            KeyConditionExpression=Key("gsi1pk").eq(SPRINT_GSI_PK),
            ScanIndexForward=False,
        )
        return [Sprint.model_validate(record) for record in records]

    def find_active_sprint(self) -> Sprint | None:
        return next((s for s in self.list_sprints() if s.status == SprintStatus.ACTIVE), None)

    def put_work_item(self, item: WorkItem) -> None:
        self._table.put_item(
            Item={
                **item.model_dump(mode="json"),
                "pk": f"{ITEM_PREFIX}{item.work_item_id}",
                "sk": META_SK,
                "gsi1pk": f"{SPRINT_PREFIX}{item.sprint_id}",
                "gsi1sk": f"{ITEM_PREFIX}{iso_timestamp(item.created_at)}#{item.work_item_id}",
                "entity_type": "work_item",
            }
        )

    def get_work_item(self, work_item_id: str) -> WorkItem:
        response = self._table.get_item(Key={"pk": f"{ITEM_PREFIX}{work_item_id}", "sk": META_SK})
        if "Item" not in response:
            raise NotFoundError(f"work item {work_item_id} not found")
        return WorkItem.model_validate(response["Item"])

    def list_work_items(self, sprint_id: str) -> list[WorkItem]:
        records = self._query_all(
            IndexName=GSI_NAME,
            KeyConditionExpression=Key("gsi1pk").eq(f"{SPRINT_PREFIX}{sprint_id}")
            & Key("gsi1sk").begins_with(ITEM_PREFIX),
        )
        return [WorkItem.model_validate(record) for record in records]

    def put_entry(self, entry: Entry) -> None:
        sort_key = _entry_sort_key(entry)
        record: dict[str, Any] = {
            **entry.model_dump(mode="json"),
            "pk": f"{SPRINT_PREFIX}{entry.sprint_id}",
            "sk": sort_key,
            "entity_type": "entry",
        }
        # Sprint-level entries leave the GSI keys out so they stay out of the sparse index.
        if entry.work_item_id is not None:
            record["gsi1pk"] = f"{ITEM_PREFIX}{entry.work_item_id}"
            record["gsi1sk"] = sort_key
        self._table.put_item(Item=record)

    def list_sprint_entries(
        self,
        sprint_id: str,
        since: datetime | None,
        until: datetime | None,
        limit: int,
    ) -> list[Entry]:
        partition = Key("pk").eq(f"{SPRINT_PREFIX}{sprint_id}")
        if since is None and until is None:
            condition = partition & Key("sk").begins_with(ENTRY_PREFIX)
        else:
            # The upper bound has no "#<entry_id>" suffix, so entries at exactly `until`
            # sort after it and `until` behaves as an exclusive bound.
            lower = f"{ENTRY_PREFIX}{iso_timestamp(since)}" if since else ENTRY_PREFIX
            upper = f"{ENTRY_PREFIX}{iso_timestamp(until)}" if until else f"{ENTRY_PREFIX}~"
            condition = partition & Key("sk").between(lower, upper)
        response = self._table.query(
            KeyConditionExpression=condition, ScanIndexForward=False, Limit=limit
        )
        return [Entry.model_validate(record) for record in response["Items"]]

    def list_item_entries(self, work_item_id: str, limit: int) -> list[Entry]:
        response = self._table.query(
            IndexName=GSI_NAME,
            KeyConditionExpression=Key("gsi1pk").eq(f"{ITEM_PREFIX}{work_item_id}"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [Entry.model_validate(record) for record in response["Items"]]

    def _query_all(self, **query: Any) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        while True:
            response = self._table.query(**query)
            records.extend(response["Items"])
            if "LastEvaluatedKey" not in response:
                return records
            query["ExclusiveStartKey"] = response["LastEvaluatedKey"]
