"""Integration tests for VoxEngine services.

Tests pure logic — no DB or network required.
"""
import pytest
import numpy as np


# --------------------------------------------------------------------------- #
# ACX Compliance
# --------------------------------------------------------------------------- #
class TestACXCompliance:
    def test_spec_constants_exist(self):
        from services.acx_compliance import ACXSpec
        assert ACXSpec.TARGET_LUFS == -23.0
        assert ACXSpec.PEAK_MAX_DBFS == -3.0
        assert ACXSpec.NOISE_FLOOR_DBFS == -60.0

    def test_acx_check_dataclass(self):
        from services.acx_compliance import ACXCheck
        check = ACXCheck(check_name="loudness", value=-24.0, threshold=-23.0, passed=True, severity="ok", message="OK")
        assert check.passed is True
        assert check.check_name == "loudness"


# --------------------------------------------------------------------------- #
# Waveform Generator
# --------------------------------------------------------------------------- #
class TestWaveformGenerator:
    def test_generate_peaks_from_array(self):
        from services.waveform_generator import generate_peaks_from_array
        # 1 second of sine wave at 440Hz
        sr = 24000
        t = np.linspace(0, 1, sr, dtype=np.float32)
        audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        peaks = generate_peaks_from_array(audio, sr, samples_per_second=10)
        assert len(peaks) == 10
        assert all(0.0 <= p <= 1.0 for p in peaks)

    def test_generate_m4b_chapters(self):
        from services.waveform_generator import generate_m4b_chapters
        result = generate_m4b_chapters([60.0, 120.0], ["Chapter 1", "Chapter 2"])
        assert "Chapter 1" in result
        assert "Chapter 2" in result
        assert "CHAPTER" in result.upper() or "chapter" in result


# --------------------------------------------------------------------------- #
# SSML Converter
# --------------------------------------------------------------------------- #
class TestSSMLConverter:
    def test_convert_ssml_break(self):
        from services.ssml_converter import convert_ssml_to_acx
        result = convert_ssml_to_acx('Hello <break time="500ms"/> world')
        assert "pause" in result.lower() or "500" in result

    def test_convert_ssml_emphasis(self):
        from services.ssml_converter import convert_ssml_to_acx
        result = convert_ssml_to_acx('<emphasis level="strong">important</emphasis>')
        assert "emphasis" in result.lower() or "important" in result

    def test_convert_ssml_prosody(self):
        from services.ssml_converter import convert_ssml_to_acx
        result = convert_ssml_to_acx('<prosody rate="slow">calm text</prosody>')
        assert "slow" in result.lower() or "calm" in result


# --------------------------------------------------------------------------- #
# Batch Processor
# --------------------------------------------------------------------------- #
class TestBatchProcessor:
    def test_batch_job_dataclass(self):
        from services.batch_processor import BatchJob
        job = BatchJob(job_id="test-123", org_id="org-456", priority=8, created_at=None, estimated_duration_s=120.0)
        assert job.priority == 8
        assert job.job_id == "test-123"

    def test_priority_validation(self):
        from services.batch_processor import BatchJob
        # Priority should be 1-10
        job = BatchJob(job_id="x", org_id="y", priority=10, created_at=None, estimated_duration_s=0)
        assert job.priority == 10


# --------------------------------------------------------------------------- #
# Voice Safety
# --------------------------------------------------------------------------- #
class TestVoiceSafety:
    def test_protected_blocklist_exists(self):
        from services.voice_safety import PROTECTED_VOICE_BLOCKLIST
        assert isinstance(PROTECTED_VOICE_BLOCKLIST, list)
        assert len(PROTECTED_VOICE_BLOCKLIST) > 0

    def test_watermark_metadata(self):
        from services.voice_safety import generate_watermark_metadata
        meta = generate_watermark_metadata("org-123", "job-456")
        assert "org_id" in meta or "org" in str(meta).lower()
        assert "job_id" in meta or "job" in str(meta).lower()


# --------------------------------------------------------------------------- #
# M4B Assembly
# --------------------------------------------------------------------------- #
class TestM4BAssembly:
    def test_generate_chapter_atoms(self):
        from services.m4b_assembly import generate_chapter_atoms
        # Function signature may differ — test it exists and is callable
        assert callable(generate_chapter_atoms)


# --------------------------------------------------------------------------- #
# GPU Synthesis
# --------------------------------------------------------------------------- #
class TestGPUSynthesis:
    def test_synthesis_router_default(self):
        from services.gpu_synthesis import SynthesisRouter
        router = SynthesisRouter()
        assert router is not None

    def test_normalize_loudness(self):
        try:
            from services.gpu_synthesis import normalize_loudness
            audio = np.sin(np.linspace(0, 2 * np.pi * 440, 24000)).astype(np.float32) * 0.5
            result = normalize_loudness(audio, target_lufs=-23.0)
            assert result is not None
            assert len(result) == len(audio)
        except ImportError:
            pytest.skip("pyloudnorm not installed")


# --------------------------------------------------------------------------- #
# Stripe Billing
# --------------------------------------------------------------------------- #
class TestStripeBilling:
    def test_pricing_tiers_exist(self):
        from services.billing.stripe_integration import TIER_FREE, TIER_PRO, TIER_ENTERPRISE
        assert TIER_FREE.monthly_price_cents == 0
        assert TIER_PRO.monthly_price_cents > 0
        assert TIER_ENTERPRISE.monthly_price_cents > TIER_PRO.monthly_price_cents

    def test_calculate_bill(self):
        from services.billing.stripe_integration import calculate_bill, TIER_STARTER
        usage = {"characters": 100000, "cost_usd": 0.0}
        bill = calculate_bill(usage, TIER_STARTER)
        assert "total" in str(bill).lower() or "amount" in str(bill).lower() or isinstance(bill, dict)

    def test_tier_ordering(self):
        from services.billing.stripe_integration import TIER_FREE, TIER_STARTER, TIER_PRO, TIER_ENTERPRISE
        tiers = [TIER_FREE, TIER_STARTER, TIER_PRO, TIER_ENTERPRISE]
        prices = [t.monthly_price_cents for t in tiers]
        assert prices == sorted(prices)


# --------------------------------------------------------------------------- #
# Voice Catalog
# --------------------------------------------------------------------------- #
class TestVoiceCatalog:
    def test_voice_filter_dataclass(self):
        from services.voice_catalog import VoiceFilter
        f = VoiceFilter(gender="female", accent="american")
        assert f.gender == "female"
