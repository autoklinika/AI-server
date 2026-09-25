"""Public ERS domain errors that must not leak database details."""


class ErsIntegrityConflict(RuntimeError):
    """An ERS write violated a domain uniqueness/FK constraint."""
