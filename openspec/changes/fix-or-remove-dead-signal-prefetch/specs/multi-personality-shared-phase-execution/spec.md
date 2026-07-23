## ADDED Requirements

### Requirement: Shared data cache advertises only real prefetches
The multi-personality shared data cache SHALL only expose prefetch stages and getters that are actually populated; dead prefetch paths SHALL be removed rather than silently returning empty results.

#### Scenario: DeepEar prefetch chain removed
- **WHEN** SharedDataCache.prefetch_all runs with deepear_intelligence among the analysts
- **THEN** no DeepEar prefetch is attempted and no deepear_fetch_time stat is reported (the previous chain never produced data)
