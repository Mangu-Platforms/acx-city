"""Built-in audition scripts for the Voice City audition room.

Every script is an original text written for this platform (no excerpts from
published works), purpose-built to stress one delivery category: sustained
narration, quotation-heavy dialogue, dense figures and acronyms, phonetically
tricky invented names, and so on.  Scripts are intentionally short (roughly
60-120 words) so a preview stays cheap to synthesize while still exposing how
a voice handles the category.

Consumed by ``voice_city/api.py``:

* ``GET /api/voice-city/audition-scripts`` returns ``AUDITION_SCRIPTS``
  (optionally filtered by the ``category`` query parameter, compared against
  each script's ``category`` field).
* Preview endpoints resolve a requested ``script_id`` through
  :func:`get_audition_script`.
"""
from __future__ import annotations

from typing import Any

#: Canonical category identifiers, in display order.  The API filters with an
#: exact string match against these values.
SCRIPT_CATEGORIES: list[str] = [
    "fiction",
    "nonfiction",
    "dialogue",
    "technical",
    "legal",
    "emotional",
    "advertising",
    "children",
    "difficult-names",
    "numbers-acronyms",
]


def _script(script_id: str, category: str, title: str, description: str, text: str) -> dict[str, Any]:
    """Build one canonical script record.

    ``word_count`` is computed from the text so it can never drift, and the
    stored ``text`` is whitespace-normalized for stable content hashing.
    """
    normalized = " ".join(text.split())
    return {
        "id": script_id,
        "category": category,
        "title": title,
        "description": description,
        "text": normalized,
        "word_count": len(normalized.split()),
    }


