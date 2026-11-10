"""The workbench: the only place where a human operator approves run sheets and controls stages.

``auth`` holds operator credentials, sessions and the entry decision; ``api`` builds the ``/wb``
router. Model roles authenticate with their own bearer tokens and can only submit drafts.
"""
