from functools import lru_cache

import boto3
from botocore.config import Config

from .config import settings


@lru_cache
def s3():
    # Regional virtual-host endpoint so presigned URLs work for buckets outside us-east-1.
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=f"https://s3.{settings.aws_region}.amazonaws.com",
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )


@lru_cache
def bedrock():
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.bedrock_region,
        config=Config(read_timeout=300, max_pool_connections=32, retries={"max_attempts": 2, "mode": "standard"}),
    )


@lru_cache
def s3vectors():
    return boto3.client("s3vectors", region_name=settings.aws_region)


@lru_cache
def cognito():
    return boto3.client("cognito-idp", region_name=settings.aws_region)
