"""AWS Polly adapter. Only active when AWS credentials are configured."""
import os
from typing import Dict, List, Optional

from .base import SpeechProvider


class PollyProvider(SpeechProvider):
    name = "polly"
    display_name = "AWS Polly"
    max_chars = 2900  # Polly sync limit is 3000; keep headroom
    paid = True
    cost_per_million_chars = 16.0  # AWS Polly neural list price, approx USD/1M chars

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "polly",
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                region_name=os.getenv("AWS_REGION", "us-east-1"),
            )
        return self._client

    def is_available(self) -> bool:
        return bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))

    def list_voices(self, language: Optional[str] = None) -> List[Dict]:
        if not self.is_available():
            return []
        kwargs = {"LanguageCode": language} if language else {}
        try:
            response = self._get_client().describe_voices(**kwargs)
        except Exception as e:  # noqa: BLE001
            print(f"[polly] error listing voices: {e}")
            return []
        return [
            {
                "id": v.get("Id"),
                "name": v.get("Name"),
                "language": v.get("LanguageCode"),
                "gender": v.get("Gender"),
                "neural": "neural" in v.get("SupportedEngines", []),
            }
            for v in response.get("Voices", [])
        ]

    def synthesize(self, text: str, voice_id: str, engine: str = "neural") -> bytes:
        response = self._get_client().synthesize_speech(
            Text=text,
            VoiceId=voice_id,
            Engine=engine,
            OutputFormat="mp3",
            TextType="text",
        )
        return response["AudioStream"].read()
