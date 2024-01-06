import logging

from datetime import datetime

from spaceone.core.utils import generate_id

from conf import DEFAULT_LOGGER
from lib import MongoCustomClient
from lib.util import print_log

_LOGGER = logging.getLogger(DEFAULT_LOGGER)


@print_log
def secret_secret_migration(
    mongo_client: MongoCustomClient, domain_id_param, project_map
):
    schema_id = ""
    resource_group = "PROJECT"
    project_id = ""
    workspace_id = ""

    for secret_info in mongo_client.find(
        "SECRET", "secret", {"domain_id": domain_id_param}, {}
    ):
        if secret_info.get("workspace_id"):
            continue

        schema = secret_info.get("schema")
        if schema:
            schema_id = _get_schema_to_schema_id(schema)

        if secret_info.get("project_id"):
            workspace_id = project_map[secret_info["domain_id"]].get(
                secret_info.get("project_id")
            )
        elif secret_info.get("service_account_id"):
            service_account_info = mongo_client.find_one(
                "IDENTITY",
                "service_account",
                {
                    "domain_id": secret_info["domain_id"],
                    "service_account_id": secret_info["service_account_id"],
                },
                {"workspace_id": 1, "project_id": 1},
            )

            if not service_account_info:
                mongo_client.update_one(
                    "SECRET", "secret",
                    {"_id": secret_info.get("_id")}, {"$set": {"tags.homeless": True}}
                )
                continue

            workspace_id = service_account_info.get("workspace_id")
            project_id = service_account_info.get("project_id")
            
        if not workspace_id:
            _LOGGER.error(
                f"Secret service_account({secret_info['service_account_id']}) does not exists in IDENTITY.sa"
            )
        
        set_param = {
            "$set": {
                "secret_schema_id": schema_id,
                "secret_id": secret_info["secret_id"],
            }
        }
        mongo_client.update_many(
            "IDENTITY", "service_account",
            {"service_account_id": secret_info.get("service_account_id")},
            set_param,
        )

        set_params = {
            "$set": {
                "schema_id": schema_id,
                "resource_group": resource_group,
                "workspace_id": workspace_id,
            },
            "$unset": {"secret_type": 1, "schema": 1},
        }

        if project_id:
            set_params["$set"].update({"project_id": project_id})

        mongo_client.update_one(
            "SECRET", "secret", {"_id": secret_info["_id"]}, set_params
        )


@print_log
def secret_trusted_secret_migration(mongo_client: MongoCustomClient, domain_id_param):
    schema_id = ""

    for trusted_secret_info in mongo_client.find(
        "SECRET", "trusted_secret", {"domain_id": domain_id_param}, {}
    ):
        if trusted_secret_info.get("workspace_id"):
            continue

        schema = trusted_secret_info.get("schema")

        if schema:
            schema_id = _get_schema_to_schema_id(schema)

        set_params = {
            "$set": {
                "schema_id": schema_id,
                "resource_group": "DOMAIN",
                "workspace_id": "*",
            },
            "$unset": {"secret_type": 1, "schema": 1},
        }

        mongo_client.update_one(
            "SECRET", "trusted_secret", {"_id": trusted_secret_info["_id"]}, set_params
        )

        if trusted_secret_info.get("trusted_account_id"):
            set_param = {
                "$set": {
                    "secret_schema_id": schema_id,
                    "trusted_secret_id": trusted_secret_info["trusted_secret_id"],
                }
            }
            mongo_client.update_many(
                "IDENTITY", "trusted_account",
                {"trusted_account_id": trusted_secret_info.get("trusted_secret_id")},
                set_param,
            )
        
        if trusted_secret_info.get("service_account_id"):
            service_account_info = mongo_client.find_one(
                "IDENTITY", "service_account"
                , {"service_account_id": trusted_secret_info.get("service_account_id")}, {}
            )

            new_trusted_account_id = generate_id("ta")
            trusted_account_create = {
                "trusted_account_id": new_trusted_account_id,
                "name": service_account_info.get("name"),
                "data": service_account_info.get("data"),
                "provider": service_account_info.get("provider"),
                "tags": service_account_info.get("tags"),
                "secret_schema_id": schema_id,
                "trusted_secret_id": trusted_secret_info.get("trusted_secret_id"),
                "resource_group": "DOMAIN",
                "workspace_id": "*",
                "domain_id": service_account_info["domain_id"],
                "created_at": datetime.utcnow(),
            }

            mongo_client.insert_one(
                "IDENTITY", "trusted_account", trusted_account_create
            )

            mongo_client.update_one(
                "SECRET", "trusted_secret"
                , {"_id": trusted_secret_info["_id"]}
                , {
                    "$set": {"trusted_account_id": new_trusted_account_id},
                    "$unset": {"service_account_id": 1}
                }
            )

            mongo_client.delete_many(
                "IDENTITY", "service_account"
                , {"service_account_id": service_account_info["service_account_id"]}
            )


def _get_schema_to_schema_id(schema):
    
    schema_id = None
    if schema == "azure_subscription_id":
        schema_id = "azure-secret-subscription-id"
    elif schema == "azure_client_secret":
        schema_id = "azure-secret-client-secret"
    elif schema == "google_oauth2_credentials":
        schema_id = "google-secret-oauth2-credentials"
    elif schema == "aws_assume_role" or schema == "aws_assume_role_with_external_id":
        schema_id = "aws-secret-assume-role"
    elif schema == "aws_access_key":
        schema_id = "aws-secret-access-key"
    elif schema == "google_project_id":
        schema_id = "google-secret-project-id"
    return schema_id


@print_log
def drop_collections(mongo_client):
    collections = ["secret_group", "secret_group_map"]
    for collection in collections:
        mongo_client.drop_collection("SECRET", collection)


@print_log
def secret_drop_indexes(mongo_client: MongoCustomClient):
    mongo_client.drop_indexes("SECRET", "*")


def main(mongo_client: MongoCustomClient, domain_id_param, project_map):
    secret_drop_indexes(mongo_client)
    secret_secret_migration(mongo_client, domain_id_param, project_map)
    secret_trusted_secret_migration(mongo_client, domain_id_param)
