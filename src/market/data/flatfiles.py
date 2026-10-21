"""Polygon (Massive) flat files over S3: list, probe and stream daily CSV.gz files.

Files are streamed into pandas and discarded — nothing raw is kept on disk (PLAN §4).
"""

from __future__ import annotations

import gzip
import io
import time
from datetime import date
from functools import lru_cache

import boto3
import pandas as pd
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError, ResponseStreamingError

from market.config import config, s3_credentials

DATASETS = {
    "stocks_day": "us_stocks_sip/day_aggs_v1",
    "options_day": "us_options_opra/day_aggs_v1",
}


def available() -> bool:
    return s3_credentials() is not None


@lru_cache(maxsize=1)
def _client():
    cfg = config()["polygon"]
    credentials = s3_credentials()
    if credentials is None:
        raise RuntimeError("Flat-file credentials missing: set MASSIVE_API_KEY_ID and MASSIVE_API_KEY in .env")
    return boto3.Session(aws_access_key_id=credentials[0], aws_secret_access_key=credentials[1]).client(
        "s3",
        endpoint_url=cfg["flatfiles_endpoint"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 4}),
    )


def key_for(dataset: str, session: date) -> str:
    return f"{DATASETS[dataset]}/{session:%Y}/{session:%m}/{session:%Y-%m-%d}.csv.gz"


def head(dataset: str, session: date) -> int | None:
    """Compressed size in bytes, or None if the file is missing or not entitled."""
    try:
        meta = _client().head_object(Bucket=config()["polygon"]["flatfiles_bucket"], Key=key_for(dataset, session))
    except ClientError:
        return None
    return int(meta["ContentLength"])


READ_ATTEMPTS = 4


def read_day(dataset: str, session: date) -> tuple[pd.DataFrame, int]:
    """Download one day's file into memory and parse it. Returns (frame, compressed_bytes).

    botocore retries the request but not a body read that stalls mid-stream, so that is retried here.
    """
    for attempt in range(READ_ATTEMPTS):
        try:
            obj = _client().get_object(Bucket=config()["polygon"]["flatfiles_bucket"], Key=key_for(dataset, session))
            raw = obj["Body"].read()
            break
        except (ReadTimeoutError, ResponseStreamingError, EndpointConnectionError):
            if attempt == READ_ATTEMPTS - 1:
                raise
            time.sleep(2 * (attempt + 1))
    with gzip.open(io.BytesIO(raw)) as handle:
        frame = pd.read_csv(handle, dtype={"ticker": "string"})
    return frame, len(raw)