AUDITION_SCRIPTS: list[dict[str, Any]] = [
    # ------------------------------------------------------------------
    # Fiction: sustained third-person narration, imagery, varied cadence.
    # ------------------------------------------------------------------
    _script(
        "fiction-glass-harbor",
        "fiction",
        "The Glass Harbor",
        "Literary narration with long, flowing sentences, imagery, and a quiet turn at the end.",
        """
        The harbor turned to glass an hour before dawn, the way it always did when the
        wind forgot itself. Mara stood at the rail and counted the masts, thirty-one of
        them, each one holding a sliver of moon. Somewhere below deck a kettle began to
        sing. She thought of her father's maps, inked in a hand steadier than his voice
        had ever been, and of the one blank stretch of coastline he refused to name. The
        tide shifted. The glass broke into a thousand moving pieces, and the first gull
        of morning called the town awake.
        """,
    ),
    _script(
        "fiction-ash-and-orchard",
        "fiction",
        "Ash and Orchard",
        "Slower, reflective narration that rewards restraint, warmth, and careful pacing.",
        """
        No one returned to the orchard after the fire, though the trees kept their
        appointment with spring. Blossom came up through the char like a rumor no one
        dared repeat. Old Tamsin watched from the lane, basket empty, boots grey to the
        ankle. If grief had a season, she thought, it would smell like this: sweet, and
        burnt, and stubborn. She stepped over the fallen gate. By June there would be
        fruit, and someone would have to decide whether eating it was mourning or
        forgiveness.
        """,
    ),
    # ------------------------------------------------------------------
    # Nonfiction: explanatory prose, steady authority, clause management.
    # ------------------------------------------------------------------
    _script(
        "nonfiction-lighthouse-rhythm",
        "nonfiction",
        "How Lighthouses Learned to Blink",
        "Explanatory nonfiction that tests steady authority, semicolon-like pauses, and list delivery.",
        """
        For most of history, the hardest problem in lighthouse design was not brightness
        but identity. A sailor glimpsing a light at midnight needed to know which light
        it was, and a steady flame off one headland looks exactly like a steady flame
        off another. The solution was rhythm. Engineers gave each tower a signature: two
        flashes, then darkness; a long beam, a pause, a short one. Charts began listing
        lights the way songbooks list melodies. Navigation became, in a quiet way, an
        act of listening with the eyes, and coastlines learned to introduce themselves.
        """,
    ),
    # ------------------------------------------------------------------
    # Dialogue: attribution tags, speaker changes, questions, interruptions.
    # ------------------------------------------------------------------
    _script(
        "dialogue-late-train",
        "dialogue",
        "The Late Train",
        "Two-speaker exchange full of attribution tags, questions, and an interrupted line.",
        """
        "You're certain the train stops here?" asked Petra, setting down her case.
        "Stopped here every night for forty years," said Joris. "Though 'stops' is
        generous. It hesitates." "And if it doesn't hesitate tonight?" "Then you'll want
        the bench with the view." He folded his newspaper. "Listen. There's the whistle
        now. No, wait. That's the kettle in the signal box." Petra laughed despite
        herself. "Is everything here a kettle?" "Everything that matters," Joris said.
        "Sit down. When it comes, it comes quietly, and it never waits."
        """,
    ),
    _script(
        "dialogue-kitchen-terms",
        "dialogue",
        "Terms of the Kitchen",
        "Playful back-and-forth that stresses quick speaker turns and dry comic timing.",
        """
        "Don't open the oven," Ruth warned, without turning around. "I was only going to
        look." "Looking lets the heat out, and the heat is the whole argument." Malcolm
        leaned against the counter. "You sound like your mother." "My mother never
        burned a souffle in her life." "That's not how she tells it." Ruth pointed the
        wooden spoon at him, a duelist accepting terms. "Set the table, tell no stories,
        and you may have the first slice." "Deal," he said, and struck a match for the
        candles.
        """,
    ),
    # ------------------------------------------------------------------
    # Technical: imperative steps, jargon, precision without monotony.
    # ------------------------------------------------------------------
    _script(
        "technical-restore-procedure",
        "technical",
        "Restoring From Backup",
        "Step-by-step technical instructions that test clarity, evenness, and jargon handling.",
        """
        Before restoring from backup, verify that the archive is intact. Run the
        checksum utility against the manifest and confirm that every segment reports a
        match. Next, stop the ingestion service so no new writes arrive during the
        restore window. Mount the recovery volume as read-only, copy the snapshot
        directory to local storage, and only then remount with write access. If the
        schema version in the snapshot is older than the running database, apply each
        migration in order, never in parallel. Finally, restart the service and tail the
        log until the first heartbeat appears.
        """,
    ),
    # ------------------------------------------------------------------
    # Legal: long subordinate clauses, formal register, provisos.
    # ------------------------------------------------------------------
    _script(
        "legal-notice-clause",
        "legal",
        "Delivery of Notice",
        "Contract language with stacked clauses and provisos; tests formal register and breath control.",
        """
        Notice under this agreement shall be deemed delivered upon the earliest of three
        events: personal delivery to the receiving party; confirmed electronic
        transmission to the address designated in Schedule B; or the third business day
        after deposit with a recognized courier, postage prepaid. Failure of a party to
        maintain a current address shall not excuse performance. Where a deadline falls
        on a public holiday, the obligation extends to the next business day, provided,
        however, that no extension shall exceed five days in aggregate without the prior
        written consent of both parties.
        """,
    ),
    # ------------------------------------------------------------------
    # Emotional: grief and joy, restraint versus release.
    # ------------------------------------------------------------------
    _script(
        "emotional-empty-chair",
        "emotional",
        "The Empty Chair",
        "Quiet grief that rewards restraint, softness, and space between phrases.",
        """
        The chair still faces the window, because moving it felt like an announcement
        she wasn't ready to make. Some mornings she pours two cups before she remembers,
        and the kitchen holds its breath while she stands there, kettle in hand,
        deciding whether to laugh or break. Today she carried both cups out to the
        garden and gave one to the roses. It isn't forgetting, she told them. It is
        learning to set a table for what remains.
        """,
    ),
    _script(
        "emotional-acceptance-letter",
        "emotional",
        "The Acceptance Letter",
        "Rising excitement and outright joy; tests energy, acceleration, and exclamations.",
        """
        The envelope was too thin to mean anything good. Everyone said so. And yet her
        name on the front was written like a door opening. She read the first line on
        the porch, the second on the stairs, and the third at a full sprint through the
        kitchen, waving the page like a flag. We got in! she shouted, to her brother, to
        the dog, to the astonished mailman still standing at the gate. We got in, we got
        in, we got in!
        """,
    ),
    # ------------------------------------------------------------------
    # Advertising: punchy copy, brand emphasis, a call to action.
    # ------------------------------------------------------------------
    _script(
        "advertising-northlight-roast",
        "advertising",
        "Northlight Roast",
        "Upbeat commercial read with short punchy sentences, brand emphasis, and a closing tagline.",
        """
        Some mornings need a headline. Introducing Northlight Roast, a coffee that shows
        up like good news and stays like an old friend. We source small, roast slow, and
        ship within the week, because fresh isn't a buzzword. It's a deadline. Try the
        sampler trio: bright, balanced, and boldly dark. Your first bag ships free, and
        your Tuesday will never see it coming. Northlight Roast. Pour the day some
        courage.
        """,
    ),
    # ------------------------------------------------------------------
    # Children: playful rhythm, repetition, big friendly dynamics.
    # ------------------------------------------------------------------
    _script(
        "children-snail-picnic",
        "children",
        "The Snail Who Was Late",
        "Bouncy read-aloud story with repetition, sound effects, and a cheerful ending.",
        """
        Sim the snail was late again. Not a little late. A lot late! The picnic started
        at noon, and noon had packed up and gone home hours ago. Hurry, hurry! called
        the beetles. Zoom, zoom! buzzed the bees. But Sim just smiled his slow, silvery
        smile. I am hurrying, he said. This is what hurrying looks like. And when he
        finally arrived, under the biggest moon you ever saw, he brought the one thing
        everyone had forgotten: the strawberry jam. Hooray for Sim!
        """,
    ),
    # ------------------------------------------------------------------
    # Difficult names: phonetically tricky invented people and places.
    # ------------------------------------------------------------------
    _script(
        "difficult-names-roll-call",
        "difficult-names",
        "Roll Call at Thornwick Academy",
        "A register of invented, phonetically demanding personal names delivered in sequence.",
        """
        The register at Thornwick Academy read like a pronunciation exam. Ms. Alderquist
        began bravely. Aoibheann Szymczak answered from the front row. Behind her sat
        Dziugas Featherstonehaugh, who preferred simply Dz. Then came Siobhan Ngata,
        Xiulan Krzyzewski, and the twins, Eoghan and Caoimhe Postlethwaite. A new name
        had been added in pencil: Tzipporah Oyelaran, transferred from the coast. Ms.
        Alderquist took a breath, trusted her vowels, and by the second week she could
        summon every one of them without once looking down at the page.
        """,
    ),
    _script(
        "difficult-names-gazetteer",
        "difficult-names",
        "The Cartographer's Gazetteer",
        "Invented place names with consonant clusters and unusual vowel runs.",
        """
        The gazetteer listed every town the empire had misplaced. Ylgrathune, where the
        cliffs sang in wet weather. Pwyllcaster and its seven unpronounceable bridges.
        Tsoukalithi, an island that appeared on alternate Tuesdays. The twin ports of
        Schravenmoere and Skjaldvik, forever disputing a hyphen. Quenhessaly,
        Mbwenzurro, and the mountain shrine of Dhrupathaan, reachable only by argument.
        The cartographer read each name aloud twice, once as written and once as the
        locals insisted, and recorded both, because a map that cannot be spoken is only
        a picture.
        """,
    ),
    # ------------------------------------------------------------------
    # Numbers and acronyms: figures, dates, currency, initialisms.
    # ------------------------------------------------------------------
    _script(
        "numbers-quarterly-briefing",
        "numbers-acronyms",
        "Quarterly Briefing",
        "Dense financial figures, percentages, dates, and corporate acronyms.",
        """
        The Q3 report landed on October 14, 2025, at 9:45 a.m., and the numbers spoke
        first. Revenue reached $12,480,000, up 18.6 percent year over year, while churn
        fell to 2.3 percent. The API division processed 4,700,000,000 requests, roughly
        1,509 per second, with 99.98 percent uptime. Headcount grew from 212 to 268,
        including 31 engineers and 14 in QA. The CFO flagged three dates: November 3 for
        the audit, December 1 for the SOC 2 review, and January 15, 2026, for the IPO
        readiness check with the SEC and NYSE.
        """,
    ),
    _script(
        "numbers-mission-countdown",
        "numbers-acronyms",
        "Mission Countdown",
        "Times, units, version numbers, agency acronyms, and a spoken countdown.",
        """
        T-minus 10 minutes. The AURIGA-7 probe, all 3,214 kilograms of her, sat atop
        490,000 liters of fuel. Launch window: 06:32 to 06:47 UTC, February 29, 2028.
        Flight computer v4.1.9 reported nominal; the backup battery held 98.5 percent.
        NASA, ESA, and JAXA shared the loop, with the FAA and NOAA watching weather cell
        14B. Downrange stations at kilometers 250, 1,100, and 3,750 confirmed lock. At
        T-minus 8 seconds the count went manual: eight, seven, six, five, four, three,
        two, one. Ignition.
        """,
    ),
]

#: Fast lookup by script id.
_SCRIPTS_BY_ID: dict[str, dict[str, Any]] = {script["id"]: script for script in AUDITION_SCRIPTS}


def get_audition_script(script_id: str) -> dict[str, Any] | None:
    """Return the audition script with ``script_id``, or ``None`` if unknown.

    A shallow copy is returned so callers can annotate the record without
    mutating the module-level catalog.
    """
    script = _SCRIPTS_BY_ID.get(str(script_id))
    return dict(script) if script is not None else None
