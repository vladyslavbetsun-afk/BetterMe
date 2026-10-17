import pytest

from decay.priority import confidence, install_intent, priority


@pytest.mark.parametrize("kw,want", [
    ("wall pilates workout plan", "HIGH"),
    ("28 day wall pilates challenge", "HIGH"),
    ("chair yoga for beginners", "HIGH"),
    ("benefits of wall pilates", "MEDIUM"),
    ("is intermittent fasting safe", "MEDIUM"),
    ("what is calisthenics", "LOW"),
    ("does wall pilates work", "LOW"),
    ("how many calories does walking burn", "LOW"),
])
def test_install_intent(kw, want):
    assert install_intent(kw) == want


def test_commercial_intent_lifts_to_high():
    assert install_intent("pilates mat", commercial=True) == "HIGH"


def test_priority_formula(cfg):
    # 400 lost x HIGH 1.5 x core 1.3 x confirmed 1.0 x L1 1.2
    assert priority(cfg, 400, "HIGH", True, 1.0, "L1") == pytest.approx(400 * 1.5 * 1.3 * 1.0 * 1.2)
    # 400 x LOW 0.6 x non-core 1.0 x watch 0.5 x L3 0.7
    assert priority(cfg, 400, "LOW", False, 0.5, "L3") == pytest.approx(400 * 0.6 * 0.5 * 0.7)
    assert priority(cfg, 400, "MEDIUM", False, 1.0, "NOSEO") == 0


def test_confidence(cfg):
    assert confidence(cfg, True, None) == (1.0, None)
    assert confidence(cfg, False, None) == (0.5, None)
    assert confidence(cfg, True, -30)[0] == pytest.approx(1.2)
    value, note = confidence(cfg, True, 4)
    assert value == pytest.approx(0.7) and note == "Ahrefs shows a drop, GSC clicks stable"
