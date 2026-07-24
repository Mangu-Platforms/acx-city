import os
from dotenv import load_dotenv

load_dotenv()


class AWSConfig:
    """Optional AWS configuration. The app runs fine without any AWS setup —
    the Polly provider simply reports itself unavailable."""

    def __init__(self):
        self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        self.region_name = os.getenv("AWS_REGION", "us-east-1")
        self.s3_bucket = os.getenv("S3_BUCKET_NAME")

    @property
    def configured(self) -> bool:
        return bool(self.aws_access_key_id and self.aws_secret_access_key)

    def get_polly_client(self):
        import boto3

        return boto3.client(
            "polly",
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.region_name,
        )

    def get_s3_client(self):
        import boto3

        return boto3.client(
            "s3",
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.region_name,
        )


aws_config = AWSConfig()
