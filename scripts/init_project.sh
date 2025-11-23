#!/usr/bin/env bash
set -e

mkdir -p scripts/Build

CONFIG=$(<scripts/config.json)
DB_NAME=$(echo "$CONFIG" | jq -r .db_name)
FN_NAME=$(echo "$CONFIG" | jq -r .function_name)
SA_NAME=$(echo "$CONFIG" | jq -r .service_account_name)

echo "Creating database..."

yc ydb database create \
  --name $DB_NAME \
  --serverless \
  --location ru-central1

echo "Database created!"



echo "Creating serverless function..."

yc iam key create --service-account-name $SA_NAME \
  --output scripts/Build/key.sa 

yc serverless function create --name "$FN_NAME" || true
bash scripts/deploy_function.sh
yc serverless function allow-unauthenticated-invoke "$FN_NAME"

echo "Serverless function created!"



# Если есть необходимость, то можно вынести в отдельный скрипт, но как будто создание БД и ее инициализация по логике должны быть где-то рядом
echo "Invoking function in schema init mode..."

yc serverless function invoke "$FN_NAME" \
  --data '{"MODE": "init"}' \
  --format json


bash scripts/create_api_gateway.sh

