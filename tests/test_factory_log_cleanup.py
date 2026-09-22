import stat
import pytest


def test_cleanup_is_dry_by_default_and_redacts_without_backups(tmp_path):
    from modules.factory.operations.log_privacy import sanitize_log
    p = tmp_path / 'program.log'
    p.write_text('GET /?code=sensitive&state=private HTTP/1.1 404\nordinary failure\n')
    preview = sanitize_log(p)
    assert preview['changed_lines'] == 1
    assert 'sensitive' in p.read_text()
    with pytest.raises(RuntimeError, match='writer'):
        sanitize_log(p, apply=True)
    sanitize_log(p, apply=True, writer_stopped=True)
    assert 'sensitive' not in p.read_text() and 'ordinary failure' in p.read_text()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [p]


def test_redaction_preserves_normal_questions_and_url_paths():
    from modules.factory.events.redact import redact_log as redact
    assert redact('Are you serious? Keep this!') == 'Are you serious? Keep this!'
    assert redact('GET /callback?code=secret HTTP/1.1') == 'GET /callback?[redacted] HTTP/1.1'


def test_non_secret_domain_url_remains_usable():
    from modules.factory.events.redact import redact
    assert redact('https://www.youtube.com/watch?v=abcdefghijk') == 'https://www.youtube.com/watch?v=abcdefghijk'
    assert redact('Use discount code: SAVE20') == 'Use discount code: SAVE20'


@pytest.mark.parametrize('line', [
    'https://private-user:private-pass@example.test/path',
    "{'client_secret': 'private-secret'}",
    'Authorization: Basic private-credentials',
    'Cookie: session=private-cookie; csrf=private-csrf',
])
def test_log_credentials_are_removed_outside_query_strings(line):
    from modules.factory.events.redact import redact_log
    assert 'private-' not in redact_log(line)


def test_sanitized_legacy_archive_keeps_context_not_credentials(tmp_path):
    import gzip
    from modules.factory.operations.log_privacy import sanitize_log
    path, archive = tmp_path/'api.log', tmp_path/'api-legacy.log.gz'
    path.write_text('GET /?code=secret HTTP/1.1 404\nold diagnosis\n')
    sanitize_log(path, apply=True, writer_stopped=True, archive_to=archive)
    assert path.read_text() == ''
    with gzip.open(archive,'rt') as source: text=source.read()
    assert 'secret' not in text and 'old diagnosis' in text
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
