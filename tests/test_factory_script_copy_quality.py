"""Prevent the live QA failure: a word budget must not cut a sentence."""
from modules.factory.autorun import scripts
from modules.factory.autorun.service import AutoRunService
from test_factory_autorun import application, stack, make_seed, launch, autorun, SCRIPT, scripted_transport
import copy
import json
import pytest


def sample():
    beats = [{"id": "b1", "role": "body", "start_s": 0, "end_s": 4}]
    base = {"A": {"b1": ""}, "B": {"b1": ""}, "C": {"b1": ""},
            "D": {"b1": ""}, "changed": dict.fromkeys("BCD", "b1"),
            "factors": scripts.FACTORS, "metrics": scripts.METRICS,
            "hypotheses": {}}
    llm = {"variants": {"A": {"b1": ""}, "B": {"b1": "Watch this chicken."},
                       "C": {"b1": "And here, a chicken curiously watches as butter is spread in a frying pan nearby."},
                       "D": {"b1": "Watch that again."}}}
    return beats, base, llm


def test_overlong_sentence_requires_rewrite_instead_of_mid_sentence_truncation():
    beats, base, llm = sample()
    merged, notices = AutoRunService.__new__(AutoRunService)._merge_llm_scripts(base, llm, beats)
    assert merged is None
    assert any(n[-1] == "rewrite_required" for n in notices)


def test_complete_short_sentence_can_be_retained_without_word_cutting():
    beats, base, llm = sample()
    llm["variants"]["C"]["b1"] = "The chicken watches the butter. " + "Additional explanation " * 10
    merged, _ = AutoRunService.__new__(AutoRunService)._merge_llm_scripts(base, llm, beats)
    assert merged["C"]["b1"] == "The chicken watches the butter."


def test_script_request_declares_per_beat_word_budgets():
    beats, base, _ = sample()
    request = scripts.llm_request("model", beats, [], base["A"], base["changed"])
    assert request["script_input"]["beats"][0]["max_words"] == scripts.word_budget(beats[0], "")


def test_malformed_script_stays_paused_without_draft_speech_or_unknown_replay(application):
    from test_factory_autorun import drive
    bad = copy.deepcopy(SCRIPT)
    bad['variants']['C'] = None
    s, _, act, worker, root = stack(application, script_result=bad)
    run = launch(act, make_seed(act, root), generate_music=False)
    drive(s,worker)
    first = autorun(s, run['id'])
    assert first.status == 'paused' and first.stage == 'script'
    assert not first.state.get('script_llm_failed'), 'Malformed future scripts must not select a fallback on Resume'
    assert not first.experiment_id and not first.state.get('tts_jobs')
    job = first.state['script_jobs'][0]
    count = s.db.conn.execute('SELECT count(*) FROM attempts WHERE job_id=?',(job,)).fetchone()[0]
    resumed = act('post',f'/api/autoruns/{run["id"]}/resume',{})
    assert resumed.status_code == 200, resumed.text
    drive(s,worker)
    final = autorun(s,run['id'])
    assert final.status == 'paused' and final.stage == 'script'
    assert not final.experiment_id and not final.state.get('tts_jobs')
    assert s.db.conn.execute('SELECT count(*) FROM attempts WHERE job_id=?',(job,)).fetchone()[0] == count


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_script_rewrite_is_bounded_durable_and_before_tts(application, repair_succeeds):
    s, _, act, worker, root = stack(application)
    provider = s.providers["audiovisual_analysis"]
    original = provider.transport
    calls = []
    # Make the deterministic C fallback unavailable, reproducing a silent
    # source beat whose newly narrated line must be rewritten, not dropped.
    original_adapt = scripts.adapt
    from unittest.mock import patch
    def adapt(*args):
        base = original_adapt(*args)
        base["A"]["b1"] = ""
        base["C"]["b1"] = ""
        return base
    def transport(method, url, payload, headers):
        text = json.loads(payload)["contents"][0]["parts"][0].get("text", "")
        if "split test" not in text:
            return original(method, url, payload, headers)
        calls.append(text)
        script = copy.deepcopy(SCRIPT)
        script["variants"]["A"]["b1"] = ""
        if not (repair_succeeds and '"rewrite_feedback":' in text):
            script["variants"]["C"]["b1"] = "And here a dog curiously watches as someone carefully places the ball in a bowl"
        return scripted_transport({"script": script})(method, url, payload, headers)
    provider.transport = transport
    with patch.object(scripts, "adapt", side_effect=adapt):
        run = launch(act, make_seed(act, root))
        for _ in range(100):
            if worker.tick() is None:
                from datetime import timedelta
                future = s.scheduler.clock() + timedelta(seconds=5)
                s.scheduler.clock = lambda: future
            current = autorun(s, run["id"])
            if (current.stage != "script" and current.state.get("scripts")) or current.status == "paused":
                break
    assert len(calls) == 2
    assert "rewrite_feedback" in calls[1]
    assert "script_repair_jobs" in current.state
    if repair_succeeds:
        assert current.state["scripts"]["C"]["b1"] == SCRIPT["variants"]["C"]["b1"]
    else:
        assert current.pause["code"] == "script_repair_failed"
        assert not current.state.get("tts_jobs")
