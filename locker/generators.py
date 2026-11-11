"""Three genuinely different test-generation strategies.

All generators share the interface ``Generator(seed, max_length).generate(count)``
and return ``list[list[Command]]``. They use the *model* (never the SUT) to decide
which commands are sensible, so the model stays the single source of expected
behaviour and the strategies stay independent of the runner.

    A  RandomWalkGenerator       random operation selection, optionally biased to
                                 model-valid commands          (name: "random")
    B  CoverageGuidedGenerator   greedy + look-ahead towards the least-covered
                                 transitions                    (name: "coverage")
    C  TransitionPairGenerator   plans paths that exercise every defined adjacent
                                 transition pair                (name: "pair")

Reproducibility: every ``generate`` call builds a fresh ``random.Random(seed)``;
no set iteration order ever influences a random choice (sets are sorted first),
so output is identical across runs and across PYTHONHASHSEED values.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict, deque
from typing import Optional

from .model import LockerModel, TransitionKey, transition_catalogue, transition_pairs
from .types import Command, Operation as Op, Snapshot, State

DEFAULT_CUSTOMERS = ("C1", "C2")
WRONG_CODE = "WRONG"


# --------------------------------------------------------------------------- #
# Command alphabet (input classes)
# --------------------------------------------------------------------------- #
def candidate_commands(snap: Snapshot, customers=DEFAULT_CUSTOMERS,
                       near_miss: bool = False) -> list[Command]:
    """All command variants (input classes) worth trying from the given model state.

    Credential input classes for DEPOSIT/RETRIEVE: the *correct* code (taken from
    the model snapshot, or a plausible one if none exists), an arbitrary wrong
    code, the empty code, and the *other* credential type (cross-use). With
    ``near_miss`` a code that merely extends the correct one is added.
    Customer IDs vary for RESERVE so identity-dependent defects can surface.
    EXPIRE is tried with the flag both set and unset.
    """
    res_code = snap.reservation_code or f"R-{customers[0]}"
    ret_code = snap.retrieval_code or f"P-{customers[0]}"

    dep_codes = [res_code, WRONG_CODE, "", ret_code]
    rec_codes = [ret_code, WRONG_CODE, "", res_code]
    if near_miss:
        dep_codes.append(res_code + "x")
        rec_codes.append(ret_code + "x")

    cmds: list[Command] = [Command(Op.RESERVE, customer_id=c) for c in customers]
    cmds.append(Command(Op.CANCEL))
    cmds += [Command(Op.DEPOSIT, code=c) for c in dict.fromkeys(dep_codes)]
    cmds += [Command(Op.RETRIEVE, code=c) for c in dict.fromkeys(rec_codes)]
    cmds += [Command(Op.EXPIRE, expired=True), Command(Op.EXPIRE, expired=False)]
    cmds += [Command(Op.DISABLE), Command(Op.ENABLE)]
    cmds.append(Command(Op.INVALID_ACCESS, code="INVALID"))
    return cmds


# --------------------------------------------------------------------------- #
# Graph helpers over the model's abstract state graph
# --------------------------------------------------------------------------- #
_ACCEPTED_EDGES: dict[State, list[TransitionKey]] = defaultdict(list)
for _t in transition_catalogue():
    if _t.accepted and _t.src != _t.dst:
        _ACCEPTED_EDGES[_t.src].append(_t)


def shortest_path(src: State, goals: set[State]) -> Optional[list[TransitionKey]]:
    """Shortest list of accepted transitions from ``src`` into any state in ``goals``."""
    if src in goals:
        return []
    seen = {src}
    queue: deque = deque([(src, [])])
    while queue:
        state, path = queue.popleft()
        for t in _ACCEPTED_EDGES[state]:
            if t.dst in seen:
                continue
            if t.dst in goals:
                return path + [t]
            seen.add(t.dst)
            queue.append((t.dst, path + [t]))
    return None


def _distances(src: State) -> dict[State, int]:
    dist = {src: 0}
    queue = deque([src])
    while queue:
        s = queue.popleft()
        for t in _ACCEPTED_EDGES[s]:
            if t.dst not in dist:
                dist[t.dst] = dist[s] + 1
                queue.append(t.dst)
    return dist


def _realise(model: LockerModel, wanted: TransitionKey, rng: random.Random,
             customers, near_miss: bool) -> Command:
    """Pick a concrete command that makes the model fire exactly ``wanted``."""
    options = [c for c in candidate_commands(model.snapshot(), customers, near_miss)
               if model.peek(c) == wanted]
    if not options:  # cannot happen for catalogue transitions from the right state
        raise RuntimeError(f"no command realises {wanted.label()} from {model.state.value}")
    return rng.choice(options)


def _pair_sort_key(p):
    return (p[0].label(), p[1].label())


# --------------------------------------------------------------------------- #
# Base class
# --------------------------------------------------------------------------- #
class _Generator:
    name = "base"

    def __init__(self, seed: int, max_length: int, customers=DEFAULT_CUSTOMERS,
                 near_miss: bool = False):
        if max_length < 1:
            raise ValueError("max_length must be >= 1")
        self.seed, self.max_length = seed, max_length
        self.customers, self.near_miss = tuple(customers), near_miss

    def _cands(self, model: LockerModel) -> list[Command]:
        return candidate_commands(model.snapshot(), self.customers, self.near_miss)

    def generate(self, count: int) -> list[list[Command]]:  # pragma: no cover - abstract
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Strategy A - random / model-guided random
# --------------------------------------------------------------------------- #
class RandomWalkGenerator(_Generator):
    """Strategy A. Random walk over the command alphabet.

    * Selection: at each step, with probability ``p_valid`` pick uniformly among
      commands the model says are *valid* in the current state (guided); otherwise
      pick uniformly among *all* commands (so mostly invalid ones). ``p_valid=0``
      gives purely random testing.
    * Valid/invalid: validity is only used to bias selection; invalid commands
      are first-class and are executed, not filtered out.
    * Length: drawn uniformly from ``1..max_length`` per sequence.
    * Seeds: ``random.Random(seed)`` created inside ``generate``.
    """
    name = "random"

    def __init__(self, seed: int, max_length: int, p_valid: float = 0.5, **kw):
        super().__init__(seed, max_length, **kw)
        self.p_valid = p_valid

    def generate(self, count: int) -> list[list[Command]]:
        rng = random.Random(self.seed)
        out = []
        for _ in range(count):
            model, seq = LockerModel(), []
            for _ in range(rng.randint(1, self.max_length)):
                cands = self._cands(model)
                pool = cands
                if rng.random() < self.p_valid:
                    pool = [c for c in cands if model.is_valid(c)] or cands
                cmd = rng.choice(pool)
                model.step(cmd)
                seq.append(cmd)
            out.append(seq)
        return out


# --------------------------------------------------------------------------- #
# Strategy B - coverage-directed
# --------------------------------------------------------------------------- #
class CoverageGuidedGenerator(_Generator):
    """Strategy B. Greedy transition-coverage maximisation with look-ahead.

    Keeps a global execution count per model transition across *all* sequences it
    has generated so far. At each step:
      1. if some command fires a never-executed transition from the current
         state, pick one of those (random tie-break);
      2. else, if uncovered transitions exist elsewhere, follow the shortest
         path (over accepted transitions) towards the nearest state that still has
         one, i.e. a one-step-per-call BFS look-ahead;
      3. else (everything covered) prefer rarely-executed transitions with weight
         1 / (1 + count)^2, which keeps evening out the distribution.
    Length: uniform in ``max_length//2 .. max_length`` (long enough to travel).
    """
    name = "coverage"

    def generate(self, count: int) -> list[list[Command]]:
        rng = random.Random(self.seed)
        catalogue = transition_catalogue()
        counts: Counter = Counter()
        out = []
        for _ in range(count):
            model, seq = LockerModel(), []
            for _ in range(rng.randint(max(1, self.max_length // 2), self.max_length)):
                cmd = self._pick(model, counts, catalogue, rng)
                counts[model.peek(cmd)] += 1
                model.step(cmd)
                seq.append(cmd)
            out.append(seq)
        return out

    def _pick(self, model, counts, catalogue, rng) -> Command:
        keyed = [(c, model.peek(c)) for c in self._cands(model)]
        fresh = [c for c, k in keyed if counts[k] == 0]
        if fresh:
            return rng.choice(fresh)
        targets = {t.src for t in catalogue if counts[t] == 0}
        if targets:
            path = shortest_path(model.state, targets)
            if path:  # an uncovered transition lives elsewhere: head there
                return rng.choice([c for c, k in keyed if k == path[0]])
        weights = [1.0 / (1 + counts[k]) ** 2 for _, k in keyed]
        return rng.choices([c for c, _ in keyed], weights=weights, k=1)[0]


# --------------------------------------------------------------------------- #
# Strategy C - transition-pair / path based
# --------------------------------------------------------------------------- #
class TransitionPairGenerator(_Generator):
    """Strategy C. Plans command sequences that cover adjacent transition pairs.

    A *pair* (t1, t2) is defined when t1.dst == t2.src (see ``metrics``). The
    generator keeps the set of pairs not yet exercised and builds each sequence by
    repeatedly:
      * continuing from the last transition t1 with an uncovered pair (t1, t2); or
      * otherwise picking an uncovered pair whose t1 is *closest* (fewest accepted
        transitions) to the current state, walking there via BFS, then t1, t2.
    A plan is only started if it fits in the remaining length budget, so pairs are
    never truncated. Once every pair has been covered, pairs are re-sampled
    uniformly (new customer IDs / code variants) so the quota is still filled.
    """
    name = "pair"

    def generate(self, count: int) -> list[list[Command]]:
        rng = random.Random(self.seed)
        catalogue = transition_catalogue()
        all_pairs = sorted(transition_pairs(), key=_pair_sort_key)
        uncovered = set(all_pairs)
        out = []
        for _ in range(count):
            model, seq, last = LockerModel(), [], None
            while len(seq) < self.max_length:
                plan = self._plan(model, last, uncovered, all_pairs, rng,
                                  self.max_length - len(seq))
                if not plan and not seq:
                    # length budget too small for a 2-step pair plan: emit a single transition
                    plan = [rng.choice([t for t in catalogue if t.src == model.state])]
                if not plan:
                    break
                for wanted in plan:
                    cmd = _realise(model, wanted, rng, self.customers, self.near_miss)
                    model.step(cmd)
                    key = model.last_transition
                    if last is not None:
                        uncovered.discard((last, key))
                    last = key
                    seq.append(cmd)
            out.append(seq)
        return out

    @staticmethod
    def _plan(model, last, uncovered, all_pairs, rng, budget) -> list[TransitionKey]:
        if last is not None and budget >= 1:
            opts = sorted((p for p in uncovered if p[0] == last), key=_pair_sort_key)
            if not opts:
                opts = [p for p in all_pairs if p[0] == last]
            return [rng.choice(opts)[1]]
        return _new_target(model, uncovered or all_pairs, rng, budget)


def _new_target(model, pool, rng, budget) -> list[TransitionKey]:
    dist = _distances(model.state)
    for d in range(len(State) + 1):
        opts = sorted((p for p in pool if dist.get(p[0].src) == d and d + 2 <= budget),
                      key=_pair_sort_key)
        if opts:
            t1, t2 = rng.choice(opts)
            path = shortest_path(model.state, {t1.src}) or []
            return path + [t1, t2]
    return []

GENERATORS = {
    RandomWalkGenerator.name: RandomWalkGenerator,
    CoverageGuidedGenerator.name: CoverageGuidedGenerator,
    TransitionPairGenerator.name: TransitionPairGenerator,
}
