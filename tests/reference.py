"""Independent, deliberately simple five-card oracle for engine verification."""
from collections import Counter


def reference_five(cards):
    ranks = sorted((card.rank for card in cards), reverse=True)
    groups = sorted(((count, rank) for rank, count in Counter(ranks).items()), reverse=True)
    flush = len({card.suit for card in cards}) == 1
    distinct = sorted(set(ranks), reverse=True)
    straight = 0
    if distinct == [14, 5, 4, 3, 2]:
        straight = 5
    elif len(distinct) == 5 and distinct[0] - distinct[-1] == 4:
        straight = distinct[0]
    if flush and straight:
        return (8, straight)
    if groups[0][0] == 4:
        return (7, groups[0][1], groups[1][1])
    if [group[0] for group in groups] == [3, 2]:
        return (6, groups[0][1], groups[1][1])
    if flush:
        return (5, *ranks)
    if straight:
        return (4, straight)
    shape = [group[0] for group in groups]
    if shape == [3, 1, 1]:
        return (3, *(rank for _, rank in groups))
    if shape == [2, 2, 1]:
        return (2, *(rank for _, rank in groups))
    if shape == [2, 1, 1, 1]:
        return (1, *(rank for _, rank in groups))
    return (0, *ranks)
