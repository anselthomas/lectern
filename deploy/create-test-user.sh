#!/bin/bash
# Create (or reset) the internal QA user. Credentials go only to SSM /lectern/test-user, never to stdout.
# Usage: deploy/create-test-user.sh EMAIL [PROFILE]
set -euo pipefail
EMAIL=$1
PROFILE=${2:-lectern}
REGION=ap-southeast-2
export MSYS_NO_PATHCONV=1
POOL=$(aws cloudformation describe-stacks --stack-name lectern-core --region $REGION --profile "$PROFILE" \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)
SITE=$(aws cloudformation describe-stacks --stack-name lectern-core --region $REGION --profile "$PROFILE" \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontUrl'].OutputValue" --output text)
PW=$(python -c "import secrets,string;a=string.ascii_letters+string.digits;print('Lt'+''.join(secrets.choice(a) for _ in range(18))+'7q')")

aws cognito-idp admin-create-user --user-pool-id "$POOL" --username "$EMAIL" --message-action SUPPRESS \
  --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true Name=name,Value="Lectern QA" \
  --region $REGION --profile "$PROFILE" >/dev/null 2>&1 || echo "user exists, resetting password"
aws cognito-idp admin-set-user-password --user-pool-id "$POOL" --username "$EMAIL" --password "$PW" --permanent \
  --region $REGION --profile "$PROFILE"
aws ssm put-parameter --name /lectern/test-user --type SecureString --overwrite \
  --value "{\"email\":\"$EMAIL\",\"password\":\"$PW\",\"url\":\"$SITE/signin\"}" \
  --region $REGION --profile "$PROFILE" >/dev/null

# Mark the account internal (no plan limits) in the app database.
GRANT=$(mktemp)
cat > "$GRANT" <<EOF
cd /opt/lectern/src/deploy && docker compose exec -T api python -m app.admin grant-internal "$EMAIL"
EOF
bash "$(dirname "$0")/run-on-host.sh" "$GRANT" "$PROFILE" | tail -2
echo "test user $EMAIL ready. Read the password with:"
echo "  aws ssm get-parameter --name /lectern/test-user --with-decryption --query Parameter.Value --output text --region $REGION"
