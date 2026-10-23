#!/bin/bash
# Run a script on the app host through SSM and print its output. Usage: deploy/run-on-host.sh SCRIPT [PROFILE]
set -euo pipefail
SCRIPT=$1
PROFILE=${2:-lectern}
REGION=ap-southeast-2
export MSYS_NO_PATHCONV=1 PYTHONUTF8=1
IID=$(aws cloudformation describe-stacks --stack-name lectern-core --region $REGION --profile "$PROFILE" \
  --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" --output text)
PARAMS=$(python -c "import json,sys;print(json.dumps({'commands':open(sys.argv[1],encoding='utf-8').read().split('\n'),'executionTimeout':['1800']}))" "$SCRIPT")
CID=$(aws ssm send-command --instance-ids "$IID" --document-name AWS-RunShellScript --timeout-seconds 1800 \
  --parameters "$PARAMS" --region $REGION --profile "$PROFILE" --query Command.CommandId --output text)
while true; do
  S=$(aws ssm get-command-invocation --command-id "$CID" --instance-id "$IID" --region $REGION --profile "$PROFILE" --query Status --output text 2>/dev/null || echo Pending)
  case $S in Success|Failed|TimedOut|Cancelled) break;; esac
  sleep 5
done
aws ssm get-command-invocation --command-id "$CID" --instance-id "$IID" --region $REGION --profile "$PROFILE" --output json \
  | python -c "import json,sys;d=json.load(sys.stdin);print(d['Status']);print(d['StandardOutputContent']);print(d['StandardErrorContent'][-3000:])"
[ "$S" = Success ]
