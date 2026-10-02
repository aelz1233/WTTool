"""Per-profile undo / redo history for HUD layouts."""

import copy


class LayoutHistory:
    def __init__(self):
        self.states = {}
        self.future = {}

    def record(self, profiles):
        for key, groups in profiles.items():
            past = self.states.setdefault(key, [])
            if not past or past[-1] != groups:
                past.append(copy.deepcopy(groups))
                del past[:-100]
                self.future[key] = []

    def undo(self, key):
        past = self.states.get(key, [])
        if len(past) < 2:
            return None
        self.future.setdefault(key, []).append(past.pop())
        return copy.deepcopy(past[-1])

    def redo(self, key):
        future = self.future.get(key, [])
        if not future:
            return None
        groups = future.pop()
        self.states[key].append(copy.deepcopy(groups))
        return copy.deepcopy(groups)
