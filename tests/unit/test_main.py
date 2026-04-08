from pathlib import Path

from main import build_parser


def test_build_parser_accepts_config_argument() -> None:
    parser = build_parser()
    args = parser.parse_args(["--config", "config/sim_account.yaml"])

    assert Path(args.config) == Path("config/sim_account.yaml")
