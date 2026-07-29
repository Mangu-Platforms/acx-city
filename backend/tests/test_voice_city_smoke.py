"""End-to-end smoke tests for the Voice City studio API.

These intentionally exercise the full HTTP surface (auth, org scoping,
generation, candidate acceptance, versioning, presets, pronunciation,
safety screening) against the real service stack. Preview rendering is
excluded because it requires a live TTS provider connection.
"""


def _post(client, headers, url, payload):
    response = client.post(url, json=payload, headers=headers)
    assert response.status_code in (200, 201), f"{url}: {response.status_code} {response.get_json()}"
    return response.get_json()


def test_voice_city_capabilities_schema_and_scripts(client, auth_headers):
    headers, _org = auth_headers()
    caps = client.get("/api/voice-city/capabilities", headers=headers).get_json()
    assert caps["voice_cloning"] is False
    assert caps["reference_voice_creation"] is False
    assert caps["synthetic_voice_creation"] is True
    schema = client.get("/api/voice-city/schema?mode=laboratory", headers=headers).get_json()
    assert len(schema["groups"]) == 12, "soundboard architecture is twelve groups"
    assert len(schema["controls"]) >= 200, f"laboratory mode should expose the full surface, got {len(schema['controls'])}"
    scripts = client.get("/api/voice-city/audition-scripts", headers=headers).get_json()
    assert {s["category"] for s in scripts} >= {"fiction", "dialogue", "numbers-acronyms"}


def test_generate_accept_version_and_recipe_roundtrip(client, auth_headers):
    headers, _org = auth_headers()
    result = _post(client, headers, "/api/voice-city/generate", {
        "description": "warm middle-aged British female narrator, unhurried, slightly husky",
        "count": 4, "seed": 20260729,
    })
    candidates = result["candidates"]
    assert len(candidates) == 4
    assert all(c["status"] == "candidate" for c in candidates)

    # Determinism: same request → same fingerprints.
    rerun = _post(client, headers, "/api/voice-city/generate", {
        "description": "warm middle-aged British female narrator, unhurried, slightly husky",
        "count": 4, "seed": 20260729,
    })
    assert [c["fingerprint"] for c in rerun["candidates"]] == [c["fingerprint"] for c in candidates]

    accepted = _post(client, headers, f"/api/voice-city/candidates/{candidates[0]['id']}/accept",
                     {"name": "Test Narrator"})
    voice_id = accepted["voice"]["id"] if "voice" in accepted else accepted["id"]
    voice = client.get(f"/api/voice-city/voices/{voice_id}", headers=headers).get_json()
    assert voice["current_version"]["status"] in ("ready", "draft")
    assert voice["safety_classification"] == "synthetic-no-reference-audio"

    recipe = client.get(f"/api/voice-city/voices/{voice_id}/export", headers=headers)
    assert recipe.status_code == 200


def test_identity_imitation_prompts_blocked(client, auth_headers):
    headers, _org = auth_headers()
    response = client.post("/api/voice-city/generate", json={
        "description": "make it sound exactly like Morgan Freeman", "count": 2,
    }, headers=headers)
    assert response.status_code == 400


def test_presets_and_pronunciation_rules(client, auth_headers):
    headers, _org = auth_headers()
    presets = client.get("/api/voice-city/presets", headers=headers).get_json()
    assert any(str(p.get("id", "")).startswith("system:") for p in presets)

    rule = _post(client, headers, "/api/voice-city/pronunciations", {
        "pattern": "Mangu", "replacement": "MAHN-goo", "rule_type": "literal",
    })
    assert rule["pattern"] == "Mangu"
    bad = client.post("/api/voice-city/pronunciations", json={
        "pattern": "", "replacement": "x",
    }, headers=headers)
    assert bad.status_code == 400


def test_org_isolation(client, auth_headers):
    headers_a, _org_a = auth_headers()
    result = _post(client, headers_a, "/api/voice-city/generate",
                   {"description": "bright young announcer", "count": 1})
    body = client.post("/api/auth/signup", json={
        "email": "second-org@example.com", "password": "password-123",
    }).get_json()
    headers_b = {"Authorization": f"Bearer {body['token']}"}
    stolen = client.get(
        f"/api/voice-city/candidate-sets/{result['candidate_set_id']}", headers=headers_b)
    assert stolen.status_code in (400, 403, 404)
