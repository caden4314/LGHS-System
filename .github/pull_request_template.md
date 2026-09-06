## Summary

Describe the production behavior changed by this PR.

## Validation

- [ ] `core-validate` passes.
- [ ] `lghs-validate` passes.
- [ ] `rollout-validate` passes.
- [ ] `zero-touch-validate` passes.
- [ ] Documentation is updated when behavior or operator workflow changes.

## Safety / rollout

- [ ] No credentials, tokens, private keys, or classroom secrets are committed.
- [ ] Student software selection remains controller-authoritative and exact-SHA based.
- [ ] Signed-release enforcement is preserved after public-key enrollment.
- [ ] Privileged changes remain typed/allowlisted rather than opening a general remote shell.
- [ ] Any required live deployment will use a validated exact merge SHA and canary-first rollout.
