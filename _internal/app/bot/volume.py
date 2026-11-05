"""Volume as you hear it: a percent on a slider is how loud the sound seems, not how strongly it is scaled.

Loudness grows with roughly the 0.6th power of the sound's amplitude (about twice as loud for every 10 dB), so the
amplitude for a percent p is (p / 100) ** (1 / 0.6). 50 % then sounds half as loud as 100 %, 5 % a twentieth
(about -43 dB), and 200 % twice as loud (+10 dB), the way music players such as Spotify behave.
"""
EXPONENT = 1 / 0.6


def gain(percent: float) -> float:
    """The amplitude factor for a volume percent (100 -> 1.0)."""
    return max(0.0, float(percent) / 100) ** EXPONENT


def percent_for_gain(factor: float) -> float:
    """The volume percent that sounds as loud as scaling by `factor` (the inverse of gain)."""
    return 100 * max(0.0, float(factor)) ** (1 / EXPONENT)
