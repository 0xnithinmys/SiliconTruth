"""Errors caused by the input, not by a defect.

A wrong page number is not a crash, and printing a traceback for one is a
small lie about whose fault it is. It also buries the single line that
matters: a user who asks for page 412 of a 2-page PDF got forty lines of
Python frames with `page 412 out of range ... (2 pages)` in the middle.

Anything raised as a UserError is printed by `cli.app()` as one line and
nothing else. Everything else keeps its traceback, because everything else
IS a defect and the stack is the useful part.
"""

from __future__ import annotations


class UserError(Exception):
    """Bad input, reported in one line with no stack."""
