# Resolution

Markets resolve through an optimistic oracle:

1. **Propose** an outcome (bond posted).
2. **Dispute window** — anyone can dispute by posting a bond.
3. **Finalize** — if undisputed (or dispute resolved), the winning outcome is
   set and positions settle.

Admins can also create events/markets and close markets. Resolution is
permissioned; traders can propose and dispute per the configured bond.