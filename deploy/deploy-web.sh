#!/bin/bash
# Build the React app and publish it to the web bucket behind CloudFront. Usage: deploy/deploy-web.sh [PROFILE]
set -euo pipefail
PROFILE=${1:-lectern}
REGION=ap-southeast-2
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../frontend"
out() { aws cloudformation describe-stacks --stack-name lectern-core --region $REGION --profile "$PROFILE" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
BUCKET=$(out WebBucketName)
DIST=$(out DistributionId)
export VITE_USER_POOL_ID=$(out UserPoolId) VITE_CLIENT_ID=$(out UserPoolClientId)

npm ci --no-audit --no-fund >/dev/null
npm run build
# Hashed assets are immutable; index.html must always revalidate.
aws s3 sync dist/assets "s3://$BUCKET/assets" --cache-control "public, max-age=31536000, immutable" --region $REGION --profile "$PROFILE" --only-show-errors
aws s3 cp dist/index.html "s3://$BUCKET/index.html" --cache-control "no-cache" --content-type "text/html; charset=utf-8" --region $REGION --profile "$PROFILE" --only-show-errors
aws s3 sync dist "s3://$BUCKET" --exclude "index.html" --exclude "assets/*" --exclude "qa/*" --delete --region $REGION --profile "$PROFILE" --only-show-errors
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/index.html" "/" --profile "$PROFILE" --query Invalidation.Id --output text
echo "published to https://$(aws cloudfront get-distribution --id "$DIST" --profile "$PROFILE" --query Distribution.DomainName --output text)"
