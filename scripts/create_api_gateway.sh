#!/usr/bin/env bash
set -e

CONFIG=$(<scripts/config.json)
BUCKET=$(echo "$CONFIG" | jq -r .bucket_name)
FN_NAME=$(echo "$CONFIG" | jq -r .function_name)
GATEWAY_NAME=$(echo "$CONFIG" | jq -r .gateway_name)
SA_NAME=$(echo "$CONFIG" | jq -r .service_account_name)

FUNCTION_ID=$(yc serverless function get --name $FN_NAME --format json | jq -r '.id')
SA_ID=$(yc iam service-account get --name $SA_NAME --format json | jq -r '.id')



echo "Creating api-gateway..."

cat > scripts/Build/gateway_conf.yml <<EOF
openapi: 3.0.0
info:
  title: $GATEWAY_NAME
  version: 1.0.0
paths:
  /metrics:
    post:
      x-yc-apigateway-integration:
        type: cloud_functions
        function_id:  $FUNCTION_ID
        tag: "$latest"
        service_account:    $SA_ID
      operationId: post-metrics
      responses:
        200:
          description: Success
          content:
            application/json: {}
    get:
      x-yc-apigateway-integration:
        type: cloud_functions
        function_id:  $FUNCTION_ID
        tag: "$latest"
        service_account:    $SA_ID
      operationId: get-metrics
      responses:
        200:
          description: Success
          content:
            application/json: {}
EOF


yc serverless api-gateway create \
  --name $GATEWAY_NAME \
  --spec=scripts/Build/gateway_conf.yml \
  --description "for serverless metrics"


DOMAIN="https://$(yc serverless api-gateway get for-serverless-metrics --format json | jq -r '.domain')/metrics"

echo "Api-gateway created!"
echo $DOMAIN
