"""Scrape orchestration stub (Consórcio fetch/publish lands in a later slice)."""


def run_scrape(*, force: bool = False) -> str:
    """Run a full scrape and publish. Stub until store/ingestion ownership lands."""
    del force  # reserved for lease/staging recovery (--force) in a later slice
    return "Scrape CLI stub: not implemented yet."
