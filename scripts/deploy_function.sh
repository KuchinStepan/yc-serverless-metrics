#!/usr/bin/env bash
set -e

CONFIG=$(<scripts/config.json)
DB_NAME=$(echo "$CONFIG" | jq -r .db_name)
FN_NAME=$(echo "$CONFIG" | jq -r .function_name)
SA_NAME=$(echo "$CONFIG" | jq -r .service_account_name)

VERSION=$(git rev-parse  --short HEAD)

DB_PATH=$(yc ydb database get $DB_NAME --format json | jq -r '.endpoint')
ENDPOINT=$(echo "$DB_PATH" | cut -d'?' -f1)
DATABASE=$(echo "$DB_PATH" | grep -oP '(?<=database=)[^&]+')

SA_ID=$(yc iam service-account get --name $SA_NAME --format json | jq -r '.id')

cd backend/
cp ../scripts/Build/key.sa auth.sa && zip ../scripts/Build/src.zip handler.py requirements.txt auth.sa && rm auth.sa
cd ..

yc serverless function version create \
  --function-name "$FN_NAME" \
  --runtime python39 \
  --entrypoint handler.handler \
  --memory 128m \
  --execution-timeout 30s \
  --environment USE_METADATA_CREDENTIALS=1 \
  --environment endpoint="grpcs://ydb.serverless.yandexcloud.net:2135" \
  --environment database=$DATABASE \
  --environment BACKEND_VERSION="$VERSION" \
  --service-account-id $SA_ID \
  --source-path scripts/Build/src.zip
