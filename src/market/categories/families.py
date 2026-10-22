"""Strategies and their variants (docs/PLAN-site.md §1–2).

A *strategy* (family) is one idea on one universe — "S&P 500 Leaders". Its *variants* are the categories that
implement it: the base list, the base list plus one filter (short interest, IV, stall, RSI …), or an alternative
ranking of the same idea. Each variant has a short display name ("SPY Ldrs · SI"); SPY / MDY stand for the
S&P 500 / S&P 400 universes. Every category belongs to exactly one family.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    id: str
    name: str                  # full name
    short: str                 # display name
    section: str               # heading the family is grouped under on the site
    base: str | None           # the plain variant a filter must beat by the tie margin; None if there is none


@dataclass(frozen=True)
class Variant:
    family: str
    short: str
    filter: str | None = None  # the filter's label, for variants that skip names from a base ranking


SECTIONS = ["S&P 500 (SPY)", "S&P 400 (MDY)", "Megacap", "S&P 900 events", "Smart money"]

FAMILIES: dict[str, Family] = {f.id: f for f in [
    Family("spy_ldrs", "S&P 500 Leaders", "SPY Ldrs", SECTIONS[0], "mom12_sp500"),
    Family("spy_rank", "S&P 500 Rank Momentum", "SPY Rank Mom", SECTIONS[0], "rankmom_sp500"),
    Family("spy_steady", "S&P 500 Steady Leaders", "SPY Steady Ldrs", SECTIONS[0], "steady_sp500"),
    Family("spy_fund", "S&P 500 Fundamentals", "SPY Fundamentals", SECTIONS[0], None),
    Family("mdy_ldrs", "S&P 400 Leaders", "MDY Ldrs", SECTIONS[1], "mom12_sp400"),
    Family("mdy_rank", "S&P 400 Rank Momentum", "MDY Rank Mom", SECTIONS[1], "rankmom_sp400"),
    Family("mdy_fund", "S&P 400 Fundamentals", "MDY Fundamentals", SECTIONS[1], None),
    Family("mega_ldrs", "Megacap Leaders", "Mega Ldrs", SECTIONS[2], "mom12_megacap"),
    Family("mega_lag", "Megacap Laggards", "Mega Laggards", SECTIONS[2], "laggards_mega10"),
    Family("munger", "Munger Dip", "Munger Dip", SECTIONS[2], "munger_top50"),
    Family("dividends", "Dividend events", "Dividends", SECTIONS[3], None),
    Family("ivterm", "Inverted option term structure", "Inverted IV", SECTIONS[3], "ivinverted_sp900"),
    Family("congress", "Congress", "Congress", SECTIONS[4], None),
    Family("hedge", "13F skilled funds", "13F", SECTIONS[4], None),
]}

VARIANTS: dict[str, Variant] = {
    "mom12_sp500": Variant("spy_ldrs", "SPY Ldrs"),
    "mom12stall_sp500": Variant("spy_ldrs", "SPY Ldrs · Stall", "stall"),
    "rgrowth_sp500": Variant("spy_ldrs", "SPY Ldrs · RSI", "RSI"),
    "mom12si_sp500": Variant("spy_ldrs", "SPY Ldrs · SI", "short-interest"),
    "mom12iv_sp500": Variant("spy_ldrs", "SPY Ldrs · IV", "IV"),
    "rankmom_sp500": Variant("spy_rank", "SPY Rank Mom"),
    "rankmomiv_sp500": Variant("spy_rank", "SPY Rank Mom · IV", "IV"),
    "rankfast_sp500": Variant("spy_rank", "SPY Fast Rank Mom"),
    "steady_sp500": Variant("spy_steady", "SPY Steady Ldrs"),
    "fmom_sp500": Variant("spy_fund", "SPY Fund. Mom"),
    "rerating_sp500": Variant("spy_fund", "SPY Re-rating"),
    "shrinkers_sp500": Variant("spy_fund", "SPY Shrinkers"),
    "mom12_sp400": Variant("mdy_ldrs", "MDY Ldrs"),
    "rgrowth_sp400": Variant("mdy_ldrs", "MDY Ldrs · RSI", "RSI"),
    "mom12iv_sp400": Variant("mdy_ldrs", "MDY Ldrs · IV", "IV"),
    "rankmom_sp400": Variant("mdy_rank", "MDY Rank Mom"),
    "rankfast_sp400": Variant("mdy_rank", "MDY Fast Rank Mom"),
    "fmom_sp400": Variant("mdy_fund", "MDY Fund. Mom"),
    "emerging_sp400": Variant("mdy_fund", "MDY Emerging Ldrs"),
    "emergingall_sp400": Variant("mdy_fund", "MDY Improving Fund. & Rank"),
    "mom12_megacap": Variant("mega_ldrs", "Mega Ldrs"),
    "laggards_mega10": Variant("mega_lag", "Mega Laggards"),
    "munger_top50": Variant("munger", "Munger Dip"),
    "divraise_sp900": Variant("dividends", "Div. Raisers"),
    "divcut_sp900": Variant("dividends", "Div. Cutters"),
    "ivinverted_sp900": Variant("ivterm", "Inverted IV Term"),
    "congress_buys": Variant("congress", "Congress Buys"),
    "congress_holdings": Variant("congress", "Congress Holdings"),
    "hedge_buys": Variant("hedge", "13F Buys"),
    "hedge_drivers": Variant("hedge", "13F Drivers"),
}


def variant(category_id: str) -> Variant:
    return VARIANTS.get(category_id) or Variant("other", category_id)


def family_of(category_id: str) -> Family | None:
    return FAMILIES.get(variant(category_id).family)
