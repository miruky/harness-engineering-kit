---
id: DETAIL-RESULT
kind: detail
depends_on: [BASIC-RESULT]
artifacts:
  - path: project/app/result.json
    role: implementation
  - path: project/checks/verify.py
    role: test
    verifies: [REQ-RESULT]
  - path: project/docs/policy.md
    role: configuration
---

# Detailed verification

The verifier emits a fresh JUnit report. Assertion failures are Red; startup errors and skipped tests are not.
Green requires the same test source and executed case identities, with every assertion passing.
Review reasons describe what was checked; hashes detect stale inputs, not semantic correctness.
