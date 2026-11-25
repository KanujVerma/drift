"""Context-independent arithmetic for the bounded research weight contract."""

from collections.abc import Sequence
from decimal import MAX_EMAX, MIN_EMIN, Context, Decimal, Inexact


def weight_sum(weights: Sequence[str]) -> Decimal:
    """Sum validated plain-text weights in [0, 1] without context rounding.

    With no exponent notation, each input's fractional precision is bounded by
    its text length. The extra digits cover the carry from the number of terms.
    """
    precision = max(map(len, weights), default=1) + len(str(len(weights))) + 2
    context = Context(prec=precision, Emin=MIN_EMIN, Emax=MAX_EMAX, traps=[Inexact])
    total = Decimal(0)
    for weight in weights:
        total = context.add(total, Decimal(weight))
    return total


def within_selector_band(maximum: Decimal, score: Decimal) -> bool:
    """Decide maximum - score - 1e-9 <= 0 using sparse signed digits.

    Only input coefficient digits and the tolerance occupy positions. A carry
    of zero or minus one remains stable across an arbitrarily large empty gap;
    other carries converge to one of those values in logarithmically many
    steps. Memory and work therefore depend on input digits, not exponent gap.
    """
    positions: dict[int, int] = {-9: -1}
    for value, multiplier in ((maximum, 1), (score, -1)):
        sign, digits, exponent = value.as_tuple()
        assert isinstance(exponent, int)  # Callers pass finite base Decimals.
        multiplier *= -1 if sign else 1
        for offset, digit in enumerate(reversed(digits)):
            if digit:
                position = exponent + offset
                positions[position] = positions.get(position, 0) + multiplier * digit

    carry = 0
    has_nonzero_digit = False
    previous: int | None = None
    for position in sorted(positions):
        if previous is not None:
            gap = position - previous - 1
            while gap and carry not in (0, -1):
                carry, digit = divmod(carry, 10)
                has_nonzero_digit |= digit != 0
                gap -= 1
            if gap and carry == -1:
                has_nonzero_digit = True
        carry, digit = divmod(positions[position] + carry, 10)
        has_nonzero_digit |= digit != 0
        previous = position
    return carry < 0 or (carry == 0 and not has_nonzero_digit)
