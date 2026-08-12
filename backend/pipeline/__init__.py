"""VoxEngine multi-agent preprocessing pipeline.

Five agents (structure parser, character attribution, text normalizer,
prosody planner, QA validator) transform raw manuscript text into tagged,
synthesis-ready scripts.

The pipeline runs synchronously inside the existing worker via
pipeline.integration.preprocess_chapter_pipeline — see that module. The
former Celery/Redis task fabric was deleted in P1.2: it duplicated the
worker path against a broker that does not exist in the deployed topology.
"""
