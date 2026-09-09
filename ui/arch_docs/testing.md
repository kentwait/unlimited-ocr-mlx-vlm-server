# Testing

Name tests by the boundary and risk they exercise.

| Class                  | Location                            | Purpose                                                                        |
| ---------------------- | ----------------------------------- | ------------------------------------------------------------------------------ |
| Pure unit              | Co-located with feature or utility  | Schemas, transformations, deterministic business behavior                      |
| Component              | Co-located with rendered UI         | User interaction, validation, loading, empty, and failure states               |
| Server operation       | Co-located with feature server code | Persistence/provider semantics and stable errors                               |
| Route and boundary     | `tests/routes/`                     | Route contracts, loaders, server-function integration, and source dependencies |
| Composition smoke      | Focused integration test            | One small path through the real application composition                        |
| Browser E2E            | `e2e/`                              | Built application exercised through the public browser interface               |
| Performance acceptance | Design-owned location               | Only measurable normative targets in a controlled environment                  |

Unit tests isolate external I/O. Integration tests may use real infrastructure when the
integration itself is under test. Browser tests do not import application internals.

An in-process route test is not browser E2E. A full contract suite is not a focused
smoke test. Performance thresholds are not invented without a product requirement and
controlled technical design.

Every changed behavior should cover the happy path, meaningful failures, and applicable
edge conditions. Browser prerequisites must fail visibly rather than silently skipping
all acceptance evidence.
