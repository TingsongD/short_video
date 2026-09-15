"""Credential source selection, using fake values and no network."""
import os

import pytest

from modules.common import config


@pytest.fixture
def private_config(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "secrets.toml").write_text(
        'ELEVENLABS_API_KEY = "toml-test-value"\nLLM_MODEL = "saved-model"\n'
    )
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "CONFIG_DIR", directory)
    for name in config.GOOGLE_SETTINGS | {"ELEVENLABS_API_KEY", "LLM_MODEL", "TEST_VALUE"}:
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_existing_toml_works_without_dotenv(private_config):
    assert config.secrets()["ELEVENLABS_API_KEY"] == "toml-test-value"


def test_dotenv_overrides_toml_without_exporting_or_changing_directory(private_config, monkeypatch):
    (private_config / ".env").write_text(
        '\ufeffexport ELEVENLABS_API_KEY="dotenv-test-value" # selected key\n'
        'GEMINI_TTS_VERTEX_API_KEY=google-test-value\n'
    )
    elsewhere = private_config / "another-video"
    elsewhere.mkdir()
    (elsewhere / ".env").write_text('ELEVENLABS_API_KEY=wrong-project\n')
    monkeypatch.chdir(elsewhere)
    loaded = config.secrets()
    assert loaded["ELEVENLABS_API_KEY"] == "dotenv-test-value"
    assert loaded["GEMINI_TTS_VERTEX_API_KEY"] == "google-test-value"
    assert loaded["LLM_MODEL"] == "saved-model"
    assert "ELEVENLABS_API_KEY" not in os.environ
    assert (private_config / "config/secrets.toml").read_text().startswith(
        'ELEVENLABS_API_KEY = "toml-test-value"'
    )


def test_environment_has_explicit_precedence(private_config, monkeypatch):
    (private_config / ".env").write_text('ELEVENLABS_API_KEY=dotenv-test-value\n')
    monkeypatch.setenv("ELEVENLABS_API_KEY", "environment-test-value")
    monkeypatch.setenv("GEMINI_TTS_VERTEX_API_KEY", "environment-google-test-value")
    assert config.secrets()["ELEVENLABS_API_KEY"] == "environment-test-value"
    assert config.secrets()["GEMINI_TTS_VERTEX_API_KEY"] == "environment-google-test-value"


def test_empty_placeholders_preserve_working_configuration(private_config, monkeypatch):
    (private_config / ".env").write_text('ELEVENLABS_API_KEY=\nGEMINI_API_KEY=\n')
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    assert config.secrets()["ELEVENLABS_API_KEY"] == "toml-test-value"
    assert "GEMINI_API_KEY" not in config.secrets()


def test_values_are_literal_not_shell_or_variable_expansion(private_config, monkeypatch):
    monkeypatch.setenv("CONFIG_TEST_SECRET", "must-not-be-expanded")
    (private_config / ".env").write_text(
        'TEST_VALUE="${CONFIG_TEST_SECRET} $(touch should-not-exist) # literal"\n'
    )
    assert config.secrets()["TEST_VALUE"] == '${CONFIG_TEST_SECRET} $(touch should-not-exist) # literal'
    assert not (private_config / "should-not-exist").exists()


@pytest.mark.parametrize("bad_line", ['TEST_VALUE="private-test-value', 'private-test-value'])
def test_malformed_dotenv_fails_without_exposing_contents(private_config, bad_line, capsys):
    (private_config / ".env").write_text(bad_line + "\n")
    with pytest.raises(ValueError, match="Invalid .env entry") as error:
        config.secrets()
    captured = capsys.readouterr()
    assert "private-test-value" not in str(error.value) + captured.out + captured.err


def test_saved_edits_are_read_on_next_call(private_config):
    path = private_config / ".env"
    path.write_text('ELEVENLABS_API_KEY=first-test-value\n')
    assert config.secrets()["ELEVENLABS_API_KEY"] == "first-test-value"
    path.write_text('ELEVENLABS_API_KEY=second-test-value\n')
    assert config.secrets()["ELEVENLABS_API_KEY"] == "second-test-value"


def test_viral_outliers_environment_and_dotenv(private_config, monkeypatch):
    (private_config / '.env').write_text('VIRAL_OUTLIERS_API_KEY=dotenv-viral-value\n')
    monkeypatch.delenv('VIRAL_OUTLIERS_API_KEY', raising=False)
    assert config.secrets()['VIRAL_OUTLIERS_API_KEY'] == 'dotenv-viral-value'
    (private_config / '.env').unlink()
    monkeypatch.setenv('VIRAL_OUTLIERS_API_KEY', 'environment-viral-value')
    assert config.secrets()['VIRAL_OUTLIERS_API_KEY'] == 'environment-viral-value'
