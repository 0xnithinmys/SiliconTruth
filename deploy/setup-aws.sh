#!/usr/bin/env bash
# The parts of the AWS setup that grant access or store secrets.
#
# Separated out deliberately: these three things hand an external party a key
# to the account, or put a live credential into it, and they should be run by
# a human who can see what they are agreeing to.
#
# Everything else -- ECR repositories, the instance role, the security group,
# the instance itself -- is already provisioned.
#
#   bash deploy/setup-aws.sh
set -euo pipefail

REGION=us-east-1
ACCOUNT=323708468700
REPO=0xnithinmys/SiliconTruth
export AWS_PAGER=""

# Git Bash on Windows rewrites any argument that looks like a Unix path into
# a Windows one before the program sees it, so an SSM parameter named
# /silicontruth/MODEL_API_KEY arrived as
# C:/Program Files/Git/silicontruth/MODEL_API_KEY and PutParameter rejected
# it as "not a fully qualified name". Harmless everywhere else: off MSYS
# these variables are simply ignored.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

# Policy documents are written beside this script and passed as RELATIVE
# paths. mktemp returns /tmp/..., which Git Bash understands and the Windows
# aws.exe does not -- a different filesystem namespace, so file:///tmp/x.json
# is simply not there.
WORK=".aws-setup"
mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

echo "== 1/3  secrets into SSM Parameter Store =="
# Read from the repo's .env rather than being pasted on a command line, so the
# key never lands in shell history.
KEY=$(grep -E '^MODEL_API_KEY=' .env | cut -d= -f2-)
[ -n "$KEY" ] || { echo "MODEL_API_KEY not found in .env"; exit 1; }

# One password for live mode. Generated, not chosen, because this one guards
# a paid inference key.
LIVE_PASSWORD=$(python -c 'import secrets;print(secrets.token_urlsafe(18))')

aws ssm put-parameter --region "$REGION" --name /silicontruth/MODEL_API_KEY \
    --type SecureString --value "$KEY" --overwrite >/dev/null
aws ssm put-parameter --region "$REGION" --name /silicontruth/LIVE_PASSWORD \
    --type SecureString --value "$LIVE_PASSWORD" --overwrite >/dev/null

echo "   stored. live-mode password (save this, it is not shown again):"
echo
echo "       $LIVE_PASSWORD"
echo

echo "== 2/3  let GitHub Actions assume a role, with no stored AWS keys =="
OIDC="arn:aws:iam::${ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"
aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC" >/dev/null 2>&1 || \
aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 >/dev/null

TRUST="$WORK/trust.json"; POLICY="$WORK/policy.json"
cat > "$TRUST" <<JSON
{"Version":"2012-10-17","Statement":[{
  "Effect":"Allow",
  "Principal":{"Federated":"$OIDC"},
  "Action":"sts:AssumeRoleWithWebIdentity",
  "Condition":{
    "StringEquals":{"token.actions.githubusercontent.com:aud":"sts.amazonaws.com"},
    "StringLike":{"token.actions.githubusercontent.com:sub":"repo:${REPO}:*"}
  }}]}
JSON

# Scoped to this project's repositories and this project's instances. Not
# PowerUser, not "*".
cat > "$POLICY" <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["ecr:GetAuthorizationToken"],"Resource":"*"},
 {"Effect":"Allow","Action":["ecr:BatchCheckLayerAvailability","ecr:CompleteLayerUpload","ecr:InitiateLayerUpload","ecr:PutImage","ecr:UploadLayerPart","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],
  "Resource":"arn:aws:ecr:${REGION}:${ACCOUNT}:repository/silicontruth-*"},
 {"Effect":"Allow","Action":["ssm:SendCommand"],
  "Resource":["arn:aws:ssm:${REGION}::document/AWS-RunShellScript","arn:aws:ec2:${REGION}:${ACCOUNT}:instance/*"]},
 {"Effect":"Allow","Action":["ssm:GetCommandInvocation","ssm:ListCommandInvocations"],"Resource":"*"},
 {"Effect":"Allow","Action":["ec2:DescribeInstances"],"Resource":"*"}
]}
JSON

aws iam get-role --role-name silicontruth-ci >/dev/null 2>&1 \
  && aws iam update-assume-role-policy --role-name silicontruth-ci --policy-document "file://$TRUST" \
  || aws iam create-role --role-name silicontruth-ci --assume-role-policy-document "file://$TRUST" >/dev/null
aws iam put-role-policy --role-name silicontruth-ci --policy-name deploy --policy-document "file://$POLICY"
echo "   role: arn:aws:iam::${ACCOUNT}:role/silicontruth-ci"

echo "== 3/3  push the new secrets onto the running instance =="
ID=$(aws ec2 describe-instances --region "$REGION" \
      --filters Name=tag:Name,Values=silicontruth Name=instance-state-name,Values=running \
      --query "Reservations[0].Instances[0].InstanceId" --output text)
aws ssm send-command --region "$REGION" --instance-ids "$ID" \
    --document-name AWS-RunShellScript \
    --parameters 'commands=["/usr/local/bin/silicontruth-deploy latest"]' \
    --query "Command.CommandId" --output text

echo
echo "Done. Push to main and .github/workflows/deploy.yml takes it from here."
