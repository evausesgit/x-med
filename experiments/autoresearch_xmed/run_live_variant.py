"""Collecte live d'une variante via le moteur commun du runner baseline."""

from experiments.autoresearch_xmed.run_live_baseline import main as shared_main


def main() -> None:
    shared_main(run_role="variant")


if __name__ == "__main__":
    main()
