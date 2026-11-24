from trtool import config
from trtool.cli import main


def test_set_get_round_trip(tmp_path, monkeypatch):
    ini = tmp_path / "trtool.ini"
    monkeypatch.delenv("TRTOOL_GAME_DIR", raising=False)
    assert config.get("game_dir", str(ini)) is None
    config.set("game_dir", r"E:\Games\Travellers Rest", str(ini))
    assert config.get("game_dir", str(ini)) == r"E:\Games\Travellers Rest"


def test_env_overrides_file(tmp_path, monkeypatch):
    ini = tmp_path / "trtool.ini"
    config.set("game_dir", "from-file", str(ini))
    monkeypatch.setenv("TRTOOL_GAME_DIR", "from-env")
    assert config.get("game_dir", str(ini)) == "from-env"


def test_cli_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRTOOL_CONFIG", str(tmp_path / "trtool.ini"))
    monkeypatch.delenv("TRTOOL_GAME_DIR", raising=False)
    main(["config", "set", "game_dir", "somewhere"])
    capsys.readouterr()
    main(["config", "get", "game_dir"])
    assert capsys.readouterr().out.strip() == "somewhere"
