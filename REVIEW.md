# Review

For a routine UI/feature/bugfix PR, inspect the diff against the request and
test evidence. Do not request a separate reviewer or test-runner agent by default.

For security, identity, privacy, protocol, state persistence, native-game,
SDK/package, installation or deployment changes, require independent code
review and the relevant comprehensive tests before the owner merges.

Review for concrete bugs, trust leaks, broken compatibility and unapproved
scope. Avoid style debates and rechecking generated/automated findings.
Paired Party/Games changes must be compatible, with their merge order clear.

Owner approves every merge and deployment. Simulation does not count as
physical phone/Pi testing.
