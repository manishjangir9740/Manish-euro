"""Money value object represented in integer paise.

Never use floating-point numbers for currency arithmetic.
Shopify expects decimal strings (e.g. "104.98") at the boundary;
all internal calculations are strictly integer paise.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Union


class Money:
    """Immutable representation of monetary value in integer paise."""

    __slots__ = ("_paise",)

    def __init__(self, paise: int = 0):
        if not isinstance(paise, int):
            raise TypeError(f"Paise must be an integer, got {type(paise).__name__}")
        self._paise = paise

    @property
    def paise(self) -> int:
        return self._paise

    @classmethod
    def zero(cls) -> "Money":
        return cls(0)

    @classmethod
    def from_decimal(cls, value: Union[str, int, float, Decimal]) -> "Money":
        """Parse decimal string like '104.98' into Money(10498)."""
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value * 100)
        d = Decimal(str(value).strip().replace(",", ""))
        p = int((d * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return cls(p)

    def to_decimal(self) -> str:
        """Format as decimal string with 2 decimal places, e.g. '104.98'."""
        sign = "-" if self._paise < 0 else ""
        abs_p = abs(self._paise)
        return f"{sign}{abs_p // 100}.{abs_p % 100:02d}"

    def format_inr(self) -> str:
        """Format in Indian numbering style (e.g. ₹10,498.00)."""
        sign = "-" if self._paise < 0 else ""
        abs_p = abs(self._paise)
        rupees = abs_p // 100
        paise_str = f"{abs_p % 100:02d}"

        s = str(rupees)
        if len(s) <= 3:
            formatted_rupees = s
        else:
            last3 = s[-3:]
            rest = s[:-3]
            chunks = []
            while len(rest) > 2:
                chunks.insert(0, rest[-2:])
                rest = rest[:-2]
            if rest:
                chunks.insert(0, rest)
            formatted_rupees = ",".join(chunks) + "," + last3

        return f"{sign}₹{formatted_rupees}.{paise_str}"

    def to_words(self) -> str:
        """Convert amount to Indian English words."""
        abs_p = abs(self._paise)
        rupees = abs_p // 100
        paise_part = abs_p % 100

        units = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                 "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
                 "seventeen", "eighteen", "nineteen"]
        tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

        def two_digits(n: int) -> str:
            if n == 0:
                return ""
            if n < 20:
                return units[n]
            return (tens[n // 10] + ("-" + units[n % 10] if n % 10 != 0 else "")).strip()

        def three_digits(n: int) -> str:
            h = n // 100
            rem = n % 100
            parts = []
            if h > 0:
                parts.append(units[h] + " hundred")
            if rem > 0:
                parts.append(two_digits(rem))
            return " ".join(parts)

        if rupees == 0:
            words = "zero rupees"
        else:
            crores = rupees // 10000000
            rupees %= 10000000
            lakhs = rupees // 100000
            rupees %= 100000
            thousands = rupees // 1000
            rupees %= 1000

            res = []
            if crores > 0:
                res.append(two_digits(crores) + " crore")
            if lakhs > 0:
                res.append(two_digits(lakhs) + " lakh")
            if thousands > 0:
                res.append(two_digits(thousands) + " thousand")
            if rupees > 0:
                res.append(three_digits(rupees))
            words = " ".join(res) + " rupees"

        if paise_part > 0:
            words += f" and {two_digits(paise_part)} paise"

        return words.strip().capitalize()

    def percent_bps(self, bps: int) -> "Money":
        """Return bps basis points of this amount, rounded half-up to the paisa (integer math only)."""
        if not isinstance(bps, int):
            raise TypeError("bps must be an integer")
        num = self._paise * bps
        q, r = divmod(abs(num), 10000)
        if r * 2 >= 10000:
            q += 1
        return Money(q if num >= 0 else -q)

    def allocate(self, weights: "List[int]") -> "List[Money]":
        """Split this amount across weights (largest-remainder), so the parts sum exactly to the whole."""
        total_w = sum(weights)
        if total_w <= 0:
            return [Money.zero() for _ in weights]
        base = [self._paise * w // total_w for w in weights]
        remainders = [(self._paise * w % total_w, i) for i, w in enumerate(weights)]
        left = self._paise - sum(base)
        for _, i in sorted(remainders, key=lambda x: (-x[0], x[1]))[:left]:
            base[i] += 1
        return [Money(p) for p in base]

    # Operator overloads
    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self._paise + other._paise)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self._paise - other._paise)

    def __mul__(self, scalar: Union[int, float, Decimal]) -> "Money":
        if isinstance(scalar, (int, float, Decimal)):
            d = (Decimal(self._paise) * Decimal(str(scalar))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            return Money(int(d))
        return NotImplemented

    def __rmul__(self, scalar: Union[int, float, Decimal]) -> "Money":
        return self.__mul__(scalar)

    def __floordiv__(self, divisor: int) -> "Money":
        if not isinstance(divisor, int):
            return NotImplemented
        if divisor == 0:
            raise ZeroDivisionError("Cannot divide money by zero")
        return Money(self._paise // divisor)

    def __neg__(self) -> "Money":
        return Money(-self._paise)

    def __abs__(self) -> "Money":
        return Money(abs(self._paise))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Money):
            return self._paise == other._paise
        return False

    def __lt__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._paise < other._paise

    def __le__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._paise <= other._paise

    def __gt__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._paise > other._paise

    def __ge__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._paise >= other._paise

    def __hash__(self) -> int:
        return hash(self._paise)

    def __repr__(self) -> str:
        return f"Money({self._paise}p = '{self.to_decimal()}')"

    def __str__(self) -> str:
        return self.to_decimal()
