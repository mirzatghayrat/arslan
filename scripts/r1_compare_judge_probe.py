"""Retired calibration probe; retained to stop old commands safely.

The previous corpus included unsupported facts in a supposedly better answer,
and its better>=1 gate no longer represented production acceptance. Keeping
those live calls available would produce a misleading quality verdict.
"""


def main() -> None:
    raise SystemExit(
        "Retired probe: its tiny synthetic corpus and obsolete better>=1 gate do not "
        "validate the current replay gate. No provider calls were made. See "
        "docs/EVALUATION.md for the replacement acceptance protocol."
    )


if __name__ == "__main__":
    main()
