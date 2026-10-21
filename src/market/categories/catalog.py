"""Importing this registers every category (momentum, reversion, Congress, 13F)."""

import market.categories.momentum  # noqa: F401
import market.categories.smartmoney  # noqa: F401
import market.categories.option_flow  # noqa: F401
import market.categories.fundamentals  # noqa: F401
import market.categories.earnings  # noqa: F401
import market.categories.dividends  # noqa: F401
import market.categories.steady  # noqa: F401
import market.categories.short_interest  # noqa: F401
import market.categories.convergence  # noqa: F401  (last: reads the other categories' stored lists)
