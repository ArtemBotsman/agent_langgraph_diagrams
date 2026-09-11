# Benchmark changelog

## 2026-09-09 — pre-hidden freeze correction E-001

Before any hidden live evaluation, the equivalence policy gained
`allow_uc_split_merge=true`. The change does not alter inputs, gold actors,
milestones, branches or trace targets; it makes explicit that several valid UC
boundary decompositions may realize the same required semantics. The author-level
freeze hashes were regenerated afterwards. No prompt or threshold was tuned on a
hidden output.
