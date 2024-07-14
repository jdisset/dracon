
class Dracontainer(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'Dracontainer' object has no attribute '{key}'")

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError:
            raise AttributeError(f"'Dracontainer' object has no attribute '{key}'")

    # To maintain dict-like behavior when creating new instances
    @classmethod
    def fromkeys(cls, iterable, value=None):
        return cls(dict.fromkeys(iterable, value))
