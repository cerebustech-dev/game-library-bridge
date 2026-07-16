from game_library_bridge.models import epoch_to_iso, normalize_title


def test_normalize_strips_trademarks_and_punctuation():
    assert normalize_title("Mass Effect™ Legendary Edition") == "mass effect legendary edition"
    assert normalize_title("Half-Life 2: Deathmatch") == "half life 2 deathmatch"


def test_normalize_folds_ampersand_and_case():
    assert normalize_title("Dungeons & Dragons") == normalize_title("dungeons and dragons")


def test_normalize_collapses_whitespace_and_unicode():
    assert normalize_title("  Café   Simulator  ") == "cafe simulator"


def test_epoch_to_iso():
    assert epoch_to_iso(1784072808) == "2026-07-14T23:46:48Z"
    assert epoch_to_iso(None) is None
